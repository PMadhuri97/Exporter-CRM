"""
Rails domain entities — Rail Abstraction Layer (Epic 2.4).

Five tables, all inside the `rails` schema:

  rails.rail_registration          — registered rail adapters and their capabilities.
  rails.leg_submission_record      — every leg submission attempt, plus its poll cursor.
  rails.leg_status_update_record   — immutable record of every status update from a rail.
  rails.routing_decision_record    — immutable record of every routing decision.
  rails.circuit_breaker_state      — current circuit breaker state per rail. Upsert only.

Immutability rules enforced at the DB level (see rails_0001_baseline.py:399-427
for the triggers themselves — they are narrower than "append-only" suggests):
  - leg_status_update_record: public.prevent_mutation() blocks ALL UPDATE and
    DELETE. This is the only rails table under the blanket rule.
  - leg_submission_record: rails.assert_leg_submission_record_immutable_fields()
    freezes submission_request, submission_response and submitted_at. What was
    sent, what came back and when cannot be rewritten; other columns are
    mutable, which is what lets the polling manager keep its polling cursor on the row.
  - routing_decision_record: rails.assert_routing_decision_record_immutable_fields()
    freezes decided_at, evaluated_rails, selected_rail_id and routing_factors.
  - rail_registration.registered_at and rail_registration.rail_id:
    rails.assert_rail_registration_immutable_fields() blocks changes once set.
  - circuit_breaker_state: fully mutable — upserted on every state transition.

Enum label convention: values_callable is used so SQLAlchemy persists .value
(lowercase) — matching the settlement module's convention, not the legacy
leg_type_enum / leg_status_enum which persist .name (uppercase).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel, Base, UUIDPrimaryKeyMixin
from app.shared.enums.rails import (  # noqa: F401
    ConfirmationMechanism,
    FinalityType,
    RailLegStatus,
    RailStatus,
    RailType,
    SubmissionStatus,
)

SCHEMA = "rails"
SETTLEMENT_SCHEMA = "settlement"


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Create a schema-qualified SQLAlchemy Enum type persisting lowercase .value."""
    return Enum(
        py_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda e: [m.value for m in e],
    )


# ── Enums ─────────────────────────────────────────────────────────────────────

