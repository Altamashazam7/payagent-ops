"""Optional OTLP tracing and Sentry error-reporting setup."""

from __future__ import annotations

import logging

import sentry_sdk
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from app.core.constants import SERVICE_NAME
from app.core.settings import Settings

_logger = logging.getLogger("payagent_ops.observability")


def configure_tracing(settings: Settings) -> tuple[Tracer, TracerProvider | None]:
    """Create an OTLP-backed tracer only when a collector is configured."""
    endpoint = settings.otel_exporter_otlp_traces_endpoint
    if endpoint is None:
        return trace.get_tracer_provider().get_tracer(SERVICE_NAME), None

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": SERVICE_NAME,
                "deployment.environment.name": settings.environment,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    return provider.get_tracer(SERVICE_NAME), provider


def configure_sentry(settings: Settings) -> None:
    """Enable Sentry only when an operator supplies a DSN."""
    if settings.sentry_dsn is None:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )
    _logger.info(
        "Sentry error reporting enabled",
        extra={"event": "sentry_enabled", "service": SERVICE_NAME},
    )
