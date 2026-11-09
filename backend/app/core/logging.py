"""JSON logging configuration for application lifecycle events."""

import json
import logging
import sys
from datetime import UTC, datetime


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC)
        payload: dict[str, object] = {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, str):
            payload["event"] = event
        service = getattr(record, "service", None)
        if isinstance(service, str):
            payload["service"] = service
        dependency = getattr(record, "dependency", None)
        if isinstance(dependency, str):
            payload["dependency"] = dependency
        for field in (
            "provider",
            "operation",
            "http_method",
            "circuit_state",
            "error_code",
            "status_code",
            "request_id",
            "trace_id",
            "route",
            "duration_ms",
            "attempt",
            "agent_id",
            "decision_id",
            "dispute_id",
            "invoice_id",
            "payout_id",
            "reviewer_user_id",
            "vendor_id",
        ):
            value = getattr(record, field, None)
            if isinstance(value, (str, int, float)):
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure a dedicated structured logger without changing other loggers."""
    level = logging.getLevelNamesMapping().get(log_level.upper())
    if level is None:
        raise ValueError(f"Unsupported log level: {log_level}")

    logger = logging.getLogger("payagent_ops")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
