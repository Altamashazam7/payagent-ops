"""Application service for dependency readiness checks."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from app.repositories.readiness import ReadinessRepository

logger = logging.getLogger("payagent_ops")


class ReadinessService:
    """Evaluate required infrastructure through a repository boundary."""

    def __init__(self, repository: ReadinessRepository) -> None:
        self._repository = repository

    async def is_ready(self) -> bool:
        """Return false and log a safe event if the database probe fails."""
        try:
            await self._repository.check_database()
        except SQLAlchemyError:
            logger.exception(
                "Database readiness check failed",
                extra={
                    "event": "readiness_check_failed",
                    "dependency": "database",
                },
            )
            return False
        return True
