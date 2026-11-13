"""Settings validation and secret handling tests."""

from pathlib import Path

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


def test_repository_environment_example_loads_with_optional_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_path = Path(__file__).resolve().parents[2] / ".env.example"
    for line in example_path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", maxsplit=1)
            monkeypatch.setenv(key, value)
    settings = Settings()

    assert settings.oidc_issuer is None
    assert settings.sentry_dsn is None
    assert settings.otel_exporter_otlp_traces_endpoint is None
    assert settings.redis_url == SecretStr("redis://localhost:6379/0")


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


def test_settings_reject_demo_auth_outside_development() -> None:
    with pytest.raises(ValidationError, match="only be used in development"):
        Settings(environment="test", demo_auth_enabled=True)


def test_settings_reject_sync_database_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://localhost/payagent_ops")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_normalize_render_postgresql_connection_string() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql://user:pass@db/payagent_ops"),
        environment="test",
    )

    assert settings.database_url == SecretStr(
        "postgresql+psycopg://user:pass@db/payagent_ops"
    )


def test_settings_require_metrics_token_when_metrics_are_enabled() -> None:
    with pytest.raises(ValidationError, match="METRICS_BEARER_TOKEN"):
        Settings(
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            environment="test",
            metrics_enabled=True,
        )


def test_paypal_environment_selects_sandbox_and_live_origins() -> None:
    sandbox = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        environment="test",
        paypal_environment="sandbox",
    )
    live = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        environment="test",
        paypal_environment="live",
    )

    assert sandbox.paypal_api_base_url == "https://api-m.sandbox.paypal.com"
    assert live.paypal_api_base_url == "https://api-m.paypal.com"


def test_settings_require_paypal_credentials_as_a_pair() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            environment="test",
            paypal_client_id=SecretStr("client-id"),
        )


def test_settings_mask_paypal_client_credentials() -> None:
    settings = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        environment="test",
        paypal_client_id=SecretStr("paypal-client-id"),
        paypal_client_secret=SecretStr("paypal-private-secret"),
    )

    assert "paypal-client-id" not in repr(settings)
    assert "paypal-private-secret" not in repr(settings)


def test_settings_mask_optional_openai_api_key() -> None:
    settings = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        environment="test",
        openai_api_key=SecretStr("openai-private-key"),
    )

    assert settings.dispute_narrative_model == "gpt-4.1-mini"
    assert "openai-private-key" not in repr(settings)


def test_settings_reject_inverted_paypal_retry_waits() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        Settings(
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            environment="test",
            paypal_retry_min_wait_seconds=2,
            paypal_retry_max_wait_seconds=1,
        )
