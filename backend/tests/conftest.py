"""Shared backend test fixtures."""

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.settings import Settings
from app.db.session import Database
from app.main import create_app
from tests.models import SampleEntity


@pytest.fixture
def application() -> Iterator[FastAPI]:
    """Create an isolated app backed by an in-memory SQLite database."""
    settings = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        environment="test",
    )
    yield create_app(settings)


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    """Start and stop the app lifespan around an HTTP test client."""
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """Provide an isolated async test database with mapped tables created."""
    database = Database(SecretStr("sqlite+aiosqlite:///:memory:"))
    async with database.engine.begin() as connection:
        await connection.run_sync(SampleEntity.metadata.create_all)
    try:
        yield database
    finally:
        await database.dispose()
