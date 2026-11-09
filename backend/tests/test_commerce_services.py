"""Integration tests for typed commerce services and repositories."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.models.decision import Decision
from app.models.dispute import Dispute
from app.models.enums import (
    AuditEntityType,
    DecisionStatus,
    DisputeStatus,
    PayoutStatus,
)
from app.models.payout import Payout
from app.repositories.commerce import UserRepository
from app.schemas.commerce import (
    AgentCreate,
    AuditLogCreate,
    DecisionCreate,
    DisputeCreate,
    InvoiceCreate,
    PayoutCreate,
    TransactionCreate,
    UserCreate,
    VendorCreate,
)
from app.services.commerce import (
    AgentService,
    AuditLogService,
    DecisionService,
    DisputeService,
    InvoiceService,
    PayoutService,
    TransactionService,
    UserService,
    VendorService,
)


async def test_services_persist_vendor_commerce_graph_and_keep_approval_pending(
    database: Database,
) -> None:
    session_factory = database.session_factory
    async with session_factory() as session:
        assert isinstance(session, AsyncSession)
        user = await UserService(session).create(
            UserCreate(email="ops@example.com", display_name="Ops User")
        )
        vendor = await VendorService(session).create(
            VendorCreate(owner_user_id=user.id, name="Merchant")
        )
        transaction = await TransactionService(session).create(
            TransactionCreate(
                vendor_id=vendor.id,
                created_by_user_id=user.id,
                paypal_transaction_id="PAYMENT-001",
                amount=Decimal("100.00"),
                currency="USD",
            )
        )
        dispute = await DisputeService(session).create(
            DisputeCreate(
                vendor_id=vendor.id,
                transaction_id=transaction.id,
                external_dispute_id="DISPUTE-001",
                reason="product_not_received",
                amount=Decimal("100.00"),
                currency="USD",
                response_due_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        invoice = await InvoiceService(session).create(
            InvoiceCreate(
                vendor_id=vendor.id,
                invoice_number="INV-001",
                amount=Decimal("100.00"),
                currency="USD",
                billing_email="billing@example.com",
            )
        )
        payout = await PayoutService(session).create(
            PayoutCreate(
                vendor_id=vendor.id,
                requested_by_user_id=user.id,
                amount=Decimal("50.00"),
                currency="USD",
            )
        )
        agent = await AgentService(session).create(
            AgentCreate(
                vendor_id=vendor.id,
                created_by_user_id=user.id,
                name="Dispute review",
                agent_type="dispute_reviewer",
                model_name="gpt-example",
            )
        )
        decision = await DecisionService(session).create(
            DecisionCreate(
                vendor_id=vendor.id,
                agent_id=agent.id,
                dispute_id=dispute.id,
                action_type="prepare_evidence",
                recommendation="Collect delivery confirmation",
                confidence=Decimal("0.875"),
            )
        )
        audit_log = await AuditLogService(session).create(
            AuditLogCreate(
                entity_type=AuditEntityType.INVOICE,
                entity_id=invoice.id,
                vendor_id=vendor.id,
                actor_user_id=user.id,
                action="invoice.created",
                after_state={
                    "invoice_number": "INV-001",
                    "line_items": [{"description": "Order", "amount": "100.00"}],
                },
            )
        )

        assert transaction.currency == "USD"
        assert invoice.billing_email == "billing@example.com"
        assert payout.status == PayoutStatus.PENDING_APPROVAL
        assert decision.status == DecisionStatus.PENDING
        assert audit_log.entity_id == invoice.id
        assert audit_log.after_state == {
            "invoice_number": "INV-001",
            "line_items": [{"description": "Order", "amount": "100.00"}],
        }
        assert len(await TransactionService(session).list_for_vendor(vendor.id)) == 1
        assert (
            len(
                await DisputeService(session).list_actionable(
                    vendor.id,
                    due_before=datetime.now(UTC) + timedelta(days=2),
                )
            )
            == 1
        )
        assert (
            len(await DecisionService(session).list_pending_for_vendor(vendor.id)) == 1
        )
        assert (
            len(
                await AuditLogService(session).list_for_entity(
                    AuditEntityType.INVOICE,
                    invoice.id,
                )
            )
            == 1
        )


async def test_soft_delete_is_audited_and_hidden_by_default(
    database: Database,
) -> None:
    async with database.session_factory() as session:
        user_service = UserService(session)
        user = await user_service.create(
            UserCreate(email="delete@example.com", display_name="Delete Me")
        )

        assert await user_service.soft_delete(user.id, actor_user_id=user.id)
        assert await user_service.get_by_id(user.id) is None

        deleted_user = await UserRepository(
            session,
            include_deleted=True,
        ).get_by_id(user.id)
        assert deleted_user is not None
        assert deleted_user.deleted_at is not None
        assert deleted_user.deleted_by_user_id == user.id


async def test_database_enforces_vendor_scope_and_human_payout_approval(
    database: Database,
) -> None:
    async with database.session_factory() as session:
        user = await UserService(session).create(
            UserCreate(email="scope@example.com", display_name="Scope User")
        )
        vendor_a = await VendorService(session).create(
            VendorCreate(owner_user_id=user.id, name="Vendor A")
        )
        vendor_b = await VendorService(session).create(
            VendorCreate(owner_user_id=user.id, name="Vendor B")
        )
        transaction = await TransactionService(session).create(
            TransactionCreate(
                vendor_id=vendor_a.id,
                amount=Decimal("10.00"),
                currency="USD",
            )
        )

        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Dispute(
                        vendor_id=vendor_b.id,
                        transaction_id=transaction.id,
                        external_dispute_id="DISPUTE-CROSS-VENDOR",
                        reason="product_not_received",
                        amount=Decimal("10.00"),
                        currency="USD",
                        status=DisputeStatus.NEEDS_RESPONSE,
                    )
                )
                await session.flush()

        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Payout(
                        vendor_id=vendor_a.id,
                        requested_by_user_id=user.id,
                        amount=Decimal("5.00"),
                        currency="USD",
                        status=PayoutStatus.APPROVED,
                    )
                )
                await session.flush()


async def test_database_requires_decision_subject(database: Database) -> None:
    async with database.session_factory() as session:
        user = await UserService(session).create(
            UserCreate(email="decision@example.com", display_name="Decision User")
        )
        vendor = await VendorService(session).create(
            VendorCreate(owner_user_id=user.id, name="Decision Vendor")
        )

        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Decision(
                        vendor_id=vendor.id,
                        action_type="review",
                        recommendation="Review the underlying record",
                    )
                )
                await session.flush()
