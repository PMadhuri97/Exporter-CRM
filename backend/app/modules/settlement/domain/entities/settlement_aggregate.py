from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AnerModel, AppendOnlyModel

SCHEMA = "settlement"
LEDGER_SCHEMA = "ledger"

ASSET_CODE_LEN = 16


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(py_enum, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e])


# ── Enums ─────────────────────────────────────────────────────────────────────

class SettlementStatus(str, enum.Enum):

    INITIATED = "initiated"
    FUNDED = "funded"
    SCREENED = "screened"
    AUTHORIZED = "authorized"
    ROUTED = "routed"
    SETTLING = "settling"
    SETTLED = "settled"
    RECONCILED = "reconciled"
    FAILED_PENDING_COMPENSATION = "failed_pending_compensation"
    COMPENSATED = "compensated"
    FAILED = "failed"
    RECALLED = "recalled"
    RETURNED = "returned"
    RECALL_FAILED = "recall_failed"


class SettlementLegType(str, enum.Enum):

    FIAT = "fiat"
    CRYPTO = "crypto"


class SettlementLegStatus(str, enum.Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SETTLED = "settled"
    FAILED = "failed"
    COMPENSATED = "compensated"


class SettlementLegFinalityType(str, enum.Enum):

    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class LegSignalStatus(str, enum.Enum):
    """Delivery state of a queued settlement-workflow signal. `pending` retries
    until it lands — a settled leg's signal has no acceptable "gave up" state."""

    PENDING = "pending"
    DELIVERED = "delivered"


# ── Tables ────────────────────────────────────────────────────────────────────
class SettlementLeg(AnerModel):

    __tablename__ = "settlement_leg"
    __table_args__ = (
        CheckConstraint("leg_sequence > 0", name="ck_settlement_leg_sequence_positive"),
        CheckConstraint("amount > 0", name="ck_settlement_leg_amount_positive"),
        # One leg per (settlement, sequence). Added by g6b7c8d9e0f1; declared here
        # so autogenerate does not read the constraint as drift.
        UniqueConstraint(
            "settlement_id",
            "leg_sequence",
            name="uq_settlement_leg_settlement_id_leg_sequence",
        ),
        Index("ix_settlement_leg_settlement", "settlement_id"),
        Index("ix_settlement_leg_sequence", "leg_sequence"),
        Index("ix_settlement_leg_status", "status"),
        Index("ix_settlement_leg_rail_reference", "rail_reference"),
        {"schema": SCHEMA},
    )

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.settlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    leg_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    leg_type: Mapped[SettlementLegType] = mapped_column(
        _enum(SettlementLegType, "settlement_leg_type_enum"), nullable=False
    )
    # Rail identifier from Epic 2.4 routing. NULL until the Routed transition assigns one.
    rail_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[SettlementLegStatus] = mapped_column(
        _enum(SettlementLegStatus, "settlement_leg_status_enum"),
        nullable=False,
        default=SettlementLegStatus.PENDING,
    )
    # Rule 1: integer minor units, scaled by the currency registry's precision.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_code: Mapped[str] = mapped_column(String(ASSET_CODE_LEN), nullable=False)
    # Reference from the rail on submission (blockchain tx id, bank reference, ...).
    rail_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finality_type: Mapped[SettlementLegFinalityType] = mapped_column(
        _enum(SettlementLegFinalityType, "settlement_leg_finality_type_enum"), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to Epic 2.1's compensating ledger transaction, once the saga reverses this leg.
    compensation_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{LEDGER_SCHEMA}.ledger_transaction.id", ondelete="RESTRICT"),
        nullable=True,
    )

    settlement: Mapped[Settlement] = relationship(back_populates="legs")


class SettlementEvent(AppendOnlyModel):
    __tablename__ = "settlement_event"
    __table_args__ = (
        Index("ix_settlement_event_settlement", "settlement_id"),
        Index("ix_settlement_event_created_at", "created_at"),
        Index("ix_settlement_event_type", "event_type"),
        {"schema": SCHEMA},
    )

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.settlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    # Foundation.md types both of these as String, not the SettlementStatus enum — from_status is
    # NULL for the creation event, which has no prior status to record.
    from_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    produced_by: Mapped[str] = mapped_column(String(255), nullable=False)

    settlement: Mapped[Settlement] = relationship(back_populates="events")


class Settlement(AnerModel):
    __tablename__ = "settlement"
    __table_args__ = (
        CheckConstraint("send_amount > 0", name="ck_settlement_send_amount_positive"),
        CheckConstraint(
            "receive_amount IS NULL OR receive_amount > 0",
            name="ck_settlement_receive_amount_positive",
        ),
        CheckConstraint(
            "edd_required = (edd_trigger_rule IS NOT NULL)",
            name="ck_settlement_edd_rule_consistent",
        ),
        Index("ix_settlement_correlation_id", "correlation_id"),
        Index("ix_settlement_status", "status"),
        Index("ix_settlement_sender_account", "sender_account_id"),
        Index("ix_settlement_beneficiary_account", "beneficiary_account_id"),
        Index("ix_settlement_created_at", "created_at"),
        # Explicit: bare unique=True auto-names it settlement_idempotency_key_key,
        # but the database has uq_settlement_idempotency_key.
        UniqueConstraint("idempotency_key", name="uq_settlement_idempotency_key"),
        {"schema": SCHEMA},
    )

    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[SettlementStatus] = mapped_column(
        _enum(SettlementStatus, "settlement_status_enum"),
        nullable=False,
        default=SettlementStatus.INITIATED,
    )

    # ── Parties ────────────────────────────────────────────────────────────────
    sender_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{LEDGER_SCHEMA}.ledger_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    beneficiary_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{LEDGER_SCHEMA}.ledger_account.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ── Amounts ────────────────────────────────────────────────────────────────
    # Rule 1: integer minor units, scaled by the currency registry's precision.
    send_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    send_asset_code: Mapped[str] = mapped_column(String(ASSET_CODE_LEN), nullable=False)
    # Populated after FX (Epic 2.7) — NULL until the rate is applied.
    receive_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    receive_asset_code: Mapped[str] = mapped_column(String(ASSET_CODE_LEN), nullable=False)

    # ── FX ─────────────────────────────────────────────────────────────────────
    # Fixed-precision integer rate, populated and locked by Epic 2.7. A ratio, not money — like
    # the ledger's own `rate`/`spread` columns, Rule 1 (integer minor units) deliberately excludes
    # rates.
    fx_rate: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fx_rate_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fx_rate_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Routing ────────────────────────────────────────────────────────────────
    route: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Compliance (Epic 2.2 Story S0) ─────────────────────────────────────────
    purpose_code: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # corridor_id and country_jurisdiction are compliance-evaluation inputs
    # (the corridor the settlement runs on, and the jurisdiction derived from
    # the beneficiary's country of domicile) but are not persisted as columns
    # yet — that lands in a follow-up story once their storage shape is settled.
    edd_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    edd_trigger_rule: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment=(
            "The rule that triggered EDD. Populated exactly when edd_required is true "
            "(ck_settlement_edd_rule_consistent) and immutable once set "
            "(settlement_immutable_fields). Setting it post-insert therefore requires "
            "flipping edd_required in the same UPDATE."
        ),
    )
    edd_trigger_jurisdiction: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment=(
            "The authority (framework, country, or corridor) whose sector "
            "classification fed the compliance evaluation, as returned by "
            "ComplianceActionSet.resolving_jurisdiction. Immutable once set "
            "(settlement_immutable_fields) — not required to be non-null exactly "
            "when edd_required is true, since a classification can resolve "
            "without any rule firing."
        ),
    )
    screening_reference: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ── Orchestration ──────────────────────────────────────────────────────────
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Concurrency ────────────────────────────────────────────────────────────
    # Optimistic lock counter — incremented on every successful state transition.
    # The transition enforcer uses WHERE version = :expected to detect concurrent
    # modification; the loser retries or fails cleanly.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Identity of the calling service. Immutable — mirrors `ledger_transaction.created_by`.
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'metadata' is reserved on SQLAlchemy declarative classes, so the attribute is renamed while
    # the DB column keeps the name the data model specifies (matches the ledger's convention).
    settlement_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    legs: Mapped[list[SettlementLeg]] = relationship(
        SettlementLeg,
        back_populates="settlement",
        order_by=SettlementLeg.leg_sequence,
        lazy="selectin",
    )
    events: Mapped[list[SettlementEvent]] = relationship(
        SettlementEvent,
        back_populates="settlement",
        order_by=SettlementEvent.created_at,
        lazy="selectin",
    )


