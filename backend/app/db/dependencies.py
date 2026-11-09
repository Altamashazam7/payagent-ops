"""Request-scoped database dependencies for application and API layers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database


def get_database(request: Request) -> Database:
    """Resolve the database owned by the active application."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise TypeError("The application database is not configured")
    return database


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session; transaction ownership stays with services."""
    async with database.session_factory() as session:
        yield session
