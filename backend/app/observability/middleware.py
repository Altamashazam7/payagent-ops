"""ASGI request correlation, tracing, structured logging, and metrics."""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from opentelemetry.trace import Status, StatusCode, Tracer
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.metrics import RequestMetrics


class RequestObservabilityMiddleware:
    """Instrument HTTP requests without buffering streaming responses."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: RequestMetrics,
        tracer: Tracer,
        logger: logging.Logger,
    ) -> None:
        self._app = app
        self._metrics = metrics
        self._tracer = tracer
        self._logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = str(uuid4())
        method = str(scope.get("method", "UNKNOWN"))
        route = "unmatched"
        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal route, status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                route_object: Any = scope.get("route")
                route_candidate = getattr(route_object, "path", None)
                if isinstance(route_candidate, str):
                    route = route_candidate
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        with self._tracer.start_as_current_span("http.server.request") as active_span:
            active_span.set_attribute("http.request.method", method)
            try:
                await self._app(scope, receive, send_with_request_id)
            except Exception as exc:
                active_span.record_exception(exc)
                active_span.set_status(Status(StatusCode.ERROR))
                self._logger.exception(
                    "HTTP request failed",
                    extra={
                        "event": "http_request_failed",
                        "request_id": request_id,
                        "http_method": method,
                        "route": route,
                    },
                )
                raise
            finally:
                duration = time.perf_counter() - started
                active_span.set_attribute("http.route", route)
                active_span.set_attribute("http.response.status_code", status_code)
                if status_code >= 500:
                    active_span.set_status(Status(StatusCode.ERROR))
                self._metrics.observe(
                    method=method,
                    route=route,
                    status_code=status_code,
                    duration_seconds=duration,
                )
                span_context = active_span.get_span_context()
                log_fields: dict[str, object] = {
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "http_method": method,
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 3),
                }
                if span_context.is_valid:
                    log_fields["trace_id"] = f"{span_context.trace_id:032x}"
                self._logger.info(
                    "HTTP request completed",
                    extra=log_fields,
                )
