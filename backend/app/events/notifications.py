"""Application service for emitting tenant-scoped notifications."""

from uuid import UUID

from app.events.bus import EventBus
from app.events.schemas import EventEnvelope, NotificationPayload


class NotificationService:
    """Convert notification content into validated realtime events."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def notify(
        self,
        tenant_id: UUID,
        notification: NotificationPayload,
    ) -> EventEnvelope:
        """Publish a notification without coupling it to a domain workflow."""
        event = EventEnvelope(
            event_type="notification.created",
            tenant_id=tenant_id,
            payload=notification.model_dump(mode="json"),
        )
        await self._event_bus.publish(event)
        return event
