"""Health check response schema."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness status for the API process."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: Literal["payagent-ops"]
    version: str
