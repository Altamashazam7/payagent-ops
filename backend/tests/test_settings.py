"""Settings validation and secret handling tests."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import Settings


def test_settings_load_environment_and_mask_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql+psycopg://user:private-password@db/payagent"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    settings = Settings()

    assert settings.database_url == SecretStr(database_url)
    assert settings.log_level == "WARNING"
    assert "private-password" not in repr(settings)


def test_settings_reject_invalid_api_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("API_V1_PREFIX", "api/v1")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_unknown_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ENVIRONMENT", "production-like")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_sync_database_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/payagent_ops")

    with pytest.raises(ValidationError):
        Settings()
