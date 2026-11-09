"""Application services for tenant-scoped commerce reporting."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    AgentStatus,
    DecisionStatus,
    DisputeStatus,
    InvoiceStatus,
    PayoutStatus,
    VendorStatus,
)
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    ActivityRow,
    AgentMetrics,
    AmountByCurrency,
    DashboardSummary,
    DashboardTrends,
    DisputeMetrics,
    DisputeRow,
    DisputeTrendPoint,
    InvoiceMetrics,
    InvoiceRow,
    Page,
    PayoutMetrics,
    PayoutRow,
    RevenueMetric,
    RevenueTrendPoint,
    RiskMetrics,
    VendorMetrics,
)

ZERO = Decimal(0)
OPEN_DISPUTE_STATUSES = {
    DisputeStatus.NEEDS_RESPONSE,
    DisputeStatus.UNDER_REVIEW,
}
OUTSTANDING_INVOICE_STATUSES = {InvoiceStatus.SENT, InvoiceStatus.OVERDUE}
IN_FLIGHT_PAYOUT_STATUSES = {PayoutStatus.APPROVED, PayoutStatus.PROCESSING}


class AnalyticsService:
    """Coordinate aggregate and paged reads without owning HTTP concerns."""

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self._repository = AnalyticsRepository(session, tenant_id)

    async def dashboard_summary(self) -> DashboardSummary:
        now = datetime.now(UTC)
        current_start = now - timedelta(days=30)
        previous_start = current_start - timedelta(days=30)
        revenue_rows = await self._repository.revenue_periods(
            previous_start=previous_start,
            current_start=current_start,
            end=now,
        )
        revenue: list[RevenueMetric] = []
        for currency, current_raw, previous_raw, count_raw in revenue_rows:
            current = current_raw or ZERO
            previous = previous_raw or ZERO
            count = int(count_raw or 0)
            average = (current / count).quantize(Decimal("0.01")) if count else ZERO
            change = (
                ((current - previous) / previous * Decimal(100)).quantize(
                    Decimal("0.01")
                )
                if previous > 0
                else None
            )
            revenue.append(
                RevenueMetric(
                    currency=currency,
                    gross_volume=current,
                    previous_gross_volume=previous,
                    transaction_count=count,
                    average_ticket=average,
                    change_percent=change,
                )
            )

        dispute_counts = await self._repository.dispute_status_counts()
        open_disputes = sum(
            dispute_counts.get(status, 0) for status in OPEN_DISPUTE_STATUSES
        )
        won = dispute_counts.get(DisputeStatus.WON, 0)
        lost = dispute_counts.get(DisputeStatus.LOST, 0)
        resolved = won + lost
        win_rate = (
            (Decimal(won) * Decimal(100) / Decimal(resolved)).quantize(Decimal("0.01"))
            if resolved
            else None
        )
        overdue_disputes, due_soon_disputes = await self._repository.dispute_due_counts(
            now=now,
            due_soon_at=now + timedelta(days=7),
        )
        opened_current, opened_previous = await self._repository.dispute_opened_periods(
            previous_start=previous_start,
            current_start=current_start,
            end=now,
        )
        dispute_exposure = [
            AmountByCurrency(
                currency=currency,
                amount=amount or ZERO,
                count=int(count or 0),
            )
            for currency, amount, count in await self._repository.open_dispute_exposure()
        ]

        invoice_rows = await self._repository.invoice_status_buckets()
        outstanding_by_currency: dict[str, AmountByCurrency] = {}
        overdue_by_currency: dict[str, AmountByCurrency] = {}
        outstanding_count = 0
        overdue_count = 0
        for invoice_status, currency, amount, count_raw in invoice_rows:
            count = int(count_raw or 0)
            if invoice_status in OUTSTANDING_INVOICE_STATUSES:
                outstanding_count += count
                current_bucket = outstanding_by_currency.get(
                    currency,
                    AmountByCurrency(currency=currency, amount=ZERO, count=0),
                )
                outstanding_by_currency[currency] = AmountByCurrency(
                    currency=currency,
                    amount=current_bucket.amount + (amount or ZERO),
                    count=current_bucket.count + count,
                )
            if invoice_status is InvoiceStatus.OVERDUE:
                overdue_count += count
                current_bucket = overdue_by_currency.get(
                    currency,
                    AmountByCurrency(currency=currency, amount=ZERO, count=0),
                )
                overdue_by_currency[currency] = AmountByCurrency(
                    currency=currency,
                    amount=current_bucket.amount + (amount or ZERO),
                    count=current_bucket.count + count,
                )

        payout_rows = await self._repository.payout_status_buckets()
        pending_by_currency: dict[str, AmountByCurrency] = {}
        pending_count = 0
        in_flight_count = 0
        failed_count = 0
        for payout_status, currency, amount, count_raw in payout_rows:
            count = int(count_raw or 0)
            if payout_status is PayoutStatus.PENDING_APPROVAL:
                pending_count += count
                current_bucket = pending_by_currency.get(
                    currency,
                    AmountByCurrency(currency=currency, amount=ZERO, count=0),
                )
                pending_by_currency[currency] = AmountByCurrency(
                    currency=currency,
                    amount=current_bucket.amount + (amount or ZERO),
                    count=current_bucket.count + count,
                )
            if payout_status in IN_FLIGHT_PAYOUT_STATUSES:
                in_flight_count += count
            if payout_status is PayoutStatus.FAILED:
                failed_count += count

        vendor_counts = await self._repository.vendor_status_counts()
        agent_counts = await self._repository.agent_status_counts()
        decision_counts = await self._repository.decision_counts()
        pending_decisions = sum(
            count
            for (status, _action), count in decision_counts.items()
            if status is DecisionStatus.PENDING
        )
        manual_review_decisions = sum(
            count
            for (status, action), count in decision_counts.items()
            if status is DecisionStatus.PENDING and action == "manual_review"
        )

        return DashboardSummary(
            generated_at=now,
            period_start=current_start,
            period_end=now,
            revenue=revenue,
            disputes=DisputeMetrics(
                open_count=open_disputes,
                due_soon_count=due_soon_disputes,
                overdue_count=overdue_disputes,
                open_exposure=dispute_exposure,
                win_rate=win_rate,
                opened_last_30_days=opened_current,
                opened_previous_30_days=opened_previous,
            ),
            invoices=InvoiceMetrics(
                outstanding_count=outstanding_count,
                overdue_count=overdue_count,
                outstanding_amount=sorted(
                    outstanding_by_currency.values(),
                    key=lambda item: item.currency,
                ),
                overdue_amount=sorted(
                    overdue_by_currency.values(),
                    key=lambda item: item.currency,
                ),
            ),
            payouts=PayoutMetrics(
                pending_approval_count=pending_count,
                pending_approval_amount=sorted(
                    pending_by_currency.values(),
                    key=lambda item: item.currency,
                ),
                in_flight_count=in_flight_count,
                failed_count=failed_count,
            ),
            risk=RiskMetrics(
                overdue_disputes=overdue_disputes,
                pending_decisions=pending_decisions,
                manual_review_decisions=manual_review_decisions,
                overdue_invoices=overdue_count,
                failed_payouts=failed_count,
            ),
            vendors=VendorMetrics(
                total=sum(vendor_counts.values()),
                active=vendor_counts.get(VendorStatus.ACTIVE, 0),
                pending=vendor_counts.get(VendorStatus.PENDING, 0),
                suspended=vendor_counts.get(VendorStatus.SUSPENDED, 0),
                closed=vendor_counts.get(VendorStatus.CLOSED, 0),
            ),
            agents=AgentMetrics(
                total=sum(agent_counts.values()),
                active=agent_counts.get(AgentStatus.ACTIVE, 0),
                paused=agent_counts.get(AgentStatus.PAUSED, 0),
                pending_decisions=pending_decisions,
            ),
        )

    async def dashboard_trends(self, days: int = 30) -> DashboardTrends:
        if not 7 <= days <= 90:
            raise ValueError("days must be between 7 and 90")
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        revenue_rows = await self._repository.revenue_trend(start=start, end=end)
        dispute_rows = await self._repository.dispute_trend(start=start, end=end)
        return DashboardTrends(
            days=days,
            revenue=[
                RevenueTrendPoint(
                    day=_parse_day(raw_day),
                    currency=currency,
                    gross_volume=amount or ZERO,
                    transaction_count=int(count or 0),
                )
                for raw_day, currency, amount, count in revenue_rows
            ],
            disputes=[
                DisputeTrendPoint(
                    day=_parse_day(raw_day),
                    opened_count=int(count),
                )
                for raw_day, count in dispute_rows
            ],
        )

    async def list_disputes(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: DisputeStatus | None = None,
        search: str | None = None,
    ) -> Page[DisputeRow]:
        rows, total = await self._repository.list_disputes(
            offset=offset,
            limit=limit,
            status_filter=status_filter,
            search=search,
        )
        return Page[DisputeRow](
            items=[
                DisputeRow(
                    id=dispute.id,
                    vendor_id=dispute.vendor_id,
                    vendor_name=vendor_name,
                    transaction_id=dispute.transaction_id,
                    external_dispute_id=dispute.external_dispute_id,
                    reason=dispute.reason,
                    status=dispute.status,
                    amount=dispute.amount,
                    currency=dispute.currency,
                    response_due_at=dispute.response_due_at,
                    opened_at=dispute.opened_at,
                    created_at=dispute.created_at,
                    updated_at=dispute.updated_at,
                )
                for dispute, vendor_name in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_invoices(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: InvoiceStatus | None = None,
        search: str | None = None,
    ) -> Page[InvoiceRow]:
        rows, total = await self._repository.list_invoices(
            offset=offset,
            limit=limit,
            status_filter=status_filter,
            search=search,
        )
        return Page[InvoiceRow](
            items=[
                InvoiceRow(
                    id=invoice.id,
                    vendor_id=invoice.vendor_id,
                    vendor_name=vendor_name,
                    invoice_number=invoice.invoice_number,
                    status=invoice.status,
                    amount=invoice.amount,
                    currency=invoice.currency,
                    due_at=invoice.due_at,
                    created_at=invoice.created_at,
                    updated_at=invoice.updated_at,
                )
                for invoice, vendor_name in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_payouts(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: PayoutStatus | None = None,
        search: str | None = None,
    ) -> Page[PayoutRow]:
        rows, total = await self._repository.list_payouts(
            offset=offset,
            limit=limit,
            status_filter=status_filter,
            search=search,
        )
        return Page[PayoutRow](
            items=[
                PayoutRow(
                    id=payout.id,
                    vendor_id=payout.vendor_id,
                    vendor_name=vendor_name,
                    status=payout.status,
                    amount=payout.amount,
                    currency=payout.currency,
                    reference=payout.reference,
                    approved_at=payout.approved_at,
                    created_at=payout.created_at,
                    updated_at=payout.updated_at,
                )
                for payout, vendor_name in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_activity(
        self,
        *,
        offset: int,
        limit: int,
    ) -> Page[ActivityRow]:
        rows, total = await self._repository.list_activity(
            offset=offset,
            limit=limit,
        )
        items: list[ActivityRow] = []
        for audit, user_name, agent_name in rows:
            if audit.vendor_id is None:
                raise RuntimeError("Tenant-scoped audit record has no vendor")
            if audit.actor_user_id is not None:
                actor_type: Literal["user", "agent", "system"] = "user"
                actor_name = user_name
            elif audit.agent_id is not None:
                actor_type = "agent"
                actor_name = agent_name
            else:
                actor_type = "system"
                actor_name = None
            items.append(
                ActivityRow(
                    id=audit.id,
                    vendor_id=audit.vendor_id,
                    entity_type=audit.entity_type,
                    entity_id=audit.entity_id,
                    action=audit.action,
                    actor_type=actor_type,
                    actor_name=actor_name,
                    created_at=audit.created_at,
                )
            )
        return Page[ActivityRow](
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )


def _parse_day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("Database returned an invalid reporting date") from exc
