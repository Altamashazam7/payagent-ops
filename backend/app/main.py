"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.health import probe_router
from app.api.v1.health import router as health_router
from app.core.constants import SERVICE_NAME
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.db.session import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with isolated configuration and resources."""
    app_settings = settings or get_settings()
    logger: logging.Logger = configure_logging(app_settings.log_level)
    database = Database(
        app_settings.database_url,
        echo=app_settings.database_echo,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "Application started",
            extra={"event": "application_started", "service": SERVICE_NAME},
        )
        try:
            yield
        finally:
            await database.dispose()
            logger.info(
                "Application stopped",
                extra={"event": "application_stopped", "service": SERVICE_NAME},
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
    application.include_router(health_router, prefix=app_settings.api_v1_prefix)
    application.include_router(probe_router)
    return application