# RailStatus, RailType, FinalityType, ConfirmationMechanism, SubmissionStatus,
# RailLegStatus live in app.shared.enums.rails (imported above) — see that
# module's docstring for why. CircuitBreakerStateEnum has no such constraint
# and stays here, module-owned.
class CircuitBreakerStateEnum(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ── Tables ────────────────────────────────────────────────────────────────────

class RailRegistration(UUIDPrimaryKeyMixin, Base):
    """Registry of all rail adapters on the platform.

    Populated at service startup from registered rail adapters. One record per
    rail. `capability_declaration` holds the full structured capability document
    as defined in Epic 2.4 §Rail Capability Declaration.

    Uses registered_at and last_updated_at as the spec defines — not the
    AnerModel created_at/updated_at pair.
    """

    __tablename__ = "rail_registration"
    __table_args__ = (
        UniqueConstraint("rail_id", name="uq_rail_registration_rail_id"),
        CheckConstraint(
            "status IN ('active', 'degraded', 'suspended', 'decommissioned')",
            name="ck_rail_registration_status",
        ),
        CheckConstraint(
            "octet_length(capability_declaration::text) <= 65536",
            name="ck_rail_registration_cap_decl_size",
        ),
        Index("ix_rail_registration_status", "status"),
        {"schema": SCHEMA},
    )

    # Stable unique identifier. Examples: nium_usd_inr, circle_usdc_cctp.
    # Immutable once registered — trigger guards this field.
    rail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The full capability declaration as defined in Epic 2.4.
    # Contains all 20 capability fields (rail_name, rail_type, supported assets,
    # settlement speed, confirmation mechanism, fee structure, etc.).
    capability_declaration: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The internal class name of the rail adapter implementation.
    adapter_class: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[RailStatus] = mapped_column(
        _enum(RailStatus, "rails_rail_status_enum"),
        nullable=False,
        server_default="active",
    )
    # Internal endpoint called by the health monitor.
    health_check_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # When this rail was registered. Immutable once set — trigger guards this.
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Updated when capability declaration or status changes.
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class LegSubmissionRecord(UUIDPrimaryKeyMixin, Base):
    """Record of every leg submission attempt. Every attempt is a new row.

    Immutable in the sense that matters and no further: the field-level trigger
    ``rails.assert_leg_submission_record_immutable_fields()`` freezes
    ``submission_request``, ``submission_response`` and ``submitted_at``, so
    what was sent, what came back and when can never be rewritten. Unlike
    ``LegStatusUpdateRecord`` this table is NOT under
    ``public.prevent_mutation()``, and never has been — see the module
    docstring. The polling cursor below depends on that distinction.

    Retries are new rows rather than edits, so at most one row per leg may be
    in the poll queue at a time; :class:`PollingManager` keeps the newest
    non-terminal attempt and clears the cursor on the ones it supersedes.
    """

    __tablename__ = "leg_submission_record"
    __table_args__ = (
        CheckConstraint(
            "octet_length(submission_request::text) <= 65536",
            name="ck_leg_submission_request_size",
        ),
        CheckConstraint(
            "submission_response IS NULL OR octet_length(submission_response::text) <= 65536",
            name="ck_leg_submission_response_size",
        ),
        Index("ix_leg_submission_leg_id", "leg_id"),
        Index("ix_leg_submission_settlement_id", "settlement_id"),
        Index("ix_leg_submission_rail_id", "rail_id"),
        Index("ix_leg_submission_idempotency_key", "idempotency_key"),
        Index("ix_leg_submission_submitted_at", "submitted_at"),
        # Poll queue. Partial because the due-poll query always carries
        # `polling_next_at IS NOT NULL`, and this table grows with every
        # submission the platform ever makes while the live queue stays small —
        # so the index is sized by the queue rather than by the history.
        Index(
            "ix_leg_submission_polling_next_at",
            "polling_next_at",
            postgresql_where=text("polling_next_at IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    # FK to Epic 2.2 settlement_leg.
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SETTLEMENT_SCHEMA}.settlement_leg.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # FK to Epic 2.2 settlement.
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SETTLEMENT_SCHEMA}.settlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The rail this submission was sent to.
    rail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The rail reference used as the idempotency key (from Epic 2.3).
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # End-to-end trace ID.
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The full leg submission request. Immutable once written.
    submission_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The full leg submission response. Immutable once written.
    submission_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Immutable once written.
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    submission_status: Mapped[SubmissionStatus] = mapped_column(
        _enum(SubmissionStatus, "rails_submission_status_enum"), nullable=False
    )
    # ── Poll queue (rails_0003_polling_schedule) ──────────────────────────────
    # When this leg is next due to be polled. NULL means "not in the poll
    # queue": a non-polling rail, a leg that has reached a terminal status, or
    # a retry row superseded by a later attempt. The queue is this column and
    # nothing else, which is what makes it survive a restart.
    polling_next_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LegStatusUpdateRecord(UUIDPrimaryKeyMixin, Base):
    """Immutable record of every status update received for a submitted leg.

    Entire table is append-only: public.prevent_mutation() rejects ALL UPDATE
    and DELETE. Every status update — webhook, poll result, or on-chain event —
    produces a new record. Existing records are never modified.
    """

    __tablename__ = "leg_status_update_record"
    __table_args__ = (
        CheckConstraint(
            "octet_length(leg_status_update::text) <= 65536",
            name="ck_leg_status_update_size",
        ),
        CheckConstraint(
            "octet_length(raw_rail_event::text) <= 65536",
            name="ck_raw_rail_event_size",
        ),
        Index("ix_leg_status_update_leg_id", "leg_id"),
        Index("ix_leg_status_update_rail_reference", "rail_reference"),
        Index("ix_leg_status_update_status", "status"),
        Index("ix_leg_status_update_received_at", "received_at"),
        # Webhook idempotency (S5): the same rail webhook delivered twice must
        # produce exactly one row. Partial — poll/on-chain writers leave
        # rail_event_id NULL and keep appending a row per observation.
        Index(
            "uq_leg_status_update_rail_ref_event",
            "rail_reference",
            "rail_event_id",
            unique=True,
            postgresql_where=text("rail_event_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    # FK to Epic 2.2 settlement_leg.
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SETTLEMENT_SCHEMA}.settlement_leg.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The rail reporting the update.
    rail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The rail's own reference for this transaction — used to correlate with the submission.
    rail_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    # The rail's own unique id for this delivery, when it carries one. With
    # rail_reference it is the webhook idempotency key (S5). NULL for poll
    # results and on-chain events.
    rail_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[RailLegStatus] = mapped_column(
        _enum(RailLegStatus, "rails_rail_leg_status_enum"), nullable=False
    )
    # When this update was received by the platform. Immutable.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # The full normalised leg status update.
    leg_status_update: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The complete raw webhook payload, polling response, or on-chain event.
    raw_rail_event: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RoutingDecisionRecord(UUIDPrimaryKeyMixin, Base):
    """Immutable record of every routing decision made by the routing engine.

    Append-only: public.prevent_mutation() rejects all UPDATE and DELETE.
    """

    __tablename__ = "routing_decision_record"
    __table_args__ = (
        Index("ix_routing_decision_settlement_id", "settlement_id"),
        Index("ix_routing_decision_leg_id", "leg_id"),
        Index("ix_routing_decision_selected_rail_id", "selected_rail_id"),
        CheckConstraint(
            "octet_length(evaluated_rails::text) <= 65536",
            name="ck_routing_decision_evaluated_rails_size",
        ),
        CheckConstraint(
            "octet_length(routing_factors::text) <= 65536",
            name="ck_routing_decision_routing_factors_size",
        ),
        Index("ix_routing_decision_decided_at", "decided_at"),
        {"schema": SCHEMA},
    )

    # FK to Epic 2.2 settlement.
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SETTLEMENT_SCHEMA}.settlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # FK to Epic 2.2 settlement_leg.
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SETTLEMENT_SCHEMA}.settlement_leg.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # All rails evaluated with their scores and inclusion/exclusion reason. Immutable.
    evaluated_rails: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The rail selected. Immutable.
    selected_rail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Plain-language explanation of why this rail was selected.
    selection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Routing factors applied: speed weight, cost weight, health status. Immutable.
    routing_factors: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Immutable.
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class BlockchainSubmission(AppendOnlyModel):
    """Claim record for one on-chain transaction — Epic 2.3 / S2T3, AC5.

    Blockchain transaction-hash identity is a **separate concern** from rail
    reference identity, and this table is what keeps them separate.

      * A rail reference identifies *our intent to submit* a leg. It lives in
        ``ledger.idempotency_record`` and is registered before the rail is
        called.
      * A transaction hash identifies *the chain's record of what happened*. It
        arrives afterwards, possibly more than once — a webhook redelivery, a
        poll overlapping a webhook, or a chain reorganisation replaying an
        event. It is not an idempotency key and deliberately does not live in
        that registry: it fails every key-format the registry validates, and
        overloading a generic platform table with a chain-specific concern
        would couple two lifecycles that expire differently.

    Append-only. ``public.prevent_mutation()`` rejects every UPDATE and DELETE,
    so a claim cannot be withdrawn once made — which is what makes "first
    observation wins" a durable guarantee rather than a convention.

    Identity is ``(rail_id, transaction_hash)``; see the unique constraint for
    why the rail scope is required.
    """

    __tablename__ = "blockchain_submission"
    __table_args__ = (
        # THE guard for AC5. A hash string is not globally unique on its own:
        # the same value can legitimately exist on two different chains, and
        # this repository has no chain/network concept to scope by (only
        # RailType.CRYPTO and ConfirmationMechanism.ON_CHAIN_EVENT exist).
        # rail_id is the narrowest real identifier available — a registered
        # rail such as circle_usdc_cctp implies exactly one chain — so it is
        # the correct scope until a network vocabulary exists.
        UniqueConstraint(
            "rail_id", "transaction_hash", name="uq_blockchain_submission_rail_tx"
        ),
        Index("ix_blockchain_submission_leg_id", "leg_id"),
        Index("ix_blockchain_submission_tx_hash", "transaction_hash"),
        {"schema": SCHEMA},
    )

    # The rail that reported this transaction. Scopes the hash.
    rail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The on-chain transaction identifier, stored verbatim. 128 leaves room for
    # a 66-character EVM hash and the longer base58 signatures other chains use.
    transaction_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # FK to Epic 2.2 settlement_leg — which leg this transaction settles.
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SETTLEMENT_SCHEMA}.settlement_leg.id", ondelete="RESTRICT"),
        nullable=False,
    )


