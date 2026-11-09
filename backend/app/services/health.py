"""Health check application service."""

from app.core.constants import API_VERSION, SERVICE_NAME
from app.schemas.health import HealthResponse


def get_health(version: str = API_VERSION) -> HealthResponse:
    """Build the process liveness response without probing external systems."""
    return HealthResponse(status="ok", service=SERVICE_NAME, version=version)
