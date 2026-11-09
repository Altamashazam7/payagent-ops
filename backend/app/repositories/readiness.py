"""Database readiness repository contract and SQLAlchemy implementation."""

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ReadinessRepository(Protocol):
    """Read-only database connectivity probe."""

    async def check_database(self) -> None:
        """Raise a SQLAlchemy error if the database cannot execute a query."""


class SqlAlchemyReadinessRepository:
    """Implement the readiness probe using the injected async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_database(self) -> None:
        await self._session.execute(text("SELECT 1"))
