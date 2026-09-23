"""Exporter CRM events (B6): the publish contract, without a database.

Best-effort is the whole contract: a bus that raises must not raise out of the
publisher, because the publisher runs after the write has committed, and a raise
would turn a successful write into a 500.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.events.case_bridge_consumer import (
    CASE_BRIDGE_GROUP,
    ensure_case_bridge_subscribed,
)
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.platform.messaging.ports import EventBus, InMemoryEventBus
from app.platform.messaging.schemas import TOPIC_FOR_EVENT, EventType, Topic

pytestmark = pytest.mark.asyncio

EXPORTER_EVENTS = (
    EventType.EXPORTER_LIFECYCLE_CHANGED,
    EventType.EXPORTER_SCREENING_REVIEW_UPDATED,
    EventType.EXPORTER_VERIFICATION_REVIEWED,
    EventType.EXPORTER_DOCUMENT_SCAN_COMPLETED,
)


class _ExplodingBus(EventBus):
    def __init__(self) -> None:
        self.subscriptions: list[str] = []
        self.attempts = 0

    def subscribe(self, group, topics, handler) -> None:
        self.subscriptions.append(group)

    async def publish(self, envelope) -> None:
        self.attempts += 1
        raise ConnectionError("broker unreachable")

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class _UnsubscribableBus(_ExplodingBus):
    def subscribe(self, group, topics, handler) -> None:
        raise RuntimeError("consumer groups frozen")


@pytest.mark.parametrize("event_type", EXPORTER_EVENTS)
async def test_exporter_events_route_to_the_customer_topic(event_type: EventType):
    assert TOPIC_FOR_EVENT[event_type] is Topic.CUSTOMER


async def test_lifecycle_event_carries_the_transition():
    bus = InMemoryEventBus()
    customer_id = uuid.uuid4()

    await OnboardingEventPublisher(bus).exporter_lifecycle_changed(
        customer_id=customer_id, from_status="LEAD", to_status="CONTACTED", actor_id="u-1"
    )

    [envelope] = bus.events_of_type(EventType.EXPORTER_LIFECYCLE_CHANGED)
    assert envelope.partition_key == str(customer_id)
    assert envelope.payload == {
        "customer_id": str(customer_id),
        "from_status": "LEAD",
        "to_status": "CONTACTED",
        "actor_id": "u-1",
    }


async def test_a_failing_bus_is_swallowed_for_every_exporter_event():
    bus = _ExplodingBus()
    publisher = OnboardingEventPublisher(bus)
    customer_id = uuid.uuid4()

    await publisher.exporter_lifecycle_changed(
        customer_id=customer_id, from_status=None, to_status="LEAD", actor_id=None
    )
    await publisher.exporter_screening_review_updated(
        customer_id=customer_id,
        item_id=uuid.uuid4(),
        item_key="website-reviewed",
        status="PASSED",
        reviewed_by="u-1",
    )
    await publisher.exporter_verification_reviewed(
        verification_result_id=uuid.uuid4(),
        entity_type="EXPORTER",
        entity_reference=customer_id,
        verification_type="KYB",
        status="PASSED",
        review_status="ACCEPTED",
        reviewed_by="u-1",
    )

    assert bus.attempts == 3


async def test_case_bridge_subscribes_once_per_bus():
    bus = _ExplodingBus()

    OnboardingEventPublisher(bus)
    OnboardingEventPublisher(bus)
    ensure_case_bridge_subscribed(bus)

    assert bus.subscriptions == [CASE_BRIDGE_GROUP]


async def test_a_bus_that_refuses_the_subscription_still_yields_a_publisher():
    bus = _UnsubscribableBus()

    publisher = OnboardingEventPublisher(bus)
    await publisher.exporter_lifecycle_changed(
        customer_id=uuid.uuid4(), from_status=None, to_status="LEAD", actor_id=None
    )

    assert bus.attempts == 1
