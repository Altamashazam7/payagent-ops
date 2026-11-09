"""Validated application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for this process."""
    return Settings()
