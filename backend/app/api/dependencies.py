"""FastAPI dependencies for application infrastructure."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.db.dependencies import get_session
from app.events.bus import EventBus, RedisEventBus
from app.events.notifications import NotificationService
from app.integrations.paypal import PayPalClients
from app.repositories.readiness import SqlAlchemyReadinessRepository
from app.services.readiness import ReadinessService


def get_settings_from_request(request: Request) -> Settings:
    """Resolve validated settings owned by the active application."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise TypeError("The application settings are not configured")
    return settings


def get_paypal_clients(request: Request) -> PayPalClients:
    """Resolve the application-scoped PayPal clients for dependency injection."""
    clients = getattr(request.app.state, "paypal_clients", None)
    if not isinstance(clients, PayPalClients):
        raise TypeError("PayPal clients are not configured")
    return clients


def get_event_bus(request: Request) -> EventBus:
    """Resolve the application-scoped Redis event bus."""
    event_bus = getattr(request.app.state, "event_bus", None)
    if not isinstance(event_bus, RedisEventBus):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Real-time events are not configured",
        )
    return event_bus


def get_notification_service(
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> NotificationService:
    """Construct the notification publisher from the shared event transport."""
    return NotificationService(event_bus)


def get_readiness_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReadinessService:
    """Construct the readiness service with request-scoped persistence."""
    return ReadinessService(SqlAlchemyReadinessRepository(session))
