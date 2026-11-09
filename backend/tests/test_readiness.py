"""Readiness service behavior tests."""

import json
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import JsonLogFormatter
from app.services.readiness import ReadinessService


class AvailableRepository:
    async def check_database(self) -> None:
        return None


class UnavailableRepository:
    async def check_database(self) -> None:
        raise SQLAlchemyError("database unavailable")


async def test_readiness_service_reports_available_repository() -> None:
    service = ReadinessService(AvailableRepository())

    assert await service.is_ready() is True


async def test_readiness_service_logs_database_failure_as_not_ready() -> None:
    service = ReadinessService(UnavailableRepository())

    assert await service.is_ready() is False


def test_json_log_formatter_includes_structured_error_fields() -> None:
    record = logging.getLogger("payagent_ops").makeRecord(
        "payagent_ops",
        logging.ERROR,
        __file__,
        1,
        "Database readiness check failed",
        (),
        None,
        extra={
            "event": "readiness_check_failed",
            "dependency": "database",
        },
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "readiness_check_failed"
    assert payload["dependency"] == "database"
    assert payload["level"] == "error"
