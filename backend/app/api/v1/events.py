"""Authenticated server-sent event stream."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_event_bus
from app.core.auth.jwt import UserContext
from app.core.auth.permissions import REPORTING_ROLES, require_roles
from app.db.dependencies import get_session
from app.events.bus import EventBus
from app.events.schemas import EventEnvelope

router = APIRouter(prefix="/events", tags=["events"])
_logger = logging.getLogger("payagent_ops.events")


async def _stream_user(
    current_user: Annotated[
        UserContext,
        Depends(require_roles(*REPORTING_ROLES)),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserContext:
    """Release the authentication query session before opening an SSE stream."""
    await session.close()
    return current_user


@router.get("/stream", response_class=StreamingResponse)
async def stream_events(
    request: Request,
    current_user: Annotated[UserContext, Depends(_stream_user)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """Stream only the authenticated user's tenant events."""
    try:
        await event_bus.ensure_connected()
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Realtime event transport is unavailable",
        ) from exc

    async def event_generator() -> AsyncGenerator[str, None]:
        subscription = event_bus.subscribe(current_user.tenant_id)
        try:
            async for event in subscription:
                if await request.is_disconnected():
                    return
                if event is None:
                    yield ": keep-alive\n\n"
                    continue
                yield _format_sse(event)
        except RedisError:
            _logger.exception(
                "Realtime stream ended after a Redis failure",
                extra={
                    "event": "event_stream_failed",
                    "tenant_id": str(current_user.tenant_id),
                },
            )
            yield 'event: stream.error\ndata: {"detail":"temporarily_unavailable"}\n\n'
        finally:
            await subscription.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _format_sse(event: EventEnvelope) -> str:
    """Serialize event data as a single safe SSE frame."""
    data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {data}\n\n"
