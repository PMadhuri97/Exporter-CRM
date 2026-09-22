"""Real-time Kafka Stream Processor for Idempotency Violation Detection (S4T2).

Consumes posted events carrying idempotency keys from the Kafka event bus.
Cross-references incoming events against the idempotency registry (ledger.idempotency_record)
and active DB records. Mismatches trigger immediate alerts (< 30 seconds).

Updates Prometheus gauge `aner_idempotency_stream_processor_last_run_timestamp`.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.idempotency.alerting import dispatch_violation_alert
from app.platform.idempotency.models import IdempotencyRecord
from app.platform.messaging.consumers import BaseConsumer
from app.platform.messaging.schemas import ALL_TOPICS, EventEnvelope
from app.platform.observability.metrics import IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN

logger = structlog.get_logger(__name__)


class IdempotencyViolationStreamProcessor(BaseConsumer):
    """Kafka stream processor checking real-time events for idempotency registry mismatches."""

    group = "idempotency-violation-detector"
    topics = list(ALL_TOPICS)

    async def handle(self, db: AsyncSession, envelope: EventEnvelope) -> None:
        """Process incoming event and cross-reference idempotency key and scope_id."""
        payload = envelope.payload or {}
        idempotency_key = (
            payload.get("idempotency_key")
            or payload.get("key_value")
            or envelope.partition_key
        )

        # Update last run timestamp in Prometheus metric
        IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN.set(time.time())

        if not idempotency_key:
            return

        scope_id = payload.get("scope_id") or payload.get("sender_customer_id") or "global"
        event_id = envelope.event_id

        # Query idempotency registry for existing completed/active record matching BOTH key_value AND scope_id
        stmt = (
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.key_value == idempotency_key,
                IdempotencyRecord.scope_id == scope_id,
                IdempotencyRecord.status.in_(["active", "completed"]),
            )
            .limit(10)
        )
        res = await db.execute(stmt)
        records = res.scalars().all()

        # Violation trigger conditions:
        # 1. Multiple active/completed records exist in registry for the same (key_value, scope_id).
        # 2. An event arrives for an already COMPLETED key with a different correlation ID / transaction ID (replay violation).
        is_duplicate = len(records) > 1 or (
            len(records) == 1
            and records[0].status.value == "completed"
            and records[0].correlation_id is not None
            and envelope.correlation_id is not None
            and records[0].correlation_id != envelope.correlation_id
        )


        if is_duplicate:
            involved_ids = [str(r.id) for r in records] + [event_id]
            logger.warning(
                "stream_processor_duplicate_event_detected",
                idempotency_key=idempotency_key,
                scope_id=scope_id,
                event_type=envelope.event_type.value,
            )
            await dispatch_violation_alert(
                db,
                key_value=idempotency_key,
                scope=scope_id,
                operation_type=envelope.event_type.value,
                execution_count=max(len(records) + 1, 2),
                involved_object_ids=involved_ids,
                correlation_id=envelope.correlation_id or event_id,
            )
