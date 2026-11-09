"""Generic async repository foundation."""

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class SqlAlchemyRepository(Generic[ModelT]):
    """Provide typed persistence operations without owning transactions."""

    def __init__(self, session: AsyncSession, model_type: type[ModelT]) -> None:
        self._session = session
        self._model_type = model_type

    async def get_by_id(self, entity_id: UUID) -> ModelT | None:
        """Fetch one entity by UUID, or return None if it does not exist."""
        statement = select(self._model_type).where(self._model_type.id == entity_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ModelT]:
        """Return a bounded page of entities in deterministic primary-key order."""
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        statement = (
            select(self._model_type)
            .order_by(self._model_type.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    def add(self, entity: ModelT) -> ModelT:
        """Stage an entity in the current transaction without committing it."""
        self._session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Stage an entity deletion in the current transaction."""
        await self._session.delete(entity)
