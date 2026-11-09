"""Readiness check response schema."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReadinessResponse(BaseModel):
    """Status returned when required infrastructure is available."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]
    service: Literal["payagent-ops"]
    version: str
