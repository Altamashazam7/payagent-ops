"""Tests for realtime event contracts and notification publishing."""

from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies import get_event_bus
from app.core.auth.dependencies import get_current_user
from app.core.auth.jwt import UserContext
from app.events.notifications import NotificationService
from app.events.schemas import EventEnvelope, NotificationPayload
from app.models.enums import UserRole


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def ensure_connected(self) -> None:
        return None

    async def publish(self, event: EventEnvelope) -> None:
        self.events.append(event)

    async def subscribe(
        self,
        tenant_id: UUID,
    ) -> AsyncGenerator[EventEnvelope | None, None]:
        for event in self.events:
            if event.tenant_id == tenant_id:
                yield event

    async def aclose(self) -> None:
        return None


def test_authenticated_sse_stream_is_scoped_to_claimed_tenant(
    application: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    user = UserContext(
        sub=uuid4(),
        email="operator@example.invalid",
        tenant_id=tenant_id,
        role=UserRole.VIEWER,
    )
    bus = RecordingEventBus()
    bus.events.append(
        EventEnvelope(
            event_type="notification.created",
            tenant_id=tenant_id,
            payload={"title": "Synthetic event"},
        )
    )
    application.dependency_overrides[get_current_user] = lambda: user
    application.dependency_overrides[get_event_bus] = lambda: bus

    response = client.get("/api/v1/events/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: notification.created" in response.text
    assert f"id: {bus.events[0].event_id}" in response.text


@pytest.mark.asyncio
async def test_notification_service_publishes_to_the_requested_tenant() -> None:
    bus = RecordingEventBus()
    tenant_id = uuid4()
    notification = NotificationPayload(
        title="Review required",
        message="A synthetic dispute is ready for human review.",
        severity="warning",
    )

    event = await NotificationService(bus).notify(tenant_id, notification)

    assert event.tenant_id == tenant_id
    assert event.event_type == "notification.created"
    assert event.payload["title"] == "Review required"
    assert bus.events == [event]


def test_notification_rejects_external_navigation() -> None:
    with pytest.raises(ValidationError, match="same-origin"):
        NotificationPayload(
            title="Review",
            message="Open the record.",
            href="//outside.example/path",
        )


def test_event_envelope_rejects_naive_timestamp_and_invalid_type() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        EventEnvelope(
            tenant_id=uuid4(),
            event_type="commerce.updated",
            occurred_at=datetime(2026, 11, 9, 12, 0),
            payload={},
        )
    with pytest.raises(ValidationError, match="lowercase dotted identifier"):
        EventEnvelope(
            tenant_id=uuid4(),
            event_type="Commerce Updated",
            payload={},
        )


def test_event_envelope_bounds_payload_size() -> None:
    with pytest.raises(ValidationError, match="16 KiB"):
        EventEnvelope(
            tenant_id=uuid4(),
            event_type="commerce.updated",
            payload={"summary": "x" * 17_000},
        )
