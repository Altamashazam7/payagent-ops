"""Async database session lifecycle tests."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database


async def test_database_session_factory_yields_working_async_session(
    database: Database,
) -> None:
    async with database.session_factory() as session:
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))

    assert result.scalar_one() == 1
