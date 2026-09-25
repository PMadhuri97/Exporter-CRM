"""The two CRM handover events, and the rule that they cannot hurt the caller.

`company.became_customer` and `deal.handed_over` are what the Exporter CRM
announces to other teams. Nothing fires them yet — the transitions that should
belong to Developer 2 and Developer 3 — so these tests exercise the helper
directly. That is the point: the envelope and the payload are settled here,
before two people build against a guess.

No database. `InMemoryEventBus` is injected per test, which is what
`set_event_bus` exists for.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.platform.messaging.ports import InMemoryEventBus
from app.platform.messaging.schemas import (
    TOPIC_FOR_EVENT,
    EventEnvelope,
    EventType,
    Topic,
    build_envelope,
)

# No module-level `pytest.mark.asyncio`: `asyncio_mode = "auto"` in
# pyproject.toml already marks the async tests, and a blanket mark would also
# land on the synchronous envelope tests below — which pytest warns about,
# correctly.

COMPANY = uuid.uuid4()
DEAL = uuid.uuid4()
DECISION = uuid.uuid4()


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def publisher(bus: InMemoryEventBus) -> OnboardingEventPublisher:
    """The bus is passed in rather than set globally, so these tests cannot
    leak a bus into any other test in the session."""
    return OnboardingEventPublisher(bus=bus)


# ── The envelope (U2) ────────────────────────────────────────────────────────


def test_the_envelope_carries_an_actor_and_a_deal():
    """Decision U2: both are fields on the envelope, not payload keys.

    A field with a type is what makes a producer that forgets one fail; a
    documented convention about `payload` would fail at no point.
    """
    envelope = build_envelope(
        EventType.COMPANY_BECAME_CUSTOMER,
        partition_key=str(COMPANY),
        actor_id="user-1",
        deal_id=str(DEAL),
    )
    assert envelope.actor_id == "user-1"
    assert envelope.deal_id == str(DEAL)


def test_both_default_to_none_so_existing_producers_are_unaffected():
    envelope = build_envelope(
        EventType.CUSTOMER_REGISTERED, partition_key=str(COMPANY)
    )
    assert envelope.actor_id is None
    assert envelope.deal_id is None


def test_an_envelope_written_before_the_new_fields_still_parses():
    """Wire compatibility in the direction that matters: a message produced by
    an older build, sitting on a topic, must not break a consumer on this one."""
    old_wire = (
        '{"event_id":"e1","event_type":"customer.registered",'
        '"topic":"aner.customer.events","partition_key":"c1",'
        '"occurred_at":"2026-01-01T00:00:00+00:00","payload":{}}'
    )
    envelope = EventEnvelope.from_kafka_value(old_wire.encode())
    assert envelope.event_id == "e1"
    assert envelope.actor_id is None
    assert envelope.deal_id is None


def test_the_new_fields_survive_a_round_trip_through_the_wire():
    original = build_envelope(
        EventType.DEAL_HANDED_OVER,
        partition_key=str(COMPANY),
        actor_id="user-9",
        deal_id=str(DEAL),
    )
    restored = EventEnvelope.from_kafka_value(original.to_kafka_value())
    assert (restored.actor_id, restored.deal_id) == ("user-9", str(DEAL))


def test_both_crm_events_route_to_the_customer_topic():
    """Not a new topic: everything subscribing to `ALL_TOPICS` would have to
    provision one to carry two event types nothing consumes yet."""
    assert TOPIC_FOR_EVENT[EventType.COMPANY_BECAME_CUSTOMER] is Topic.CUSTOMER
    assert TOPIC_FOR_EVENT[EventType.DEAL_HANDED_OVER] is Topic.CUSTOMER


def test_every_event_type_has_a_topic():
    """Adding a member without routing it would fail at publish time, inside a
    `try/except` that swallows the error — so the event would vanish silently."""
    assert [e for e in EventType if e not in TOPIC_FOR_EVENT] == []


# ── company.became_customer ──────────────────────────────────────────────────


async def test_company_became_customer_publishes_the_contracted_shape(
    publisher: OnboardingEventPublisher, bus: InMemoryEventBus
):
    await publisher.company_became_customer(
        company_id=COMPANY,
        name="Acme Exports Pvt Ltd",
        country="IN",
        pan="ABCDE1234F",
        gstins=["27ABCDE1234F1Z5"],
        risk_rating="LOW",
        clearing_decision_id=DECISION,
        actor_id="compliance-3",
    )

    (envelope,) = bus.events_of_type(EventType.COMPANY_BECAME_CUSTOMER)
    assert envelope.topic is Topic.CUSTOMER
    # The company is the partition key, so one company's events stay ordered.
    assert envelope.partition_key == str(COMPANY)
    assert envelope.actor_id == "compliance-3"
    assert envelope.deal_id is None
    assert envelope.payload == {
        "company_id": str(COMPANY),
        "name": "Acme Exports Pvt Ltd",
        "country": "IN",
        "pan": "ABCDE1234F",
        "gstins": ["27ABCDE1234F1Z5"],
        "risk_rating": "LOW",
        "clearing_decision_id": str(DECISION),
    }


async def test_company_became_customer_sends_the_pan_unmasked(
    publisher: OnboardingEventPublisher, bus: InMemoryEventBus
):
    """Deliberate, and worth pinning down so nobody "fixes" it later.

    This is a system-to-system announcement to the customers team, which needs
    the identifier to match the company against its own records. The masking
    rules govern what a *viewer* sees in an API response, not what one internal
    service tells another.
    """
    await publisher.company_became_customer(
        company_id=COMPANY, name="N", country="IN", pan="ABCDE1234F",
        gstins=[], risk_rating="LOW", clearing_decision_id=DECISION,
    )

    (envelope,) = bus.events_of_type(EventType.COMPANY_BECAME_CUSTOMER)
    assert envelope.payload["pan"] == "ABCDE1234F"
    assert "•" not in envelope.payload["pan"]


async def test_company_became_customer_tolerates_no_actor(
    publisher: OnboardingEventPublisher, bus: InMemoryEventBus
):
    """`None` means the platform itself acted — the same meaning `actor_id`
    carries on a history row, so the answer does not change shape between the
    record and the announcement of it."""
    await publisher.company_became_customer(
        company_id=COMPANY, name="N", country="IN", pan=None,
        gstins=[], risk_rating="MEDIUM", clearing_decision_id=DECISION,
    )
    (envelope,) = bus.events_of_type(EventType.COMPANY_BECAME_CUSTOMER)
    assert envelope.actor_id is None
    assert envelope.payload["pan"] is None


# ── deal.handed_over ─────────────────────────────────────────────────────────


async def test_deal_handed_over_publishes_the_contracted_shape(
    publisher: OnboardingEventPublisher, bus: InMemoryEventBus
):
    buyer = {"name": "Gulf Trading LLC", "country": "AE", "identifiers": {"trn": "100..."}}

    await publisher.deal_handed_over(
        deal_id=DEAL,
        company_id=COMPANY,
        buyer=buyer,
        document_ids=["doc-1", "doc-2"],
        actor_id="ops-2",
    )

    (envelope,) = bus.events_of_type(EventType.DEAL_HANDED_OVER)
    # Still keyed by the company: a deal event is an event about that company.
    assert envelope.partition_key == str(COMPANY)
    assert envelope.deal_id == str(DEAL)
    assert envelope.actor_id == "ops-2"
    assert envelope.payload["buyer"] == buyer
    assert envelope.payload["document_ids"] == ["doc-1", "doc-2"]


async def test_the_document_list_is_a_snapshot_not_a_live_reference(
    publisher: OnboardingEventPublisher, bus: InMemoryEventBus
):
    """A later upload must not change what the lending team was handed."""
    documents = ["doc-1"]
    await publisher.deal_handed_over(
        deal_id=DEAL, company_id=COMPANY, buyer={}, document_ids=documents,
    )

    documents.append("doc-added-afterwards")

    (envelope,) = bus.events_of_type(EventType.DEAL_HANDED_OVER)
    assert envelope.payload["document_ids"] == ["doc-1"]


# ── Failure isolation ────────────────────────────────────────────────────────


class _BrokenBus(InMemoryEventBus):
    """A bus whose publish always fails, the way a broker outage would."""

    async def publish(self, envelope: EventEnvelope) -> None:
        raise RuntimeError("broker unreachable")


async def test_a_publish_failure_never_reaches_the_caller():
    """The rule from the contract: the history row is the source of truth and
    the announcement is best effort.

    If this raised, a broker outage would roll back a company that genuinely
    became a customer — losing the change to protect the notification of it.
    """
    publisher = OnboardingEventPublisher(bus=_BrokenBus())

    await publisher.company_became_customer(
        company_id=COMPANY, name="N", country="IN", pan=None,
        gstins=[], risk_rating="LOW", clearing_decision_id=DECISION,
    )
    await publisher.deal_handed_over(
        deal_id=DEAL, company_id=COMPANY, buyer={}, document_ids=[],
    )
    # Reaching here is the assertion.


async def test_one_failing_consumer_does_not_stop_another(bus: InMemoryEventBus):
    """`InMemoryEventBus` isolates handlers. A CRM event with two subscribers —
    the customers team and, later, anything else — must not lose the second
    because the first threw."""
    seen: list[str] = []

    async def broken(_envelope: EventEnvelope) -> None:
        raise RuntimeError("consumer bug")

    async def working(envelope: EventEnvelope) -> None:
        seen.append(envelope.event_type.value)

    bus.subscribe("broken-group", [Topic.CUSTOMER], broken)
    bus.subscribe("working-group", [Topic.CUSTOMER], working)

    await OnboardingEventPublisher(bus=bus).company_became_customer(
        company_id=COMPANY, name="N", country="IN", pan=None,
        gstins=[], risk_rating="LOW", clearing_decision_id=DECISION,
    )

    assert seen == ["company.became_customer"]
