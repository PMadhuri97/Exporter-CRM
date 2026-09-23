"""The case bridge's bus subscription (ANER-4.3-S2T1, in-memory stand-in).

The ticket specifies a Kafka consumer. This checkout runs the in-memory bus, so
the bridge subscribes to that instead. It has the same shape: a `BaseConsumer`
group on `Topic.CUSTOMER`, idempotent per `event_id` via `processed_events`. Moving
to Kafka is configuration.

**Two places subscribe it, one per bus kind.**

- *At startup:* `bootstrap.register_consumers` calls `ensure_case_bridge_subscribed`
  before `bus.start()`. This is the only path that works for Kafka, because
  `KafkaEventBus.start()` creates a consumer only for groups already
  subscribed. A group added afterwards is never polled.
- *At publish time, in-memory bus only:* `OnboardingEventPublisher.__init__`
  calls `ensure_case_bridge_subscribed(bus, lazy=True)`. The in-memory bus
  dispatches synchronously to whatever is subscribed, whether or not
  `EVENT_CONSUMERS_ENABLED` started the event tier, and tests install new buses
  through `set_event_bus`. For any other bus the lazy call does nothing, since
  subscribing there would look attached and never run.

Both paths share `_subscribed_buses`, so a bus never gets the group twice.
If the bridge is not attached at all (Kafka with the event tier off), no case
opens on entry to COMPLIANCE_REVIEW. Onboarding still cannot skip one: the
lifecycle route refuses a direct approval and opens the case on demand
(`CaseBridgeService.ensure_review_case`).

**Removable in two lines**, the two calls above. `app.modules.cases` does not
know this consumer exists.
"""

from __future__ import annotations

import weakref

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.messaging.consumers import BaseConsumer
from app.platform.messaging.ports import EventBus, InMemoryEventBus
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


def ensure_case_bridge_subscribed(bus: EventBus, *, lazy: bool = False) -> None:
    """Subscribe `CaseBridgeConsumer` to `bus` once. `lazy=True` (the
    publisher's call) only acts on an `InMemoryEventBus`; see the module
    docstring. Never raises: a failure here must not stop the publisher from
    being built."""
    try:
        if bus in _subscribed_buses:
            return
        if lazy and not isinstance(bus, InMemoryEventBus):
            return
        bus.subscribe(CASE_BRIDGE_GROUP, CaseBridgeConsumer.topics, CaseBridgeConsumer())
        _subscribed_buses.add(bus)
        logger.info("case_bridge_subscribed", consumer_group=CASE_BRIDGE_GROUP)
    except Exception as exc:  # noqa: BLE001 — best-effort, like publish
        logger.warning("case_bridge_subscribe_failed", error=str(exc))


__all__ = ["CASE_BRIDGE_GROUP", "CaseBridgeConsumer", "ensure_case_bridge_subscribed"]
