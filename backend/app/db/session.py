"""Async SQLAlchemy engine and session lifecycle."""

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Own the async engine and session factory for one application instance."""

    def __init__(self, database_url: SecretStr, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url.get_secret_value(),
            echo=echo,
            pool_pre_ping=True,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def dispose(self) -> None:
        """Close pooled database connections during application shutdown."""
        await self.engine.dispose()