class CircuitBreakerState(Base):
    """Current circuit breaker state for each rail.

    One record per rail. Uses upsert semantics — updated on state transitions,
    never appended. States: closed (normal), open (tripped), half_open (recovery probe).
    """

    __tablename__ = "circuit_breaker_state"
    __table_args__ = (
        CheckConstraint("failure_count >= 0", name="ck_circuit_breaker_failure_count"),
        Index("ix_circuit_breaker_state_state", "state"),
        {"schema": SCHEMA},
    )

    # One record per rail. Primary key.
    rail_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[CircuitBreakerStateEnum] = mapped_column(
        _enum(CircuitBreakerStateEnum, "rails_circuit_breaker_state_enum"),
        nullable=False,
        server_default="closed",
    )
    # Number of consecutive failures that contributed to the current state.
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # Timestamp of the most recent failure.
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When the circuit breaker last transitioned to open. Null if currently closed.
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When the half_open probe request will be allowed. Null if currently closed.
    next_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Updated on every state transition.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RailPerformanceHourly(UUIDPrimaryKeyMixin, Base):
    """Aggregated operational performance statistics per rail per hour.

    Populated by the hourly aggregation job. Used by the routing engine's
    health score calculation and by SRE / commercial rail evaluation.
    """

    __tablename__ = "rail_performance_hourly"
    __table_args__ = (
        UniqueConstraint("rail_id", "hour_bucket", name="uq_rail_performance_hourly_rail_bucket"),
        Index("ix_rail_performance_hourly_rail_id", "rail_id"),
        Index("ix_rail_performance_hourly_hour_bucket", "hour_bucket"),
        {"schema": SCHEMA},
    )

    rail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hour_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submission_success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    settlement_success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_settlement_time_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_settlement_time_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_distribution: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    timeout_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

