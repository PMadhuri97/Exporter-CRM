"""
Event taxonomy and the canonical event envelope.

Topic architecture and partition-key rules are defined in
architecture-temporal-and-kafka.md. Partition key = transaction_id on all
settlement topics so every event for a transaction lands on one partition in
order (required for correct audit replay). Ledger events key on account_id.
Rail webhook events key on rail_reference, so every status update for one
leg-submission is ordered on a single partition.
"""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Topic(str, enum.Enum):
    """Kafka topics. Retention is configured at the cluster, not here."""

    TRANSACTION = "aner.transaction.events"
    COMPLIANCE = "aner.compliance.events"
    SETTLEMENT = "aner.settlement.events"
    LEDGER = "aner.ledger.events"
    AUDIT = "aner.audit.events"          # 7-year retention — canonical audit log
    NOTIFICATION = "aner.notification.events"
    CUSTOMER = "aner.customer.events"    # customer onboarding / KYC lifecycle
    WEBHOOK_RECEIVED = "aner.rail.webhook_received"  # inbound rail webhooks, queued for async processing
    RAILS = "aner.rail.circuit_breaker"  # circuit breaker state-change events


ALL_TOPICS: tuple[Topic, ...] = tuple(Topic)


class EventType(str, enum.Enum):
    """
    The nine lifecycle events broadcast in this phase.

    These are coarse milestones — distinct from the fine-grained per-step audit
    records that settlement activities still write synchronously.
    """

    PAYMENT_CREATED = "transaction.initiated"
    COMPLIANCE_APPROVED = "compliance.approved"
    LEDGER_UPDATED = "ledger.updated"
    SETTLEMENT_STARTED = "settlement.started"
    SETTLEMENT_COMPLETED = "settlement.completed"
    SETTLEMENT_FAILED = "settlement.failed"
    COMPENSATION_STARTED = "compensation.started"
    COMPENSATION_COMPLETED = "compensation.completed"

    # ── Customer onboarding lifecycle (parallel to the settlement events) ──────
    CUSTOMER_REGISTERED = "customer.registered"
    CUSTOMER_VERIFICATION_UPDATED = "customer.verification.updated"

    # ── Exporter CRM handovers (docs/contracts/event-envelope.md) ─────────────
    # The two things the CRM announces to other teams. The CRM records
    # outcomes; the teams that receive these own the decisions that follow.
    #
    # `company.became_customer` fires when a company is a Prospect and its
    # background check is CLEAR, whichever happens second (assumption A1). The
    # customers team builds the receiver later (decision 10), so nothing
    # consumes it yet — which is expected, and why the CRM only announces.
    #
    # `deal.handed_over` fires when a deal passes to the lending team, which is
    # permitted only for a CUSTOMER whose check is CLEAR (assumption A5).
    COMPANY_BECAME_CUSTOMER = "company.became_customer"
    DEAL_HANDED_OVER = "deal.handed_over"

    # ── Account lifecycle events ───────────────────────────────────────────────
    ACCOUNT_SUSPENDED = "account.suspended"
    ACCOUNT_CLOSED = "account.closed"

    # ── Settlement state machine ──────────────────────────────────────────────
    SETTLEMENT_TRANSITION = "settlement.transition"

    # ── Reconciliation ────────────────────────────────────────────────────────
    RECONCILIATION_TRIGGERED = "reconciliation.triggered"

    # ── Recall and return ─────────────────────────────────────────────────────
    # The three outcomes on the path back: the rail has been asked to return a
    # payment, the money has come back, or the rail refused. Consumers that
    # notify a customer or open a case subscribe to these; the settlement module
    # knows nothing about either.
    SETTLEMENT_RECALLED = "settlement.recalled"
    SETTLEMENT_RETURNED = "settlement.returned"
    SETTLEMENT_RECALL_FAILED = "settlement.recall_failed"

    # ── Rail polling ──────────────────────────────────────────────────────────
    # A submitted leg has passed its rail's declared settlement_speed_minutes_p99
    # without settling or failing. Two audiences, one event: the SRE on-call,
    # who needs to know a rail is not delivering, and the Case
    # Management Console, which opens the manual investigation. A case row
    # cannot be created directly — compliance_cases keys on
    # payments.transactions and a settlement has no row there — so this event
    # carries everything a case needs, the same resolution
    # `settlement.recall_failed` uses.
    RAIL_LEG_STUCK = "rail.leg_stuck"

    # ── Rail webhooks (Epic 2.4 / S5) ────────────────────────────────────────
    # A signature-verified inbound rail webhook, queued by the receiver for the
    # webhook processor. The payload carries the raw body (base64) + headers so
    # the processor can re-run the adapter's handle_webhook.
    RAIL_WEBHOOK_RECEIVED = "rail.webhook.received"

    # ── Circuit breaker state transitions (Epic 2.4 / S4T2) ──────────────────
    CIRCUIT_BREAKER_OPENED = "rail.circuit_breaker.opened"
    CIRCUIT_BREAKER_PROBING = "rail.circuit_breaker.probing"
    CIRCUIT_BREAKER_CLOSED = "rail.circuit_breaker.closed"


# The nine settlement-lifecycle events — the original core taxonomy. Kept as an
# explicit set so tests can assert on the settlement flow independently of any
# additional (e.g. onboarding) event types.
SETTLEMENT_LIFECYCLE_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.PAYMENT_CREATED,
        EventType.COMPLIANCE_APPROVED,
        EventType.LEDGER_UPDATED,
        EventType.SETTLEMENT_STARTED,
        EventType.SETTLEMENT_COMPLETED,
        EventType.SETTLEMENT_FAILED,
        EventType.COMPENSATION_STARTED,
        EventType.COMPENSATION_COMPLETED,
        EventType.RECONCILIATION_TRIGGERED,
    }
)


