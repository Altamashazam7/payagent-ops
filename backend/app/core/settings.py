"""Validated application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import API_VERSION


class Settings(BaseSettings):
    """Application configuration; database URLs are masked in representations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="PayAgent Ops API", min_length=1)
    app_version: str = Field(default=API_VERSION, min_length=1)
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://localhost:5432/payagent_ops"
    )
    database_echo: bool = False
    redis_url: SecretStr | None = None
    api_v1_prefix: str = "/api/v1"
    metrics_enabled: bool = False
    metrics_bearer_token: SecretStr | None = None
    otel_exporter_otlp_traces_endpoint: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
    )
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0, le=1)
    oidc_issuer: str | None = Field(default=None, min_length=1, max_length=512)
    oidc_audience: str | None = Field(default=None, min_length=1, max_length=256)
    oidc_jwks_url: str | None = Field(default=None, min_length=1, max_length=2048)
    oidc_jwks_cache_seconds: int = Field(default=300, ge=30, le=3600)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=120)
    paypal_environment: Literal["sandbox", "live"] = "sandbox"
    paypal_client_id: SecretStr | None = None
    paypal_client_secret: SecretStr | None = None
    paypal_webhook_id: str | None = Field(default=None, min_length=1, max_length=128)
    openai_api_key: SecretStr | None = None
    dispute_narrative_model: str = Field(
        default="gpt-4.1-mini",
        min_length=1,
        max_length=120,
    )
    invoice_compliance_model: str = Field(
        default="gpt-4.1-mini",
        min_length=1,
        max_length=120,
    )
    payout_narrative_model: str = Field(
        default="gpt-4.1-mini",
        min_length=1,
        max_length=120,
    )
    executive_copilot_model: str = Field(
        default="gpt-4.1-mini",
        min_length=1,
        max_length=120,
    )
    paypal_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    paypal_retry_attempts: int = Field(default=3, ge=1, le=8)
    paypal_retry_min_wait_seconds: float = Field(default=0.25, ge=0, le=60)
    paypal_retry_max_wait_seconds: float = Field(default=4.0, gt=0, le=120)
    paypal_circuit_breaker_failure_threshold: int = Field(default=5, ge=1, le=100)
    paypal_circuit_breaker_reset_seconds: float = Field(default=30.0, gt=0, le=600)

    @field_validator(
        "oidc_issuer",
        "oidc_audience",
        "oidc_jwks_url",
        "paypal_webhook_id",
        "otel_exporter_otlp_traces_endpoint",
        mode="before",
    )
    @classmethod
    def normalize_empty_optional_strings(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "metrics_bearer_token",
        "sentry_dsn",
        "paypal_client_id",
        "paypal_client_secret",
        "openai_api_key",
        mode="before",
    )
    @classmethod
    def normalize_empty_optional_secrets(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if url.startswith(("postgres://", "postgresql://")):
            return SecretStr("postgresql+psycopg://" + url.split("://", 1)[1])
        supported_schemes = ("postgresql+psycopg://", "sqlite+aiosqlite://")
        if not url.startswith(supported_schemes):
            raise ValueError("DATABASE_URL must use PostgreSQL or sqlite+aiosqlite")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(
            ("redis://", "rediss://")
        ):
            raise ValueError("REDIS_URL must use redis or rediss")
        return value

    @field_validator("otel_exporter_otlp_traces_endpoint")
    @classmethod
    def validate_otel_endpoint(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT must use HTTP or HTTPS"
            )
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_v1_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("api_v1_prefix must start with '/' and not end with '/'")
        return value

    @model_validator(mode="after")
    def validate_paypal_configuration(self) -> Settings:
        oidc_values = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if any(value is not None for value in oidc_values) and not all(
            value is not None for value in oidc_values
        ):
            raise ValueError(
                "OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL "
                "must be configured together"
            )
        if self.oidc_issuer is not None and not self.oidc_issuer.startswith("https://"):
            raise ValueError("OIDC_ISSUER must use HTTPS")
        if self.oidc_jwks_url is not None and not self.oidc_jwks_url.startswith(
            "https://"
        ):
            raise ValueError("OIDC_JWKS_URL must use HTTPS")
        client_id = (
            self.paypal_client_id.get_secret_value()
            if self.paypal_client_id is not None
            else ""
        )
        client_secret = (
            self.paypal_client_secret.get_secret_value()
            if self.paypal_client_secret is not None
            else ""
        )
        if bool(client_id) != bool(client_secret):
            raise ValueError(
                "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be configured together"
            )
        if self.paypal_retry_min_wait_seconds > self.paypal_retry_max_wait_seconds:
            raise ValueError(
                "paypal_retry_min_wait_seconds cannot exceed "
                "paypal_retry_max_wait_seconds"
            )
        if self.metrics_enabled and (
            self.metrics_bearer_token is None
            or not self.metrics_bearer_token.get_secret_value()
        ):
            raise ValueError(
                "METRICS_BEARER_TOKEN is required when METRICS_ENABLED is true"
            )
        return self

    @property
    def paypal_api_base_url(self) -> str:
        """Return the official sandbox or live API origin."""
        if self.paypal_environment == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for this process."""
    return Settings()
