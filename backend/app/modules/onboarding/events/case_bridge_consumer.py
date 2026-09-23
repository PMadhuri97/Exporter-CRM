"""The case bridge's bus subscription (ANER-4.3-S2T1, in-memory stand-in).

The ticket specifies a Kafka consumer. This checkout runs the in-memory bus, so
the bridge subscribes to that instead. It has the same shape: a `BaseConsumer`
group on `Topic.CUSTOMER`, idempotent per `event_id` via `processed_events`. Moving
to Kafka is configuration.

**Removable in one place.** `ensure_case_bridge_subscribed` is called from one
line, in `OnboardingEventPublisher.__init__`. Delete that line and onboarding no
longer opens cases. `app.modules.cases` does not know this consumer exists.

**Why subscription happens at publish time, not at startup.** The consumer list
lives in `app/bootstrap.py`, which this module does not own, and it is registered
only when `EVENT_CONSUMERS_ENABLED` is set. Tests also install a new bus through
`set_event_bus`. Subscribing lazily, once per bus instance, on whichever bus the
publisher is about to use, keeps the bridge attached in every one of those cases.
With Kafka, the proper home is `bootstrap.ALL_CONSUMERS`: consumer groups are
started by `bus.start()`, and a group subscribed after that may never be polled.
Add `CaseBridgeConsumer()` there when Kafka is switched on.
"""

from __future__ import annotations

import weakref

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.messaging.consumers import BaseConsumer
from app.platform.messaging.ports import EventBus
from app.platform.messaging.schemas import EventEnvelope, Topic

logger = structlog.get_logger(__name__)

CASE_BRIDGE_GROUP = "onboarding-case-bridge"

_subscribed_buses: weakref.WeakSet[EventBus] = weakref.WeakSet()


class CaseBridgeConsumer(BaseConsumer):
    """Routes exporter CRM events to `CaseBridgeService`."""

    group = CASE_BRIDGE_GROUP
    topics = [Topic.CUSTOMER]

    async def handle(self, db: AsyncSession, envelope: EventEnvelope) -> None:
        # Imported here, not at module scope: application/ imports the
        # publisher, which imports this module.
        from app.modules.onboarding.application.case_bridge_service import CaseBridgeService

        await CaseBridgeService(db).handle_event(envelope)


def ensure_case_bridge_subscribed(bus: EventBus) -> None:
    """Subscribe `CaseBridgeConsumer` to `bus` once. Never raises: a failure
    here must not stop the publisher from being built."""
    try:
        if bus in _subscribed_buses:
            return
        bus.subscribe(CASE_BRIDGE_GROUP, CaseBridgeConsumer.topics, CaseBridgeConsumer())
        _subscribed_buses.add(bus)
        logger.info("case_bridge_subscribed", consumer_group=CASE_BRIDGE_GROUP)
    except Exception as exc:  # noqa: BLE001 — best-effort, like publish
        logger.warning("case_bridge_subscribe_failed", error=str(exc))


__all__ = ["CASE_BRIDGE_GROUP", "CaseBridgeConsumer", "ensure_case_bridge_subscribed"]
