"""Integration tests for tenant-scoped commerce reporting."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.executive.service import ExecutiveCopilotService
from app.db.base import Base
from app.db.session import Database
from app.models import (
    Dispute,
    DisputeStatus,
    Invoice,
    InvoiceStatus,
    Payout,
    PayoutStatus,
    Transaction,
    TransactionStatus,
    User,
    UserRole,
    UserStatus,
    Vendor,
    VendorStatus,
)
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    CopilotOverview,
    CopilotQuestion,
    DashboardSummary,
    DashboardTrends,
)
from app.services.analytics import AnalyticsService


@pytest.fixture
async def commerce_session() -> AsyncIterator[AsyncSession]:
    database = Database(SecretStr("sqlite+aiosqlite:///:memory:"))
    async with database.engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with database.session_factory() as session:
            yield session
    finally:
        await database.dispose()


async def _seed_reporting_data(
    session: AsyncSession,
) -> tuple[User, Vendor, Vendor, datetime]:
    now = datetime.now(UTC)
    owner = User(
        email="owner@example.test",
        display_name="Owner",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    other_owner = User(
        email="other@example.test",
        display_name="Other",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    session.add_all([owner, other_owner])
    await session.flush()
    vendor = Vendor(
        owner_user_id=owner.id,
        name="Northwind",
        status=VendorStatus.ACTIVE,
    )
    other_vendor = Vendor(
        owner_user_id=other_owner.id,
        name="Contoso",
        status=VendorStatus.ACTIVE,
    )
    await session.flush()
    session.add_all([vendor, other_vendor])
    await session.flush()
    current_transaction = Transaction(
        vendor_id=vendor.id,
        status=TransactionStatus.CAPTURED,
        amount=Decimal("125.00"),
        currency="USD",
        occurred_at=now - timedelta(days=5),
        paypal_transaction_id="current-transaction",
    )
    previous_transaction = Transaction(
        vendor_id=vendor.id,
        status=TransactionStatus.CAPTURED,
        amount=Decimal("100.00"),
        currency="USD",
        occurred_at=now - timedelta(days=35),
        paypal_transaction_id="previous-transaction",
    )
    other_transaction = Transaction(
        vendor_id=other_vendor.id,
        status=TransactionStatus.CAPTURED,
        amount=Decimal("999.00"),
        currency="USD",
        occurred_at=now - timedelta(days=5),
        paypal_transaction_id="other-tenant-transaction",
    )
    other_currency_transaction = Transaction(
        vendor_id=vendor.id,
        status=TransactionStatus.CAPTURED,
        amount=Decimal("15.00"),
        currency="EUR",
        occurred_at=now - timedelta(days=4),
        paypal_transaction_id="eur-transaction",
    )
    session.add_all(
        [
            current_transaction,
            previous_transaction,
            other_transaction,
            other_currency_transaction,
        ]
    )
    await session.flush()
    session.add_all(
        [
            Dispute(
                vendor_id=vendor.id,
                transaction_id=current_transaction.id,
                external_dispute_id="case-100",
                reason="item not received",
                status=DisputeStatus.NEEDS_RESPONSE,
                amount=Decimal("125.00"),
                currency="USD",
                opened_at=now - timedelta(days=5),
                response_due_at=now - timedelta(days=1),
            ),
            Invoice(
                vendor_id=vendor.id,
                invoice_number="INV-100",
                status=InvoiceStatus.OVERDUE,
                amount=Decimal("75.00"),
                currency="USD",
                due_at=now - timedelta(days=2),
            ),
            Invoice(
                vendor_id=vendor.id,
                invoice_number="INV-200",
                status=InvoiceStatus.OVERDUE,
                amount=Decimal("30.00"),
                currency="EUR",
                due_at=now - timedelta(days=1),
            ),
            Payout(
                vendor_id=vendor.id,
                requested_by_user_id=owner.id,
                status=PayoutStatus.PENDING_APPROVAL,
                amount=Decimal("25.00"),
                currency="USD",
            ),
        ]
    )
    await session.commit()
    return owner, vendor, other_vendor, now


async def test_reporting_aggregates_and_lists_are_tenant_scoped(
    commerce_session: AsyncSession,
) -> None:
    owner, vendor, other_vendor, now = await _seed_reporting_data(commerce_session)
    repository = AnalyticsRepository(commerce_session, owner.id)
    current_start = now - timedelta(days=30)
    previous_start = now - timedelta(days=60)

    revenue = await repository.revenue_periods(
        previous_start=previous_start,
        current_start=current_start,
        end=now + timedelta(seconds=1),
    )
    assert revenue == [
        ("EUR", Decimal("15.00"), Decimal(0), 1),
        ("USD", Decimal("125.00"), Decimal("100.00"), 1),
    ]

    disputes, total = await repository.list_disputes(
        offset=0,
        limit=10,
        status_filter=None,
        search=None,
    )
    assert total == 1
    assert disputes[0][0].vendor_id == vendor.id
    assert disputes[0][1] == "Northwind"
    assert other_vendor.id != disputes[0][0].vendor_id

    service = AnalyticsService(commerce_session, owner.id)
    summary = await service.dashboard_summary()
    revenue_by_currency = {item.currency: item for item in summary.revenue}
    assert revenue_by_currency["USD"].gross_volume == Decimal("125.00")
    assert revenue_by_currency["USD"].previous_gross_volume == Decimal("100.00")
    assert revenue_by_currency["EUR"].gross_volume == Decimal("15.00")
    assert summary.disputes.open_count == 1
    assert summary.disputes.overdue_count == 1
    assert summary.invoices.overdue_count == 2
    overdue_by_currency = {
        item.currency: item for item in summary.invoices.overdue_amount
    }
    assert overdue_by_currency["EUR"].amount == Decimal("30.00")
    assert overdue_by_currency["USD"].amount == Decimal("75.00")
    assert summary.payouts.pending_approval_count == 1
    assert summary.payouts.pending_approval_amount[0].amount == Decimal("25.00")
    assert summary.vendors.total == 1


class CapturingNarrativeGenerator:
    def __init__(self) -> None:
        self.question = ""
        self.currencies: set[str] = set()
        self.closed = False

    async def generate(
        self,
        question: str,
        summary: DashboardSummary,
        trends: DashboardTrends,
        overview: CopilotOverview,
    ) -> str:
        self.question = question
        self.currencies = {item.currency for item in summary.revenue}
        assert trends.days == 30
        assert overview.insights
        return "Review overdue receivables and dispute deadlines."

    async def aclose(self) -> None:
        self.closed = True


async def test_copilot_uses_currency_specific_aggregate_context(
    commerce_session: AsyncSession,
) -> None:
    owner, _vendor, _other_vendor, _now = await _seed_reporting_data(commerce_session)
    generator = CapturingNarrativeGenerator()
    service = ExecutiveCopilotService(
        commerce_session,
        owner.id,
        narrative_generator=generator,
    )

    answer = await service.answer(CopilotQuestion(question="What should I review?"))
    await service.aclose()

    assert answer.answer == "Review overdue receivables and dispute deadlines."
    assert generator.question == "What should I review?"
    assert generator.currencies == {"EUR", "USD"}
    assert generator.closed


async def test_reporting_search_treats_like_wildcards_literally(
    commerce_session: AsyncSession,
) -> None:
    owner, _vendor, _other_vendor, _now = await _seed_reporting_data(commerce_session)
    repository = AnalyticsRepository(commerce_session, owner.id)

    rows, total = await repository.list_disputes(
        offset=0,
        limit=10,
        status_filter=None,
        search="%",
    )

    assert rows == []
    assert total == 0


async def test_dashboard_trends_rejects_unbounded_period(
    commerce_session: AsyncSession,
) -> None:
    service = AnalyticsService(commerce_session, uuid4())

    with pytest.raises(ValueError, match="between 7 and 90"):
        await service.dashboard_trends(days=365)
