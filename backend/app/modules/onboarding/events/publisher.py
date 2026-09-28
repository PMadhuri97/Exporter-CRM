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
    """Publishes `customer.*` lifecycle events."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or get_event_bus()

    async def _emit(
        self,
        event_type: EventType,
        *,
        customer_id: str,
        correlation_id: str | None,
        payload: dict,
        actor_id: str | None = None,
        deal_id: str | None = None,
    ) -> None:
        envelope = build_envelope(
            event_type,
            partition_key=customer_id,   # customer events are ordered per customer
            transaction_id=None,         # onboarding is not tied to a transaction
            correlation_id=_resolve_correlation_id(correlation_id),
            actor_id=actor_id,
            deal_id=deal_id,
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

    # ── Exporter CRM handovers ───────────────────────────────────────────────
    #
    # Both follow the same rule, and it is the whole rule: **announce after the
    # history row is written, and never let the announcement affect the change
    # it announces.** The history row is the source of truth; this is a
    # notification that may be dropped. `_emit` already swallows and logs every
    # publish failure, so a caller that awaits one of these cannot be made to
    # fail, roll back, or lose its change by anything the bus does.
    #
    # Neither is called by anything yet. The transitions that should fire them
    # belong to Developer 2 (a company becoming a CUSTOMER) and Developer 3
    # (handing a deal over); this is the helper they call when they build them,
    # so the envelope and payload are settled before two people guess at them.

    async def company_became_customer(
        self,
        *,
        company_id: str | uuid.UUID,
        name: str,
        country: str,
        pan: str | None,
        gstins: list[str],
        risk_rating: str,
        clearing_decision_id: str | uuid.UUID,
        actor_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Announce that a company is now a CUSTOMER.

        Payload per `docs/contracts/event-envelope.md` §3. The company is the
        partition key; `actor_id` is whoever's action completed the move, taken
        from their login session by the caller.

        `pan` is sent raw and unmasked on purpose: this is a system-to-system
        announcement to the customers team, not a response to a browser, and
        the receiving team needs the identifier to match the company against
        its own records. The masking rules govern what a *viewer* sees.
        """
        await self._emit(
            EventType.COMPANY_BECAME_CUSTOMER,
            customer_id=str(company_id),
            correlation_id=correlation_id,
            actor_id=actor_id,
            deal_id=None,
            payload={
                "company_id": str(company_id),
                "name": name,
                "country": country,
                "pan": pan,
                "gstins": list(gstins),
                "risk_rating": risk_rating,
                "clearing_decision_id": str(clearing_decision_id),
            },
        )

    async def deal_handed_over(
        self,
        *,
        deal_id: str | uuid.UUID,
        company_id: str | uuid.UUID,
        buyer: dict,
        document_ids: list[str],
        actor_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Announce that a deal has passed to the lending team.

        The company is still the partition key, so a company's events stay
        ordered together even when one of them is about a deal; the deal is on
        the envelope as `deal_id`.

        `document_ids` is the list the handover rested on at the moment it
        happened — a snapshot, so a later upload cannot change what the lending
        team was given.
        """
        await self._emit(
            EventType.DEAL_HANDED_OVER,
            customer_id=str(company_id),
            correlation_id=correlation_id,
            actor_id=actor_id,
            deal_id=str(deal_id),
            payload={
                "deal_id": str(deal_id),
                "company_id": str(company_id),
                "buyer": dict(buyer),
                "document_ids": list(document_ids),
            },
        )
