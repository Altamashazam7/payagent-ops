"""Redis-backed, tenant-isolated event publishing and subscription."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError
from redis.exceptions import RedisError

from app.events.schemas import EventEnvelope

_logger = logging.getLogger("payagent_ops.events")
_CHANNEL_PREFIX = "payagent.events.tenant."


class EventBus(Protocol):
    """Application-facing event transport contract."""

    async def ensure_connected(self) -> None: ...

    async def publish(self, event: EventEnvelope) -> None: ...

    def subscribe(
        self,
        tenant_id: UUID,
    ) -> AsyncGenerator[EventEnvelope | None, None]: ...

    async def aclose(self) -> None: ...


class _RedisPubSub(Protocol):
    async def subscribe(self, *channels: str) -> None: ...

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,
    ) -> dict[str, object] | None: ...

    async def aclose(self) -> None: ...


class _RedisConnection(Protocol):
    def ping(self, **kwargs: Any) -> Awaitable[bool]: ...

    def publish(
        self,
        channel: bytes | str | memoryview[int],
        message: bytes | bytearray | memoryview[int] | str | float,
        **kwargs: Any,
    ) -> Awaitable[int]: ...

    def pubsub(self) -> _RedisPubSub: ...

    async def aclose(self) -> None: ...


class RedisEventBus:
    """Publish JSON events over Redis Pub/Sub using tenant-derived channels."""

    def __init__(self, redis: _RedisConnection) -> None:
        self._redis = redis

    async def ensure_connected(self) -> None:
        """Check Redis before starting a long-lived event stream."""
        try:
            await self._redis.ping()
        except RedisError:
            _logger.exception(
                "Redis event transport is unavailable",
                extra={"event": "event_transport_unavailable"},
            )
            raise

    async def publish(self, event: EventEnvelope) -> None:
        """Publish a validated event only to its own tenant channel."""
        channel = self._channel(event.tenant_id)
        try:
            await self._redis.publish(channel, event.model_dump_json())
        except RedisError:
            _logger.exception(
                "Could not publish realtime event",
                extra={
                    "event": "event_publish_failed",
                    "event_id": str(event.event_id),
                    "event_type": event.event_type,
                },
            )
            raise

    async def subscribe(
        self,
        tenant_id: UUID,
    ) -> AsyncGenerator[EventEnvelope | None, None]:
        """Yield tenant events, or None after an idle heartbeat interval."""
        channel = self._channel(tenant_id)
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(channel)
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=20,
                )
                if message is None:
                    yield None
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if not isinstance(data, (bytes, str)):
                    _logger.error(
                        "Redis delivered an event with an invalid payload type",
                        extra={"event": "event_payload_rejected"},
                    )
                    continue
                try:
                    event = EventEnvelope.model_validate_json(data)
                except (ValidationError, ValueError):
                    _logger.exception(
                        "Redis delivered an invalid event envelope",
                        extra={"event": "event_payload_rejected"},
                    )
                    continue
                if event.tenant_id != tenant_id:
                    _logger.error(
                        "Redis delivered an event on the wrong tenant channel",
                        extra={
                            "event": "event_tenant_mismatch",
                            "event_id": str(event.event_id),
                        },
                    )
                    continue
                yield event
        except RedisError:
            _logger.exception(
                "Redis event subscription failed",
                extra={"event": "event_subscription_failed"},
            )
            raise
        finally:
            await pubsub.aclose()

    async def aclose(self) -> None:
        """Close the shared Redis connection pool."""
        await self._redis.aclose()

    @staticmethod
    def _channel(tenant_id: UUID) -> str:
        return f"{_CHANNEL_PREFIX}{tenant_id.hex}"
