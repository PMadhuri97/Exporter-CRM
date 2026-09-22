"""
`case_state_transition` — the append-only ledger of case state changes.

The table exists, but **nothing writes to it until the state machine lands**. The
state machine that produces these rows owns the legal-transition table, the `409` on
an illegal move, and the rule that no other code may set `Case.state`.

Append-only: `AppendOnlyModel` plus the shared `prevent_mutation()` trigger, exactly
as `onboarding_verifications`, `ledger_entries` and `audit_events` do. A transition
that turned out to be wrong is corrected by appending its reverse, never by an UPDATE.

This is *not* a second audit store (decision D3). It is the case's own state history;
every transition **also** writes an `audit_events` row via `AuditService.record()`.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.audit import ActorType
from app.modules.onboarding.domain.entities.enums import CaseState, TransitionSource
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"
# actor_type_enum is owned by the audit module and shared, not duplicated.
AUDIT_SCHEMA = "audit"

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.case import Case


class CaseStateTransition(AppendOnlyModel):
    """
    One recorded move between two case states.

    Carries every field the state machine requires of a transition: actor, reason, timestamp
    (`created_at`), previous state, next state, source, and correlation id.
    """

    __tablename__ = "case_state_transition"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.onboarding_case.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Null on the genesis transition into DRAFT, should the state machine choose to
    # record one. Every subsequent row has both endpoints.
    previous_state: Mapped[CaseState | None] = mapped_column(
        Enum(CaseState, name="onboarding_case_state_enum", schema=SCHEMA), nullable=True
    )
    next_state: Mapped[CaseState] = mapped_column(
        Enum(CaseState, name="onboarding_case_state_enum", schema=SCHEMA), nullable=False
    )
    source: Mapped[TransitionSource] = mapped_column(
        Enum(TransitionSource, name="onboarding_transition_source_enum", schema=SCHEMA), nullable=False
    )

    # Null actor_id means the platform itself acted (§4.11).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type_enum", schema=AUDIT_SCHEMA), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    case: Mapped[Case] = relationship(back_populates="transitions")

    __table_args__ = (
        Index("ix_case_state_transition_case_created", "case_id", "created_at"),
        Index("ix_case_state_transition_case_id", "case_id"),
        Index("ix_case_state_transition_correlation_id", "correlation_id"),
        {"schema": SCHEMA},
    )
