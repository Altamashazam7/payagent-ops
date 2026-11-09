"""Deterministic, synthetic commerce records for product demonstrations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from app.db.base import Base
from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.dispute import Dispute
from app.models.enums import (
    AgentStatus,
    AuditEntityType,
    DecisionStatus,
    DisputeStatus,
    InvoiceStatus,
    PayoutStatus,
    TransactionStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)
from app.models.invoice import Invoice
from app.models.payout import Payout
from app.models.transaction import Transaction
from app.models.user import User
from app.models.vendor import Vendor

DEMO_OWNER_ID = uuid5(NAMESPACE_URL, "payagent-ops/demo/tenant-owner")
DEMO_OWNER_EMAIL = "demo-owner@payagent.invalid"
_VENDOR_NAMES = (
    "Northstar Outfitters",
    "Harbor & Pine",
    "Fieldwork Supply",
    "Juniper Home",
)


@dataclass(slots=True)
class DemoDataset:
    """Ordered model groups that can be inserted in one database transaction."""

    users: list[User]
    vendors: list[Vendor]
    transactions: list[Transaction]
    disputes: list[Dispute]
    invoices: list[Invoice]
    payouts: list[Payout]
    agents: list[Agent]
    decisions: list[Decision]
    audit_logs: list[AuditLog]

    def groups(self) -> tuple[Sequence[Base], ...]:
        """Return groups in foreign-key insertion order."""
        return (
            self.users,
            self.vendors,
            self.transactions,
            self.disputes,
            self.invoices,
            self.payouts,
            self.agents,
            self.decisions,
            self.audit_logs,
        )


def build_demo_dataset(*, now: datetime | None = None) -> DemoDataset:
    """Build one deterministic tenant populated only with synthetic data."""
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must include a timezone")
    timestamp = timestamp.astimezone(UTC)

    owner = User(
        id=DEMO_OWNER_ID,
        email=DEMO_OWNER_EMAIL,
        display_name="PayAgent Demo Operator",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        created_at=timestamp,
        updated_at=timestamp,
    )
    vendors = [
        Vendor(
            id=_id(f"vendor-{index}"),
            owner_user_id=owner.id,
            name=name,
            status=VendorStatus.ACTIVE,
            paypal_merchant_id=None,
            created_at=timestamp - timedelta(days=180 - 12 * index),
            updated_at=timestamp,
        )
        for index, name in enumerate(_VENDOR_NAMES, start=1)
    ]

    transactions: list[Transaction] = []
    for vendor_index, vendor in enumerate(vendors):
        for item_index in range(20):
            number = vendor_index * 20 + item_index + 1
            occurred_at = timestamp - timedelta(days=(number * 7) % 90)
            transactions.append(
                Transaction(
                    id=_id(f"transaction-{number}"),
                    vendor_id=vendor.id,
                    paypal_transaction_id=f"DEMO-TXN-{number:04d}",
                    paypal_order_id=f"DEMO-ORDER-{number:04d}",
                    paypal_capture_id=f"DEMO-CAPTURE-{number:04d}",
                    amount=Decimal(45 + (number * 29) % 960),
                    currency="USD" if number % 4 else "EUR",
                    status=(
                        TransactionStatus.REFUNDED
                        if number % 13 == 0
                        else TransactionStatus.CAPTURED
                    ),
                    description=f"Synthetic sale {number:04d}",
                    occurred_at=occurred_at,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
            )

    disputes: list[Dispute] = []
    for number in range(1, 9):
        transaction = transactions[(number * 7) - 1]
        opened_at = timestamp - timedelta(days=number * 3)
        disputes.append(
            Dispute(
                id=_id(f"dispute-{number}"),
                vendor_id=transaction.vendor_id,
                transaction_id=transaction.id,
                external_dispute_id=f"DEMO-DSP-{number:03d}",
                reason=("item_not_received" if number % 2 else "duplicate"),
                amount=transaction.amount,
                currency=transaction.currency,
                status=(
                    DisputeStatus.NEEDS_RESPONSE
                    if number % 3
                    else DisputeStatus.UNDER_REVIEW
                ),
                opened_at=opened_at,
                response_due_at=timestamp + timedelta(days=number - 5),
                created_at=opened_at,
                updated_at=timestamp,
            )
        )

    invoices: list[Invoice] = []
    for number in range(1, 13):
        transaction = transactions[number - 1]
        due_at = timestamp + timedelta(days=number - 7)
        status = (
            InvoiceStatus.PAID
            if number % 4 == 0
            else InvoiceStatus.OVERDUE
            if due_at < timestamp
            else InvoiceStatus.SENT
        )
        invoices.append(
            Invoice(
                id=_id(f"invoice-{number}"),
                vendor_id=transaction.vendor_id,
                transaction_id=transaction.id,
                invoice_number=f"DEMO-INV-{number:04d}",
                amount=transaction.amount,
                currency=transaction.currency,
                status=status,
                due_at=due_at,
                paid_at=timestamp - timedelta(days=1)
                if status is InvoiceStatus.PAID
                else None,
                description=f"Synthetic order {number:04d}",
                billing_email=None,
                created_at=timestamp - timedelta(days=35 - number),
                updated_at=timestamp,
            )
        )

    payouts = [
        Payout(
            id=_id(f"payout-{number}"),
            vendor_id=vendors[(number - 1) % len(vendors)].id,
            requested_by_user_id=owner.id,
            amount=Decimal(250 + number * 175),
            currency="USD" if number % 3 else "EUR",
            status=PayoutStatus.PENDING_APPROVAL,
            reference=f"Synthetic weekly settlement {number:02d}",
            created_at=timestamp - timedelta(days=number * 2),
            updated_at=timestamp,
        )
        for number in range(1, 9)
    ]

    agent_specs = (
        ("Dispute Defense", "dispute_defense"),
        ("Invoice Compliance", "invoice_compliance"),
        ("Smart Payout", "smart_payout"),
    )
    agents = [
        Agent(
            id=_id(f"agent-{vendor_index}-{agent_type}"),
            vendor_id=vendor.id,
            created_by_user_id=owner.id,
            name=name,
            agent_type=agent_type,
            model_name="demo-rule-engine",
            status=AgentStatus.ACTIVE,
            created_at=timestamp - timedelta(days=30),
            updated_at=timestamp,
        )
        for vendor_index, vendor in enumerate(vendors, start=1)
        for name, agent_type in agent_specs
    ]
    agents_by_vendor_and_type = {
        (agent.vendor_id, agent.agent_type): agent for agent in agents
    }

    decisions = [
        Decision(
            id=_id(f"decision-dispute-{number}"),
            vendor_id=disputes[number - 1].vendor_id,
            agent_id=agents_by_vendor_and_type[
                (disputes[number - 1].vendor_id, "dispute_defense")
            ].id,
            dispute_id=disputes[number - 1].id,
            action_type="review_dispute",
            recommendation="Review the synthetic evidence package before deciding.",
            rationale="Synthetic demonstration recommendation; no action was taken.",
            confidence=Decimal("0.780"),
            status=DecisionStatus.PENDING,
            created_at=timestamp - timedelta(days=number),
            updated_at=timestamp,
        )
        for number in range(1, 5)
    ]
    decisions.extend(
        Decision(
            id=_id(f"decision-invoice-{number}"),
            vendor_id=invoices[number - 1].vendor_id,
            agent_id=agents_by_vendor_and_type[
                (invoices[number - 1].vendor_id, "invoice_compliance")
            ].id,
            invoice_id=invoices[number - 1].id,
            action_type="review_invoice",
            recommendation="Review the synthetic invoice completeness summary.",
            rationale="Synthetic demonstration recommendation; no action was taken.",
            confidence=Decimal("0.820"),
            status=DecisionStatus.PENDING,
            created_at=timestamp - timedelta(days=number),
            updated_at=timestamp,
        )
        for number in range(1, 5)
    )

    audit_logs = [
        AuditLog(
            id=_id(f"audit-vendor-{number}"),
            entity_type=AuditEntityType.VENDOR,
            entity_id=vendors[number - 1].id,
            vendor_id=vendors[number - 1].id,
            actor_user_id=owner.id,
            action="demo.seeded",
            before_state=None,
            after_state={"synthetic": True},
            request_id=f"demo-seed-{number}",
            created_at=timestamp,
            updated_at=timestamp,
        )
        for number in range(1, 5)
    ]

    return DemoDataset(
        users=[owner],
        vendors=vendors,
        transactions=transactions,
        disputes=disputes,
        invoices=invoices,
        payouts=payouts,
        agents=agents,
        decisions=decisions,
        audit_logs=audit_logs,
    )


def _id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"payagent-ops/demo/{name}")
