"""Generic SQLAlchemy repository tests."""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.repositories.base import SqlAlchemyRepository
from tests.models import SampleEntity


async def test_repository_add_get_list_and_delete(
    database: Database,
) -> None:
    async with database.session_factory.begin() as session:
        assert isinstance(session, AsyncSession)
        repository = SqlAlchemyRepository(session, SampleEntity)
        created = repository.add(SampleEntity(name="invoice-1"))
        await session.flush()
        entity_id = created.id

    assert isinstance(entity_id, UUID)

    async with database.session_factory.begin() as session:
        repository = SqlAlchemyRepository(session, SampleEntity)
        entity = await repository.get_by_id(entity_id)
        assert entity is not None
        assert entity.name == "invoice-1"
        assert await repository.list(limit=1) == [entity]
        await repository.delete(entity)
        await session.flush()
        assert await repository.get_by_id(entity_id) is None


async def test_repository_does_not_commit_its_callers_transaction(
    database: Database,
) -> None:
    async with database.session_factory() as session:
        repository = SqlAlchemyRepository(session, SampleEntity)
        entity = repository.add(SampleEntity(name="uncommitted"))
        await session.flush()
        entity_id = entity.id

    async with database.session_factory() as session:
        repository = SqlAlchemyRepository(session, SampleEntity)
        assert await repository.get_by_id(entity_id) is None


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 10), (0, 0), (0, 101)],
)
async def test_repository_rejects_invalid_page_bounds(
    database: Database,
    offset: int,
    limit: int,
) -> None:
    async with database.session_factory() as session:
        repository = SqlAlchemyRepository(session, SampleEntity)
        with pytest.raises(ValueError):
            await repository.list(offset=offset, limit=limit)
