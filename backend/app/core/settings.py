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
    api_v1_prefix: str = "/api/v1"
    paypal_environment: Literal["sandbox", "live"] = "sandbox"
    paypal_client_id: SecretStr | None = None
    paypal_client_secret: SecretStr | None = None
    paypal_webhook_id: str | None = Field(default=None, min_length=1, max_length=128)
    paypal_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    paypal_retry_attempts: int = Field(default=3, ge=1, le=8)
    paypal_retry_min_wait_seconds: float = Field(default=0.25, ge=0, le=60)
    paypal_retry_max_wait_seconds: float = Field(default=4.0, gt=0, le=120)
    paypal_circuit_breaker_failure_threshold: int = Field(default=5, ge=1, le=100)
    paypal_circuit_breaker_reset_seconds: float = Field(default=30.0, gt=0, le=600)

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: SecretStr) -> SecretStr:
        supported_schemes = ("postgresql+psycopg://", "sqlite+aiosqlite://")
        if not value.get_secret_value().startswith(supported_schemes):
            raise ValueError(
                "DATABASE_URL must use postgresql+psycopg or sqlite+aiosqlite"
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
