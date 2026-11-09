"""Tenant-scoped SQL queries for executive and commerce workspaces."""

from datetime import datetime
from decimal import Decimal
from typing import TypeAlias
from uuid import UUID

from sqlalchemy import ColumnElement, Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.dispute import Dispute
from app.models.enums import (
    AgentStatus,
    DecisionStatus,
    DisputeStatus,
    InvoiceStatus,
    PayoutStatus,
    TransactionStatus,
    VendorStatus,
)
from app.models.invoice import Invoice
from app.models.payout import Payout
from app.models.transaction import Transaction
from app.models.user import User
from app.models.vendor import Vendor

AmountBucket: TypeAlias = tuple[str, Decimal | None, int | None]


class AnalyticsRepository:
    """Provide aggregate and paged reads restricted to a tenant owner claim."""

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def _vendor_scope(self) -> Select[UUID]:
        return select(Vendor.id).where(
            Vendor.owner_user_id == self._tenant_id,
            Vendor.deleted_at.is_(None),
        )

    @staticmethod
    def _search_pattern(search: str) -> str:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    async def revenue_periods(
        self,
        *,
        previous_start: datetime,
        current_start: datetime,
        end: datetime,
    ) -> list[tuple[str, Decimal | None, Decimal | None, int | None]]:
        current = Transaction.occurred_at >= current_start
        statement = (
            select(
                Transaction.currency,
                func.sum(case((current, Transaction.amount), else_=0)).label(
                    "current_volume"
                ),
                func.sum(
                    case(
                        (
                            Transaction.occurred_at < current_start,
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ).label("previous_volume"),
                func.sum(case((current, 1), else_=0)).label("current_count"),
            )
            .where(
                Transaction.vendor_id.in_(self._vendor_scope()),
                Transaction.status.in_(
                    (TransactionStatus.CAPTURED, TransactionStatus.PARTIALLY_REFUNDED)
                ),
                Transaction.occurred_at >= previous_start,
                Transaction.occurred_at < end,
            )
            .group_by(Transaction.currency)
            .order_by(Transaction.currency)
        )
        result = await self._session.execute(statement)
        return [
            (row.currency, row.current_volume, row.previous_volume, row.current_count)
            for row in result.all()
        ]

    async def dispute_status_counts(self) -> dict[DisputeStatus, int]:
        statement = (
            select(Dispute.status, func.count(Dispute.id))
            .where(Dispute.vendor_id.in_(self._vendor_scope()))
            .group_by(Dispute.status)
        )
        result = await self._session.execute(statement)
        return {status: count for status, count in result.all()}

    async def open_dispute_exposure(self) -> list[AmountBucket]:
        statement = (
            select(
                Dispute.currency,
                func.sum(Dispute.amount),
                func.count(Dispute.id),
            )
            .where(
                Dispute.vendor_id.in_(self._vendor_scope()),
                Dispute.status.in_(
                    (DisputeStatus.NEEDS_RESPONSE, DisputeStatus.UNDER_REVIEW)
                ),
            )
            .group_by(Dispute.currency)
            .order_by(Dispute.currency)
        )
        result = await self._session.execute(statement)
        return list(result.all())

    async def dispute_due_counts(
        self,
        *,
        now: datetime,
        due_soon_at: datetime,
    ) -> tuple[int, int]:
        actionable = (DisputeStatus.NEEDS_RESPONSE, DisputeStatus.UNDER_REVIEW)
        statement = select(
            func.sum(
                case(
                    (
                        (Dispute.response_due_at < now)
                        & Dispute.response_due_at.is_not(None),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        (Dispute.response_due_at >= now)
                        & (Dispute.response_due_at <= due_soon_at),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).where(
            Dispute.vendor_id.in_(self._vendor_scope()),
            Dispute.status.in_(actionable),
        )
        result = await self._session.execute(statement)
        overdue, due_soon = result.one()
        return int(overdue or 0), int(due_soon or 0)

    async def dispute_opened_periods(
        self,
        *,
        previous_start: datetime,
        current_start: datetime,
        end: datetime,
    ) -> tuple[int, int]:
        current = Dispute.opened_at >= current_start
        statement = select(
            func.sum(case((current, 1), else_=0)),
            func.sum(
                case(
                    (Dispute.opened_at < current_start, 1),
                    else_=0,
                )
            ),
        ).where(
            Dispute.vendor_id.in_(self._vendor_scope()),
            Dispute.opened_at >= previous_start,
            Dispute.opened_at < end,
        )
        result = await self._session.execute(statement)
        current_count, previous_count = result.one()
        return int(current_count or 0), int(previous_count or 0)

    async def invoice_status_buckets(
        self,
    ) -> list[tuple[InvoiceStatus, str, Decimal | None, int | None]]:
        statement = (
            select(
                Invoice.status,
                Invoice.currency,
                func.sum(Invoice.amount),
                func.count(Invoice.id),
            )
            .where(Invoice.vendor_id.in_(self._vendor_scope()))
            .group_by(Invoice.status, Invoice.currency)
            .order_by(Invoice.status, Invoice.currency)
        )
        result = await self._session.execute(statement)
        return list(result.all())

    async def payout_status_buckets(
        self,
    ) -> list[tuple[PayoutStatus, str, Decimal | None, int | None]]:
        statement = (
            select(
                Payout.status,
                Payout.currency,
                func.sum(Payout.amount),
                func.count(Payout.id),
            )
            .where(Payout.vendor_id.in_(self._vendor_scope()))
            .group_by(Payout.status, Payout.currency)
            .order_by(Payout.status, Payout.currency)
        )
        result = await self._session.execute(statement)
        return list(result.all())

    async def vendor_status_counts(self) -> dict[VendorStatus, int]:
        statement = (
            select(Vendor.status, func.count(Vendor.id))
            .where(
                Vendor.owner_user_id == self._tenant_id,
                Vendor.deleted_at.is_(None),
            )
            .group_by(Vendor.status)
        )
        result = await self._session.execute(statement)
        return {status: count for status, count in result.all()}

    async def agent_status_counts(self) -> dict[AgentStatus, int]:
        statement = (
            select(Agent.status, func.count(Agent.id))
            .where(
                Agent.vendor_id.in_(self._vendor_scope()),
                Agent.deleted_at.is_(None),
            )
            .group_by(Agent.status)
        )
        result = await self._session.execute(statement)
        return {status: count for status, count in result.all()}

    async def decision_counts(self) -> dict[tuple[DecisionStatus, str], int]:
        statement = (
            select(Decision.status, Decision.action_type, func.count(Decision.id))
            .where(Decision.vendor_id.in_(self._vendor_scope()))
            .group_by(Decision.status, Decision.action_type)
        )
        result = await self._session.execute(statement)
        return {
            (status, action_type): count for status, action_type, count in result.all()
        }

    async def revenue_trend(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> list[tuple[object, str, Decimal | None, int | None]]:
        day = func.date(Transaction.occurred_at)
        statement = (
            select(
                day.label("day"),
                Transaction.currency,
                func.sum(Transaction.amount),
                func.count(Transaction.id),
            )
            .where(
                Transaction.vendor_id.in_(self._vendor_scope()),
                Transaction.status.in_(
                    (TransactionStatus.CAPTURED, TransactionStatus.PARTIALLY_REFUNDED)
                ),
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
            )
            .group_by(day, Transaction.currency)
            .order_by(day, Transaction.currency)
        )
        result = await self._session.execute(statement)
        return list(result.all())

    async def dispute_trend(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> list[tuple[object, int]]:
        day = func.date(Dispute.opened_at)
        statement = (
            select(day.label("day"), func.count(Dispute.id))
            .where(
                Dispute.vendor_id.in_(self._vendor_scope()),
                Dispute.opened_at >= start,
                Dispute.opened_at < end,
            )
            .group_by(day)
            .order_by(day)
        )
        result = await self._session.execute(statement)
        return list(result.all())

    async def list_disputes(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: DisputeStatus | None,
        search: str | None,
    ) -> tuple[list[tuple[Dispute, str]], int]:
        filters: list[ColumnElement[bool]] = [
            Dispute.vendor_id.in_(self._vendor_scope())
        ]
        if status_filter is not None:
            filters.append(Dispute.status == status_filter)
        if search:
            term = self._search_pattern(search)
            filters.append(
                or_(
                    Dispute.external_dispute_id.ilike(term, escape="\\"),
                    Dispute.reason.ilike(term, escape="\\"),
                )
            )
        statement = (
            select(Dispute, Vendor.name)
            .join(Vendor, Vendor.id == Dispute.vendor_id)
            .where(*filters)
            .order_by(Dispute.created_at.desc(), Dispute.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        count_statement = (
            select(func.count(Dispute.id))
            .join(Vendor, Vendor.id == Dispute.vendor_id)
            .where(*filters)
        )
        total = await self._session.scalar(count_statement)
        return [(dispute, vendor_name) for dispute, vendor_name in result.all()], int(
            total or 0
        )

    async def list_invoices(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: InvoiceStatus | None,
        search: str | None,
    ) -> tuple[list[tuple[Invoice, str]], int]:
        filters: list[ColumnElement[bool]] = [
            Invoice.vendor_id.in_(self._vendor_scope())
        ]
        if status_filter is not None:
            filters.append(Invoice.status == status_filter)
        if search:
            term = self._search_pattern(search)
            filters.append(Invoice.invoice_number.ilike(term, escape="\\"))
        statement = (
            select(Invoice, Vendor.name)
            .join(Vendor, Vendor.id == Invoice.vendor_id)
            .where(*filters)
            .order_by(Invoice.created_at.desc(), Invoice.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        count_statement = (
            select(func.count(Invoice.id))
            .join(Vendor, Vendor.id == Invoice.vendor_id)
            .where(*filters)
        )
        total = await self._session.scalar(count_statement)
        return [(invoice, vendor_name) for invoice, vendor_name in result.all()], int(
            total or 0
        )

    async def list_payouts(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: PayoutStatus | None,
        search: str | None,
    ) -> tuple[list[tuple[Payout, str]], int]:
        filters: list[ColumnElement[bool]] = [
            Payout.vendor_id.in_(self._vendor_scope())
        ]
        if status_filter is not None:
            filters.append(Payout.status == status_filter)
        if search:
            term = self._search_pattern(search)
            filters.append(Payout.reference.ilike(term, escape="\\"))
        statement = (
            select(Payout, Vendor.name)
            .join(Vendor, Vendor.id == Payout.vendor_id)
            .where(*filters)
            .order_by(Payout.created_at.desc(), Payout.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        count_statement = (
            select(func.count(Payout.id))
            .join(Vendor, Vendor.id == Payout.vendor_id)
            .where(*filters)
        )
        total = await self._session.scalar(count_statement)
        return [(payout, vendor_name) for payout, vendor_name in result.all()], int(
            total or 0
        )

    async def list_activity(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[AuditLog, str | None, str | None]], int]:
        filters: list[ColumnElement[bool]] = [
            AuditLog.vendor_id.in_(self._vendor_scope())
        ]
        statement = (
            select(AuditLog, User.display_name, Agent.name)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .outerjoin(Agent, Agent.id == AuditLog.agent_id)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        total = await self._session.scalar(
            select(func.count(AuditLog.id)).where(*filters)
        )
        return list(result.all()), int(total or 0)
