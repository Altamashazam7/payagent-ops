"""Authenticated Prometheus scrape endpoint."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.dependencies import get_settings_from_request
from app.core.settings import Settings
from app.observability.metrics import RequestMetrics

router = APIRouter(tags=["observability"], include_in_schema=False)


@router.get("/metrics", response_class=Response)
def read_metrics(
    request: Request,
    app_settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> Response:
    """Expose low-cardinality metrics only when explicitly enabled."""
    if not app_settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    authorization = request.headers.get("authorization", "")
    expected = app_settings.metrics_bearer_token
    if expected is None or not secrets.compare_digest(
        authorization,
        f"Bearer {expected.get_secret_value()}",
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Metrics authentication is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    metrics = getattr(request.app.state, "request_metrics", None)
    if not isinstance(metrics, RequestMetrics):
        raise TypeError("Request metrics are not configured")
    return Response(
        content=generate_latest(metrics.registry),
        media_type=CONTENT_TYPE_LATEST,
    )
