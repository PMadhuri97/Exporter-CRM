"""
Notification's Kafka consumer.

Lives here, not in platform/messaging, because it calls NotificationService and
platform/ may not import a module (ARCHITECTURE.md §2). Idempotency scaffolding is
inherited from platform's BaseConsumer.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.messaging.consumers import BaseConsumer
from app.platform.messaging.schemas import EventEnvelope, EventType, Topic

logger = structlog.get_logger(__name__)


class NotificationConsumer(BaseConsumer):
    """
    Consumes settlement events and, for customer-visible outcomes, creates a PENDING
    NotificationEvent for outbound webhook delivery (delivery + 60s SLA later).
    """

    group = "notification-service"
    topics = [Topic.SETTLEMENT]

    _NOTIFY_ON = {
        EventType.SETTLEMENT_COMPLETED: "payment.settled",
        EventType.SETTLEMENT_FAILED: "payment.failed",
        EventType.COMPENSATION_COMPLETED: "payment.recalled",
    }

    async def handle(self, db: AsyncSession, envelope: EventEnvelope) -> None:
        webhook_event = self._NOTIFY_ON.get(envelope.event_type)
        if webhook_event is None or envelope.transaction_id is None:
            return

        from app.modules.notifications.application.services import NotificationService

        service = NotificationService(db)
        await service.queue_notification(
            transaction_id=uuid.UUID(envelope.transaction_id),
            event_type=webhook_event,
            webhook_url="https://customer.example/webhooks/aner",
            payload={
                "correlation_id": envelope.correlation_id,
                "payload": envelope.payload,
            },
        )
        logger.info(
            "notification_queued",
            webhook_event=webhook_event,
            transaction_id=envelope.transaction_id,
        )
