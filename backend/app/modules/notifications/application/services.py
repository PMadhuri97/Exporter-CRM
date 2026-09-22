from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.domain.entities.notifications import (
    NotificationChannel,
    NotificationEvent,
    WebhookStatus,
)
from app.modules.notifications.infrastructure.providers import resolve_provider
from app.modules.notifications.infrastructure.repository import NotificationEventRepository
from app.modules.payments import Transaction
from app.platform.configuration.config import get_settings

logger = structlog.get_logger(__name__)


# Customer-facing message + status per webhook event type. Replaces the previous
# behaviour where every delivery said "Payment failed" regardless of outcome.
_EVENT_COPY: dict[str, tuple[str, str]] = {
    # event_type: (customer-facing status, message template — {ref} is filled in)
    "payment.settled": ("SETTLED", "Payment settled successfully. Reference: {ref}"),
    "payment.failed": ("FAILED", "Payment failed. Funds secured. Reference: {ref}"),
    "payment.recalled": (
        "RECALLED_VIA_COMPENSATION",
        "Payment recalled via compensation. Funds secured. Reference: {ref}",
    ),
}
_DEFAULT_COPY = ("UPDATED", "Payment status updated. Reference: {ref}")


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = NotificationEventRepository(db)
        self._max_attempts = get_settings().NOTIFICATION_MAX_ATTEMPTS

    async def queue_notification(
        self,
        *,
        transaction_id: uuid.UUID,
        event_type: str,
        channel: NotificationChannel = NotificationChannel.WEBHOOK,
        webhook_url: str | None = None,
        recipient: str | None = None,
        payload: dict | None = None,
    ) -> NotificationEvent:
        body = {
            "event_type": event_type,
            "transaction_id": str(transaction_id),
            "payload": payload or {},
        }
        payload_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode("utf-8")
        ).hexdigest()

        event = NotificationEvent(
            transaction_id=transaction_id,
            event_type=event_type,
            channel=channel,
            webhook_url=webhook_url,
            recipient=recipient,
            payload_hash=payload_hash,
            status=WebhookStatus.PENDING,
        )
        await self._repo.create(event)
        await self._db.commit()
        logger.info(
            "notification_queued",
            transaction_id=str(transaction_id),
            event_type=event_type,
            channel=channel.value,
        )
        return event

    async def get_by_transaction(self, transaction_id: uuid.UUID) -> Sequence[NotificationEvent]:
        return await self._repo.list_by_transaction(transaction_id)

    async def list_pending(self) -> Sequence[NotificationEvent]:
        return await self._repo.list_pending()

    async def process_pending(self, *, limit: int = 10) -> list[NotificationEvent]:
        """Drain the deliverable queue (PENDING + retryable FAILED) oldest-first."""
        deliverable = await self._repo.list_deliverable()
        if not deliverable:
            return []

        processed: list[NotificationEvent] = []
        for event in deliverable[:limit]:
            processed.append(await self._deliver(event))
        return processed

    async def _deliver(self, event: NotificationEvent) -> NotificationEvent:
        event.attempt_count += 1
        event.last_attempted_at = datetime.now(UTC)

        destination = event.webhook_url if event.channel == NotificationChannel.WEBHOOK else event.recipient
        body = await self._build_body(event)
        provider = resolve_provider(event.channel)

        result = await provider.send(
            event_id=event.event_id,
            destination=destination or "",
            event_type=event.event_type,
            body=body,
        )

        if result.success:
            event.status = WebhookStatus.DELIVERED
            event.delivered_at = datetime.now(UTC)
            event.failure_reason = None
            logger.info(
                "notification_delivered",
                event_id=str(event.event_id),
                transaction_id=str(event.transaction_id),
                channel=event.channel.value,
                attempt=event.attempt_count,
            )
        else:
            event.failure_reason = result.detail or "delivery failed"
            exhausted = event.attempt_count >= self._max_attempts
            event.status = WebhookStatus.EXHAUSTED if exhausted else WebhookStatus.FAILED
            logger.warning(
                "notification_delivery_failed",
                event_id=str(event.event_id),
                transaction_id=str(event.transaction_id),
                channel=event.channel.value,
                attempt=event.attempt_count,
                status=event.status.value,
                error=event.failure_reason,
            )

        await self._db.commit()
        await self._db.refresh(event)
        return event

    async def _build_body(self, event: NotificationEvent) -> dict:
        """Constructs the outbound payload per the architecture webhook contract."""
        reference, correlation_id = await self._resolve_transaction_fields(event.transaction_id)
        status, template = _EVENT_COPY.get(event.event_type, _DEFAULT_COPY)
        return {
            "event_type": event.event_type,
            "transaction_id": str(event.transaction_id),
            "correlation_id": correlation_id,
            "status": status,
            "message": template.format(ref=reference),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _resolve_transaction_fields(
        self, transaction_id: uuid.UUID
    ) -> tuple[str, str | None]:
        """Returns (reference, correlation_id) for the transaction; falls back to the
        transaction id as the reference if no invoice reference is recorded."""
        result = await self._db.execute(
            select(Transaction.invoice_reference, Transaction.correlation_id).where(
                Transaction.transaction_id == transaction_id
            )
        )
        row = result.first()
        if row is None:
            return str(transaction_id), None
        invoice_reference, correlation_id = row
        return (invoice_reference or str(transaction_id)), (
            str(correlation_id) if correlation_id else None
        )
