"""
Onboarding event publisher.

Publishes the customer-lifecycle events onto the shared event bus (in-memory or
Kafka, per KAFKA_ENABLED) using the platform's canonical EventEnvelope. Kept as a
small module-local publisher rather than extending the settlement `EventProducer`
so the onboarding module stays self-contained.

Best-effort by design — a publish failure is logged and swallowed so it never
breaks the onboarding operation that triggered it (same discipline as
EventProducer._emit).
"""
from __future__ import annotations

import uuid

import structlog
import structlog.contextvars

from app.modules.onboarding.events.case_bridge_consumer import ensure_case_bridge_subscribed
from app.platform.messaging.ports import EventBus, get_event_bus
from app.platform.messaging.schemas import EventType, build_envelope
from app.platform.observability.metrics import record_event

logger = structlog.get_logger(__name__)


def _resolve_correlation_id(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    raw = structlog.contextvars.get_contextvars().get("correlation_id")
    return str(raw) if raw else None


class OnboardingEventPublisher:
    """Publishes `customer.*` and `exporter.*` lifecycle events."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or get_event_bus()
        # The one place the case bridge is attached — see case_bridge_consumer.py.
        ensure_case_bridge_subscribed(self._bus)

    async def _emit(
        self,
        event_type: EventType,
        *,
        customer_id: str,
        correlation_id: str | None,
        payload: dict,
    ) -> None:
        envelope = build_envelope(
            event_type,
            partition_key=customer_id,   # customer events are ordered per customer
            transaction_id=None,         # onboarding is not tied to a transaction
            correlation_id=_resolve_correlation_id(correlation_id),
            payload=payload,
        )
        try:
            await self._bus.publish(envelope)
            record_event(event_type.value)
            logger.info(
                "onboarding_event_published",
                event_type=event_type.value,
                event_id=envelope.event_id,
                customer_id=customer_id,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning(
                "onboarding_event_publish_failed",
                event_type=event_type.value,
                customer_id=customer_id,
                error=str(exc),
            )

    async def customer_registered(
        self,
        *,
        customer_id: str | uuid.UUID,
        email: str,
        external_user_id: str,
        provider: str,
        correlation_id: str | None = None,
    ) -> None:
        await self._emit(
            EventType.CUSTOMER_REGISTERED,
            customer_id=str(customer_id),
            correlation_id=correlation_id,
            payload={"email": email, "external_user_id": external_user_id, "provider": provider},
        )

    async def customer_verification_updated(
        self,
        *,
        customer_id: str | uuid.UUID,
        status: str,
        provider_ref: str | None,
        review_answer: str | None,
        correlation_id: str | None = None,
    ) -> None:
        await self._emit(
            EventType.CUSTOMER_VERIFICATION_UPDATED,
            customer_id=str(customer_id),
            correlation_id=correlation_id,
            payload={
                "status": status,
                "provider_ref": provider_ref,
                "review_answer": review_answer,
            },
        )

    # ── Exporter CRM ───────────────────────────────────────────────────────
    # Called after the triggering write has committed, so a failed publish
    # can never roll it back. The durable record is the write itself (e.g. the
    # exporter_lifecycle_history row); these are the notification channel.

    async def exporter_lifecycle_changed(
        self,
        *,
        customer_id: str | uuid.UUID,
        from_status: str | None,
        to_status: str,
        actor_id: str | None,
        correlation_id: str | None = None,
    ) -> None:
        await self._emit(
            EventType.EXPORTER_LIFECYCLE_CHANGED,
            customer_id=str(customer_id),
            correlation_id=correlation_id,
            payload={
                "customer_id": str(customer_id),
                "from_status": from_status,
                "to_status": to_status,
                "actor_id": actor_id,
            },
        )

    async def exporter_screening_review_updated(
        self,
        *,
        customer_id: str | uuid.UUID,
        item_id: str | uuid.UUID,
        item_key: str,
        status: str,
        reviewed_by: str | None,
        correlation_id: str | None = None,
    ) -> None:
        await self._emit(
            EventType.EXPORTER_SCREENING_REVIEW_UPDATED,
            customer_id=str(customer_id),
            correlation_id=correlation_id,
            payload={
                "customer_id": str(customer_id),
                "item_id": str(item_id),
                "item_key": item_key,
                "status": status,
                "reviewed_by": reviewed_by,
            },
        )

    async def exporter_verification_reviewed(
        self,
        *,
        verification_result_id: str | uuid.UUID,
        entity_type: str,
        entity_reference: str | uuid.UUID,
        verification_type: str,
        status: str,
        review_status: str,
        reviewed_by: str,
        correlation_id: str | None = None,
    ) -> None:
        # Keyed on entity_reference: for an EXPORTER result that is the
        # customer_id, so it orders with the exporter's other events.
        await self._emit(
            EventType.EXPORTER_VERIFICATION_REVIEWED,
            customer_id=str(entity_reference),
            correlation_id=correlation_id,
            payload={
                "verification_result_id": str(verification_result_id),
                "entity_type": entity_type,
                "entity_reference": str(entity_reference),
                "verification_type": verification_type,
                "status": status,
                "review_status": review_status,
                "reviewed_by": reviewed_by,
            },
        )

    # EventType.EXPORTER_DOCUMENT_SCAN_COMPLETED is reserved; the document-scan
    # phase adds its publisher method here.
