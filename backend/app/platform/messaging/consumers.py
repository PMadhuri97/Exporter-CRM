"""
Kafka consumers — the fan-out tier.

Each consumer is a distinct consumer group and is idempotent: before acting it
checks (consumer_group, event_id) in processed_events and skips if already handled
(Kafka delivers at-least-once). Side effects are deliberately non-overlapping with
the synchronous per-step audit writes that settlement activities still perform.

  • AuditEventConsumer        — ALL topics → writes EventLog (write-once event store)

The two business consumers live with the modules they drive, because they call those
modules' services and platform/ may not import modules (ARCHITECTURE.md §2):
  • ReconciliationConsumer    — app/modules/reconciliation/events/consumers.py
  • NotificationConsumer      — app/modules/notifications/events/consumers.py
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.messaging.models import EventLog, ProcessedEvent
from app.platform.messaging.schemas import ALL_TOPICS, EventEnvelope, Topic

logger = structlog.get_logger(__name__)


async def _already_processed(db: AsyncSession, group: str, event_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ProcessedEvent).where(
            ProcessedEvent.consumer_group == group,
            ProcessedEvent.event_id == event_id,
        )
    )
    return result.scalar_one_or_none() is not None


def _mark_processed(db: AsyncSession, group: str, envelope: EventEnvelope) -> None:
    db.add(
        ProcessedEvent(
            consumer_group=group,
            event_id=uuid.UUID(envelope.event_id),
            event_type=envelope.event_type.value,
        )
    )


def _opt_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


class BaseConsumer:
    """Common idempotency scaffolding. Subclasses implement topics + handle()."""

    group: str = "base"
    topics: list[Topic] = []

    async def __call__(self, envelope: EventEnvelope) -> None:
        from app.platform.database.services import AsyncSessionLocal

        event_id = uuid.UUID(envelope.event_id)
        async with AsyncSessionLocal() as db:
            try:
                if await _already_processed(db, self.group, event_id):
                    logger.debug(
                        "event_already_processed",
                        consumer_group=self.group,
                        event_id=envelope.event_id,
                    )
                    return
                await self.handle(db, envelope)
                _mark_processed(db, self.group, envelope)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def handle(self, db: AsyncSession, envelope: EventEnvelope) -> None:  # pragma: no cover
        raise NotImplementedError


class AuditEventConsumer(BaseConsumer):
    """Consumes every topic and materialises each event into the write-once EventLog."""

    group = "audit-service"
    topics = list(ALL_TOPICS)

    async def handle(self, db: AsyncSession, envelope: EventEnvelope) -> None:
        db.add(
            EventLog(
                event_id=uuid.UUID(envelope.event_id),
                topic=envelope.topic.value,
                event_type=envelope.event_type.value,
                partition_key=envelope.partition_key,
                transaction_id=_opt_uuid(envelope.transaction_id),
                correlation_id=_opt_uuid(envelope.correlation_id),
                producer=envelope.producer,
                occurred_at=envelope.occurred_at,
                payload=envelope.payload,
            )
        )
        logger.info(
            "audit_event_logged",
            event_type=envelope.event_type.value,
            event_id=envelope.event_id,
            transaction_id=envelope.transaction_id,
        )