# Event → topic routing. Each event is published to exactly one topic.
TOPIC_FOR_EVENT: dict[EventType, Topic] = {
    EventType.PAYMENT_CREATED: Topic.TRANSACTION,
    EventType.COMPLIANCE_APPROVED: Topic.COMPLIANCE,
    EventType.LEDGER_UPDATED: Topic.LEDGER,
    EventType.SETTLEMENT_STARTED: Topic.SETTLEMENT,
    EventType.SETTLEMENT_COMPLETED: Topic.SETTLEMENT,
    EventType.SETTLEMENT_FAILED: Topic.SETTLEMENT,
    EventType.COMPENSATION_STARTED: Topic.SETTLEMENT,
    EventType.COMPENSATION_COMPLETED: Topic.SETTLEMENT,
    EventType.CUSTOMER_REGISTERED: Topic.CUSTOMER,
    EventType.CUSTOMER_VERIFICATION_UPDATED: Topic.CUSTOMER,
    # Both CRM handovers go on the existing customer topic rather than a new
    # one. It is already partitioned by customer id, which is exactly the
    # partition key a CRM event uses, so one company's events stay ordered
    # together — including a deal handover, which is an event about that
    # company's deal. A new Topic member would also be picked up by everything
    # subscribing to ALL_TOPICS (the idempotency stream processor and the
    # platform consumer registry), which would mean provisioning a Kafka topic
    # to carry two event types nothing consumes yet.
    EventType.COMPANY_BECAME_CUSTOMER: Topic.CUSTOMER,
    EventType.DEAL_HANDED_OVER: Topic.CUSTOMER,
    EventType.ACCOUNT_SUSPENDED: Topic.LEDGER,
    EventType.ACCOUNT_CLOSED: Topic.LEDGER,
    EventType.SETTLEMENT_TRANSITION: Topic.SETTLEMENT,
    EventType.RECONCILIATION_TRIGGERED: Topic.SETTLEMENT,
    EventType.SETTLEMENT_RECALLED: Topic.SETTLEMENT,
    EventType.SETTLEMENT_RETURNED: Topic.SETTLEMENT,
    EventType.SETTLEMENT_RECALL_FAILED: Topic.SETTLEMENT,
    EventType.RAIL_LEG_STUCK: Topic.SETTLEMENT,
    EventType.RAIL_WEBHOOK_RECEIVED: Topic.WEBHOOK_RECEIVED,
    EventType.CIRCUIT_BREAKER_OPENED: Topic.RAILS,
    EventType.CIRCUIT_BREAKER_PROBING: Topic.RAILS,
    EventType.CIRCUIT_BREAKER_CLOSED: Topic.RAILS,
}


class EventEnvelope(BaseModel):
    """
    The wire format for every event. JSON-serialised as the Kafka record value;
    `partition_key` is the Kafka record key.

    `event_id` is the deduplication key — every consumer checks it against the
    processed_events store before acting (Kafka delivers at-least-once).

    `actor_id` and `deal_id` exist for the Exporter CRM's handover events
    (`company.became_customer`, `deal.handed_over`), whose contract puts the
    company, the deal and the actor on the envelope rather than burying them in
    `payload` where nothing would keep producers consistent. Both are optional
    and default to `None`; nothing populates them yet — the CRM event helper
    (L1-12) is the first writer. See `docs/contracts/event-envelope.md`.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    topic: Topic
    partition_key: str
    transaction_id: str | None = None
    correlation_id: str | None = None

    #: Who caused the change this event announces, when a person did.
    #:
    #: `correlation_id` traces a request; this answers "who". `None` means the
    #: platform acted on its own behalf — the same meaning `actor_id` carries on
    #: `case_state_transition` and `exporter_lifecycle_history`, so the answer
    #: does not change shape between the history row and the announcement of it.
    #:
    #: Optional with a `None` default so this is additive: every existing
    #: producer keeps working unchanged, an old message still parses, and a
    #: consumer that does not read it is unaffected.
    actor_id: str | None = None

    #: The deal a CRM event is about, when it is about one.
    #:
    #: The company is `partition_key` — customer events are already keyed by
    #: customer id so that one company's events stay ordered on one partition.
    #: A deal has no such ordering requirement of its own, so it is a field
    #: rather than the key.
    deal_id: str | None = None

    occurred_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    producer: str = "aner-settlement-platform"
    payload: dict = Field(default_factory=dict)

    def to_kafka_value(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_kafka_value(cls, raw: bytes) -> EventEnvelope:
        return cls.model_validate_json(raw.decode("utf-8"))


def build_envelope(
    event_type: EventType,
    *,
    partition_key: str,
    transaction_id: str | None = None,
    correlation_id: str | None = None,
    actor_id: str | None = None,
    deal_id: str | None = None,
    payload: dict | None = None,
) -> EventEnvelope:
    """Construct an envelope with the topic resolved from the event type.

    `actor_id` and `deal_id` are keyword-only with `None` defaults, so every
    existing call site is unchanged.
    """
    return EventEnvelope(
        event_type=event_type,
        topic=TOPIC_FOR_EVENT[event_type],
        partition_key=partition_key,
        transaction_id=transaction_id,
        correlation_id=correlation_id,
        actor_id=actor_id,
        deal_id=deal_id,
        payload=payload or {},
    )