class LegSignalOutbox(AnerModel):
    """Transactional outbox for signals the settlement state machine must receive.

    A ``leg_settled`` signal is written here in the *same transaction* that stores
    the ``rails.leg_status_update_record``, so "a settled status produces the
    signal" is a guarantee rather than a best-effort call that a transient
    Temporal outage can drop. ``LegSignalRelay`` delivers ``pending`` rows to the
    running workflow and retries until each lands; the ``leg_settled`` handler is
    idempotent, so a late delivery to an already-advanced workflow is harmless.

    Mutable (the relay updates ``status`` / ``attempts``), so no immutability
    trigger — this is operational state, like ``rails.circuit_breaker_state``.
    """

    __tablename__ = "leg_signal_outbox"
    __table_args__ = (
        # One signal of a given kind per leg. Both the webhook path and the poll
        # path enqueue on SETTLED; ON CONFLICT DO NOTHING makes the second a no-op.
        UniqueConstraint(
            "leg_id", "signal_name", name="uq_leg_signal_outbox_leg_signal"
        ),
        # The relay's hot query: oldest pending first.
        Index(
            "ix_leg_signal_outbox_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_leg_signal_outbox_settlement", "settlement_id"),
        {"schema": SCHEMA},
    )

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.settlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    leg_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.settlement_leg.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: Resolved when the row is enqueued, so the relay never has to re-derive it.
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    signal_name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The signal's dataclass fields as JSON — e.g. leg_sequence / rail_reference / leg_id.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[LegSignalStatus] = mapped_column(
        _enum(LegSignalStatus, "leg_signal_status_enum"),
        nullable=False,
        default=LegSignalStatus.PENDING,
        server_default=LegSignalStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
