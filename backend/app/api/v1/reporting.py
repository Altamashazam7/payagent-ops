"""Authenticated read-only commerce reporting and copilot endpoints."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from openai import APIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.executive.service import ExecutiveCopilotService
from app.api.dependencies import get_settings_from_request
from app.core.auth.jwt import UserContext
from app.core.auth.permissions import COPILOT_ROLES, REPORTING_ROLES, require_roles
from app.core.settings import Settings
from app.db.dependencies import get_session
from app.models.enums import DisputeStatus, InvoiceStatus, PayoutStatus
from app.schemas.analytics import (
    ActivityRow,
    CopilotAnswer,
    CopilotOverview,
    CopilotQuestion,
    DashboardSummary,
    DashboardTrends,
    DisputeRow,
    InvoiceRow,
    Page,
    PayoutRow,
)
from app.services.analytics import AnalyticsService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reporting"])


def get_analytics_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[
        UserContext,
        Depends(require_roles(*REPORTING_ROLES)),
    ],
) -> AnalyticsService:
    """Create reporting service scoped to the authenticated tenant claim."""
    return AnalyticsService(session, current_user.tenant_id)


async def get_executive_copilot_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[
        UserContext,
        Depends(require_roles(*COPILOT_ROLES)),
    ],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AsyncIterator[ExecutiveCopilotService]:
    """Create copilot service with the authenticated tenant and configured model."""
    try:
        service = ExecutiveCopilotService.from_settings(
            session,
            current_user.tenant_id,
            settings,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Executive copilot is not configured",
        ) from exc
    try:
        yield service
    finally:
        await service.aclose()


ReportingService = Annotated[AnalyticsService, Depends(get_analytics_service)]
CopilotService = Annotated[
    ExecutiveCopilotService,
    Depends(get_executive_copilot_service),
]


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def read_dashboard_summary(
    service: ReportingService,
) -> DashboardSummary:
    """Return tenant-scoped executive KPIs."""
    return await service.dashboard_summary()


@router.get("/dashboard/trends", response_model=DashboardTrends)
async def read_dashboard_trends(
    service: ReportingService,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> DashboardTrends:
    """Return daily tenant-scoped revenue and dispute trend data."""
    return await service.dashboard_trends(days=days)


@router.get("/disputes", response_model=Page[DisputeRow])
async def read_disputes(
    service: ReportingService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status_filter: Annotated[DisputeStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> Page[DisputeRow]:
    """Return a bounded, tenant-scoped disputes page."""
    return await service.list_disputes(
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        search=search,
    )


@router.get("/invoices", response_model=Page[InvoiceRow])
async def read_invoices(
    service: ReportingService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> Page[InvoiceRow]:
    """Return a bounded, tenant-scoped invoices page."""
    return await service.list_invoices(
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        search=search,
    )


@router.get("/payouts", response_model=Page[PayoutRow])
async def read_payouts(
    service: ReportingService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status_filter: Annotated[PayoutStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> Page[PayoutRow]:
    """Return a bounded payout page without payee destination details."""
    return await service.list_payouts(
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        search=search,
    )


@router.get("/activity", response_model=Page[ActivityRow])
async def read_activity(
    service: ReportingService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ActivityRow]:
    """Return a bounded audit activity page without raw before/after state."""
    return await service.list_activity(offset=offset, limit=limit)


@router.get("/copilot/insights", response_model=CopilotOverview)
async def read_copilot_insights(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[
        UserContext,
        Depends(require_roles(*COPILOT_ROLES)),
    ],
) -> CopilotOverview:
    """Return deterministic executive insights without requiring an LLM key."""
    service = ExecutiveCopilotService(session, current_user.tenant_id)
    return await service.overview()


@router.post(
    "/copilot/ask",
    response_model=CopilotAnswer,
    status_code=status.HTTP_200_OK,
)
async def ask_copilot(
    request: CopilotQuestion,
    service: CopilotService,
) -> CopilotAnswer:
    """Answer an informational question using tenant aggregates only."""
    try:
        return await service.answer(request)
    except APIError as exc:
        logger.exception(
            "Executive copilot provider request failed",
            extra={"event": "executive_copilot_provider_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Executive copilot provider is unavailable",
        ) from exc
    except ValueError as exc:
        logger.exception(
            "Executive copilot returned invalid content",
            extra={"event": "executive_copilot_invalid_response"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Executive copilot could not produce a valid answer",
        ) from exc
