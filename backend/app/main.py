"""FastAPI application entry point."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.v1.events import router as events_router
from app.api.v1.health import probe_router
from app.api.v1.health import router as health_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.reporting import router as reporting_router
from app.core.auth.jwt import OIDCJWTVerifier
from app.core.constants import SERVICE_NAME
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.session import Database
from app.events.bus import RedisEventBus
from app.integrations.paypal import PayPalClients, create_paypal_clients
from app.integrations.paypal.approval import HumanApprovalVerifier
from app.observability.metrics import RequestMetrics
from app.observability.middleware import RequestObservabilityMiddleware
from app.observability.tracing import configure_sentry, configure_tracing


def create_app(
    settings: Settings | None = None,
    *,
    paypal_approval_verifier: HumanApprovalVerifier | None = None,
) -> FastAPI:
    """Create an application instance with isolated configuration and resources."""
    app_settings = settings or get_settings()
    logger: logging.Logger = configure_logging(app_settings.log_level)
    database = Database(
        app_settings.database_url,
        echo=app_settings.database_echo,
    )
    paypal_clients: PayPalClients = create_paypal_clients(
        app_settings,
        approval_verifier=paypal_approval_verifier,
    )
    oidc_http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        follow_redirects=False,
    )
    jwt_verifier = OIDCJWTVerifier(app_settings, oidc_http_client)
    redis_client = (
        Redis.from_url(
            app_settings.redis_url.get_secret_value(),
            decode_responses=False,
        )
        if app_settings.redis_url is not None
        else None
    )
    event_bus = RedisEventBus(redis_client) if redis_client is not None else None
    metrics = RequestMetrics()
    tracer, tracer_provider = configure_tracing(app_settings)
    configure_sentry(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "Application started",
            extra={"event": "application_started", "service": SERVICE_NAME},
        )
        try:
            yield
        finally:
            try:
                if event_bus is not None:
                    await event_bus.aclose()
            finally:
                try:
                    await paypal_clients.aclose()
                finally:
                    try:
                        await oidc_http_client.aclose()
                    finally:
                        try:
                            await database.dispose()
                        finally:
                            if tracer_provider is not None:
                                await asyncio.to_thread(tracer_provider.shutdown)
                            logger.info(
                                "Application stopped",
                                extra={
                                    "event": "application_stopped",
                                    "service": SERVICE_NAME,
                                },
                            )

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="API for the PayAgent Ops commerce operations platform.",
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database = database
    application.state.paypal_clients = paypal_clients
    application.state.jwt_verifier = jwt_verifier
    application.state.event_bus = event_bus
    application.state.request_metrics = metrics
    application.add_middleware(
        RequestObservabilityMiddleware,
        metrics=metrics,
        tracer=tracer,
        logger=logger,
    )
    application.include_router(health_router, prefix=app_settings.api_v1_prefix)
    application.include_router(reporting_router, prefix=app_settings.api_v1_prefix)
    application.include_router(events_router, prefix=app_settings.api_v1_prefix)
    application.include_router(metrics_router)
    application.include_router(probe_router)
    return application
