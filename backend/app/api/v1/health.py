"""Health check routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_readiness_service, get_settings_from_request
from app.core.constants import SERVICE_NAME
from app.core.settings import Settings
from app.schemas.health import HealthResponse
from app.schemas.readiness import ReadinessResponse
from app.services.health import get_health
from app.services.readiness import ReadinessService

router = APIRouter(tags=["health"])
probe_router = APIRouter(tags=["health"], include_in_schema=False)


@router.get("/health", response_model=HealthResponse)
@probe_router.get("/health", response_model=HealthResponse)
def read_health(
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> HealthResponse:
    """Return whether the API process is running."""
    return get_health(version=settings.app_version)


@router.get("/ready", response_model=ReadinessResponse)
@probe_router.get("/ready", response_model=ReadinessResponse)
@router.get("/readiness", response_model=ReadinessResponse)
@probe_router.get("/readiness", response_model=ReadinessResponse)
async def read_readiness(
    readiness_service: Annotated[ReadinessService, Depends(get_readiness_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> ReadinessResponse:
    """Return readiness only when required database connectivity is available."""
    if not await readiness_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Required service is unavailable",
        )
    return ReadinessResponse(
        status="ready",
        service=SERVICE_NAME,
        version=settings.app_version,
    )
