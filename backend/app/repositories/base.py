"""Generic async repository foundation."""

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import BaseModel
from app.models.mixins import SoftDeleteMixin

ModelT = TypeVar("ModelT", bound=BaseModel)


class SqlAlchemyRepository(Generic[ModelT]):
    """Provide typed persistence operations without owning transactions."""

    def __init__(
        self,
        session: AsyncSession,
        model_type: type[ModelT],
        *,
        include_deleted: bool = False,
    ) -> None:
        self._session = session
        self._model_type = model_type
        self._include_deleted = include_deleted

    def _select_entities(self) -> Select[ModelT]:
        statement = select(self._model_type)
        if not self._include_deleted:
            deleted_at = getattr(self._model_type, "deleted_at", None)
            if deleted_at is not None:
                statement = statement.where(deleted_at.is_(None))
        return statement

    async def _list_query(
        self,
        statement: Select[ModelT],
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ModelT]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        result = await self._session.execute(
            statement.order_by(
                self._model_type.created_at.desc(),
                self._model_type.id,
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, entity_id: UUID) -> ModelT | None:
        """Fetch one entity by UUID, or return None if it does not exist."""
        statement = self._select_entities().where(self._model_type.id == entity_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ModelT]:
        """Return a bounded page of entities in deterministic primary-key order."""
        return await self._list_query(
            self._select_entities(),
            offset=offset,
            limit=limit,
        )

    def add(self, entity: ModelT) -> ModelT:
        """Stage an entity in the current transaction without committing it."""
        self._session.add(entity)
        return entity

    async def delete(
        self,
        entity: ModelT,
        *,
        actor_user_id: UUID | None = None,
    ) -> None:
        """Soft-delete eligible records and physically remove transient records."""
        if isinstance(entity, SoftDeleteMixin):
            entity.mark_deleted(actor_user_id)
            return
        await self._session.delete(entity)
