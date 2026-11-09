"""Typed repositories and operational queries for commerce entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from app.models.invoice import Invoice
from app.models.payout import Payout
from app.models.transaction import Transaction
from app.models.user import User
from app.models.vendor import Vendor
from app.repositories.base import SqlAlchemyRepository


class UserRepository(SqlAlchemyRepository[User]):
    def __init__(self, session: AsyncSession, *, include_deleted: bool = False) -> None:
        super().__init__(session, User, include_deleted=include_deleted)

    async def get_by_email(self, email: str) -> User | None:
        statement = self._select_entities().where(User.email == email.casefold())
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()


class VendorRepository(SqlAlchemyRepository[Vendor]):
    def __init__(self, session: AsyncSession, *, include_deleted: bool = False) -> None:
        super().__init__(session, Vendor, include_deleted=include_deleted)

    async def list_for_owner(
        self,
        owner_user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Vendor]:
        statement = self._select_entities().where(Vendor.owner_user_id == owner_user_id)
        return await self._list_query(statement, offset=offset, limit=limit)


class TransactionRepository(SqlAlchemyRepository[Transaction]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Transaction)

    async def list_for_vendor(
        self,
        vendor_id: UUID,
        *,
        status: TransactionStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Transaction]:
        statement = self._select_entities().where(Transaction.vendor_id == vendor_id)
        if status is not None:
            statement = statement.where(Transaction.status == status)
        return await self._list_query(statement, offset=offset, limit=limit)


class DisputeRepository(SqlAlchemyRepository[Dispute]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Dispute)

    async def list_actionable(
        self,
        vendor_id: UUID,
        *,
        due_before: datetime,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Dispute]:
        statement = self._select_entities().where(
            Dispute.vendor_id == vendor_id,
            Dispute.status.in_(
                (DisputeStatus.NEEDS_RESPONSE, DisputeStatus.UNDER_REVIEW)
            ),
            Dispute.response_due_at.is_not(None),
            Dispute.response_due_at <= due_before,
        )
        return await self._list_query(statement, offset=offset, limit=limit)


class InvoiceRepository(SqlAlchemyRepository[Invoice]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Invoice)

    async def list_outstanding(
        self,
        vendor_id: UUID,
        *,
        due_before: datetime,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Invoice]:
        statement = self._select_entities().where(
            Invoice.vendor_id == vendor_id,
            Invoice.status.in_((InvoiceStatus.SENT, InvoiceStatus.OVERDUE)),
            Invoice.due_at.is_not(None),
            Invoice.due_at <= due_before,
        )
        return await self._list_query(statement, offset=offset, limit=limit)


class PayoutRepository(SqlAlchemyRepository[Payout]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Payout)

    async def list_pending_approval(
        self,
        vendor_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Payout]:
        statement = self._select_entities().where(
            Payout.vendor_id == vendor_id,
            Payout.status == PayoutStatus.PENDING_APPROVAL,
        )
        return await self._list_query(statement, offset=offset, limit=limit)


class AgentRepository(SqlAlchemyRepository[Agent]):
    def __init__(self, session: AsyncSession, *, include_deleted: bool = False) -> None:
        super().__init__(session, Agent, include_deleted=include_deleted)

    async def list_active_for_vendor(
        self,
        vendor_id: UUID | None,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Agent]:
        statement = self._select_entities().where(
            Agent.status == AgentStatus.ACTIVE,
            Agent.vendor_id == vendor_id,
        )
        return await self._list_query(statement, offset=offset, limit=limit)


class DecisionRepository(SqlAlchemyRepository[Decision]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Decision)

    async def list_pending_for_vendor(
        self,
        vendor_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Decision]:
        statement = self._select_entities().where(
            Decision.vendor_id == vendor_id,
            Decision.status == DecisionStatus.PENDING,
        )
        return await self._list_query(statement, offset=offset, limit=limit)


class AuditLogRepository(SqlAlchemyRepository[AuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)

    async def list_for_entity(
        self,
        entity_type: AuditEntityType,
        entity_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[AuditLog]:
        statement: Select[AuditLog] = self._select_entities().where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        )
        return await self._list_query(statement, offset=offset, limit=limit)

    async def delete(
        self,
        entity: AuditLog,
        *,
        actor_user_id: UUID | None = None,
    ) -> None:
        raise ValueError("Audit log entries are append-only")
