"""Validated realtime event and notification contracts."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.types import JSONValue

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")


class EventEnvelope(BaseModel):
    """Versioned event envelope published to a single tenant channel."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=2, max_length=80)
    tenant_id: UUID
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, JSONValue] = Field(max_length=32)
    version: Annotated[int, Field(ge=1)] = 1

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if _EVENT_TYPE_PATTERN.fullmatch(value) is None:
            raise ValueError("event_type must be a lowercase dotted identifier")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("payload")
    @classmethod
    def limit_payload_size(cls, value: dict[str, JSONValue]) -> dict[str, JSONValue]:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 16_384:
            raise ValueError("payload must not exceed 16 KiB")
        return value


class NotificationPayload(BaseModel):
    """Small, user-facing notification data with safe relative navigation."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    severity: Annotated[
        str,
        Field(pattern=r"^(info|success|warning|error)$"),
    ] = "info"
    href: str | None = Field(default=None, max_length=512)

    @field_validator("href")
    @classmethod
    def validate_href(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("href must be a safe same-origin path")
        return value
