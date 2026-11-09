"""Typed application services for commerce-domain persistence."""

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import BaseModel as ORMBaseModel
from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.dispute import Dispute
from app.models.enums import AuditEntityType, TransactionStatus
from app.models.invoice import Invoice
from app.models.mixins import SoftDeleteMixin
from app.models.payout import Payout
from app.models.transaction import Transaction
from app.models.user import User
from app.models.vendor import Vendor
from app.repositories.base import SqlAlchemyRepository
from app.repositories.commerce import (
    AgentRepository,
    AuditLogRepository,
    DecisionRepository,
    DisputeRepository,
    InvoiceRepository,
    PayoutRepository,
    TransactionRepository,
    UserRepository,
    VendorRepository,
)
from app.schemas.commerce import (
    AgentCreate,
    AgentRead,
    AuditLogCreate,
    AuditLogRead,
    DecisionCreate,
    DecisionRead,
    DisputeCreate,
    DisputeRead,
    DomainInputSchema,
    DomainReadSchema,
    InvoiceCreate,
    InvoiceRead,
    PayoutCreate,
    PayoutRead,
    TransactionCreate,
    TransactionRead,
    UserCreate,
    UserRead,
    VendorCreate,
    VendorRead,
)

EntityT = TypeVar("EntityT", bound=ORMBaseModel)
InputT = TypeVar("InputT", bound=DomainInputSchema)
OutputT = TypeVar("OutputT", bound=DomainReadSchema)


class EntityService(Generic[EntityT, InputT, OutputT]):
    """Create and query entities while keeping transaction control in services."""

    def __init__(
        self,
        session: AsyncSession,
        repository: SqlAlchemyRepository[EntityT],
        model_type: type[EntityT],
        read_schema: type[OutputT],
    ) -> None:
        self._session = session
        self._repository = repository
        self._model_type = model_type
        self._read_schema = read_schema

    async def create(self, data: InputT) -> OutputT:
        """Create and commit a validated domain record."""
        values = data.model_dump(mode="python", exclude_unset=True)
        entity = self._model_type(**values)
        async with self._session.begin():
            self._repository.add(entity)
            await self._session.flush()
            await self._session.refresh(entity)
            result = self._read_schema.model_validate(entity)
        return result

    async def get_by_id(self, entity_id: UUID) -> OutputT | None:
        """Return a visible record by identifier."""
        entity = await self._repository.get_by_id(entity_id)
        if entity is None:
            return None
        return self._read_schema.model_validate(entity)

    async def list(self, *, offset: int = 0, limit: int = 50) -> list[OutputT]:
        """Return a bounded page of visible records."""
        entities = await self._repository.list(offset=offset, limit=limit)
        return [self._read_schema.model_validate(entity) for entity in entities]

    async def soft_delete(
        self,
        entity_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> bool:
        """Soft-delete only entities explicitly modeled for logical deletion."""
        async with self._session.begin():
            entity = await self._repository.get_by_id(entity_id)
            if entity is None:
                return False
            if not isinstance(entity, SoftDeleteMixin):
                raise TypeError("This commerce record must be retained, not deleted")
            await self._repository.delete(entity, actor_user_id=actor_user_id)
        return True


class UserService(EntityService[User, UserCreate, UserRead]):
    def __init__(self, session: AsyncSession) -> None:
        repository = UserRepository(session)
        self._user_repository = repository
        super().__init__(session, repository, User, UserRead)

    async def get_by_email(self, email: str) -> UserRead | None:
        user = await self._user_repository.get_by_email(email)
        if user is None:
            return None
        return UserRead.model_validate(user)


class VendorService(EntityService[Vendor, VendorCreate, VendorRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VendorRepository(session), Vendor, VendorRead)

    async def list_for_owner(
        self,
        owner_user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[VendorRead]:
        repository = VendorRepository(self._session)
        entities = await repository.list_for_owner(
            owner_user_id,
            offset=offset,
            limit=limit,
        )
        return [VendorRead.model_validate(entity) for entity in entities]


class TransactionService(
    EntityService[Transaction, TransactionCreate, TransactionRead]
):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(
            session,
            TransactionRepository(session),
            Transaction,
            TransactionRead,
        )

    async def list_for_vendor(
        self,
        vendor_id: UUID,
        *,
        status: TransactionStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[TransactionRead]:
        repository = TransactionRepository(self._session)
        entities = await repository.list_for_vendor(
            vendor_id,
            status=status,
            offset=offset,
            limit=limit,
        )
        return [TransactionRead.model_validate(entity) for entity in entities]


class DisputeService(EntityService[Dispute, DisputeCreate, DisputeRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DisputeRepository(session), Dispute, DisputeRead)

    async def list_actionable(
        self,
        vendor_id: UUID,
        *,
        due_before: datetime,
        offset: int = 0,
        limit: int = 50,
    ) -> list[DisputeRead]:
        repository = DisputeRepository(self._session)
        entities = await repository.list_actionable(
            vendor_id,
            due_before=due_before,
            offset=offset,
            limit=limit,
        )
        return [DisputeRead.model_validate(entity) for entity in entities]


class InvoiceService(EntityService[Invoice, InvoiceCreate, InvoiceRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, InvoiceRepository(session), Invoice, InvoiceRead)

    async def list_outstanding(
        self,
        vendor_id: UUID,
        *,
        due_before: datetime,
        offset: int = 0,
        limit: int = 50,
    ) -> list[InvoiceRead]:
        repository = InvoiceRepository(self._session)
        entities = await repository.list_outstanding(
            vendor_id,
            due_before=due_before,
            offset=offset,
            limit=limit,
        )
        return [InvoiceRead.model_validate(entity) for entity in entities]


class PayoutService(EntityService[Payout, PayoutCreate, PayoutRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PayoutRepository(session), Payout, PayoutRead)

    async def list_pending_approval(
        self,
        vendor_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[PayoutRead]:
        repository = PayoutRepository(self._session)
        entities = await repository.list_pending_approval(
            vendor_id,
            offset=offset,
            limit=limit,
        )
        return [PayoutRead.model_validate(entity) for entity in entities]


class AgentService(EntityService[Agent, AgentCreate, AgentRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(
            session,
            AgentRepository(session),
            Agent,
            AgentRead,
        )

    async def list_active_for_vendor(
        self,
        vendor_id: UUID | None,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[AgentRead]:
        repository = AgentRepository(self._session)
        entities = await repository.list_active_for_vendor(
            vendor_id,
            offset=offset,
            limit=limit,
        )
        return [AgentRead.model_validate(entity) for entity in entities]


class DecisionService(EntityService[Decision, DecisionCreate, DecisionRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(
            session,
            DecisionRepository(session),
            Decision,
            DecisionRead,
        )

    async def list_pending_for_vendor(
        self,
        vendor_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[DecisionRead]:
        repository = DecisionRepository(self._session)
        entities = await repository.list_pending_for_vendor(
            vendor_id,
            offset=offset,
            limit=limit,
        )
        return [DecisionRead.model_validate(entity) for entity in entities]


class AuditLogService(EntityService[AuditLog, AuditLogCreate, AuditLogRead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(
            session,
            AuditLogRepository(session),
            AuditLog,
            AuditLogRead,
        )

    async def list_for_entity(
        self,
        entity_type: AuditEntityType,
        entity_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[AuditLogRead]:
        repository = AuditLogRepository(self._session)
        entities = await repository.list_for_entity(
            entity_type,
            entity_id,
            offset=offset,
            limit=limit,
        )
        return [AuditLogRead.model_validate(entity) for entity in entities]
