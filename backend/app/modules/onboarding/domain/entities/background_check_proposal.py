"""``BackgroundCheckProposal`` and ``BackgroundCheckProposalResolution`` — maker-checker.

A background-check move that needs a second person — ``IN_REVIEW → CLEAR``,
``IN_REVIEW → FLAGGED``, ``FLAGGED → ON_HOLD`` — is recorded first as a
**proposal**: what the proposer decided, on which inputs (the SHA-256 fingerprint of
the evidence selection), in which cycle, under which Clear rules. The gauge does not
move. A different COMPLIANCE or ADMIN user then **approves** it — which writes the
decision, with ``decided_by`` the proposer and ``approved_by`` the approver — or
**rejects** it with a reason; or the proposer **withdraws** it. Each of those is one
**resolution** row; a proposal with none is *open* ("awaiting approval").

Both are **append-only** at both layers — ``AppendOnlyRepository`` exposes no update
and no delete, and ``public.prevent_mutation()`` refuses both at the database
(``trg_background_check_proposal_append_only``,
``trg_background_check_proposal_resolution_append_only``, migration
``onboarding_0026_maker_checker``).

Provenance
----------
``created_by`` / ``created_at`` / ``source`` / ``source_ref`` on both. On a proposal,
``created_by`` **is the proposer** and ``created_at`` when it was proposed; on a
resolution, the resolver and when. The API names them ``proposed_by`` /
``proposed_at`` and ``resolved_by`` / ``resolved_at``.

The constraints are declared here as well as in the migration so the model states the
invariants the database enforces; the migration is what creates them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"

#: The moves that need a second approver (decided 1 October 2026). Not
#: `MORE_INFO`, the start, the answer to a request, a reassessment or a reopen.
APPROVAL_MOVES: frozenset[tuple[BackgroundCheckState, BackgroundCheckState]] = frozenset(
    {
        (BackgroundCheckState.IN_REVIEW, BackgroundCheckState.CLEAR),
        (BackgroundCheckState.IN_REVIEW, BackgroundCheckState.FLAGGED),
        (BackgroundCheckState.FLAGGED, BackgroundCheckState.ON_HOLD),
    }
)

_PROPOSAL_MOVE_SQL = " OR ".join(
    f"(from_value = '{from_value.value}' AND to_value = '{to_value.value}')"
    for from_value, to_value in sorted(APPROVAL_MOVES, key=lambda m: (m[0].value, m[1].value))
)


class ProposalOutcome(str, enum.Enum):
    """How a proposal was resolved."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class BackgroundCheckProposal(AppendOnlyModel):
    """One proposed background-check move, awaiting a second person. Locked."""

    __tablename__ = "background_check_proposal"
    __table_args__ = (
        # The chain head it was based on: a decision of the same company that ended at
        # this proposal's starting value.
        ForeignKeyConstraint(
            ["based_on_decision_id", "company_id", "from_value"],
            [
                f"{SCHEMA}.background_check_decision.id",
                f"{SCHEMA}.background_check_decision.company_id",
                f"{SCHEMA}.background_check_decision.to_value",
            ],
            name="fk_background_check_proposal_based_on",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cycle_id", "company_id"],
            [f"{SCHEMA}.check_cycle.id", f"{SCHEMA}.check_cycle.company_id"],
            name="fk_background_check_proposal_cycle",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "created_by", name="uq_background_check_proposal_proposer"),
        UniqueConstraint(
            "id",
            "company_id",
            "created_by",
            "from_value",
            "to_value",
            name="uq_background_check_proposal_key",
        ),
        CheckConstraint(_PROPOSAL_MOVE_SQL, name="ck_background_check_proposal_move"),
        CheckConstraint("btrim(reason) <> ''", name="ck_background_check_proposal_reason"),
        CheckConstraint(
            "(to_value = 'CLEAR') = (risk_rating IS NOT NULL)",
            name="ck_background_check_proposal_risk",
        ),
        CheckConstraint(
            "inputs_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_background_check_proposal_fingerprint",
        ),
        CheckConstraint("evidence_count >= 0", name="ck_background_check_proposal_evidence_count"),
        CheckConstraint("btrim(created_by) <> ''", name="ck_background_check_proposal_created_by"),
        CheckConstraint("btrim(source) <> ''", name="ck_background_check_proposal_source"),
        Index(
            "ix_background_check_proposal_company_recent",
            "company_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": SCHEMA},
    )

    #: When it was proposed. Wall clock at insert, like `decided_at`.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_background_check_proposal_company_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: The chain head when it was proposed. Approval is refused once the chain has moved.
    based_on_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_value: Mapped[BackgroundCheckState] = mapped_column(
        Enum(BackgroundCheckState, name="background_check_enum", schema=SCHEMA),
        nullable=False,
    )
    to_value: Mapped[BackgroundCheckState] = mapped_column(
        Enum(BackgroundCheckState, name="background_check_enum", schema=SCHEMA),
        nullable=False,
    )
    #: Required on a proposed CLEAR, refused on any other (`ck_…_risk`).
    risk_rating: Mapped[BackgroundCheckRisk | None] = mapped_column(
        Enum(BackgroundCheckRisk, name="background_check_risk_enum", schema=SCHEMA),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: SHA-256 (hex) of the evidence selection the proposer saw
    #: (`background_check_views.inputs_fingerprint`). Approval is refused if the
    #: company's inputs now fingerprint differently.
    inputs_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: How many ids that selection held.
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: The Clear rules in force when it was proposed.
    rules_version: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The proposer, from the login session.
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class BackgroundCheckProposalResolution(AppendOnlyModel):
    """How one proposal ended: approved, rejected or withdrawn. At most one. Locked."""

    __tablename__ = "background_check_proposal_resolution"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_background_check_proposal_resolution_proposal"),
        ForeignKeyConstraint(
            ["proposal_id", "proposed_by"],
            [
                f"{SCHEMA}.background_check_proposal.id",
                f"{SCHEMA}.background_check_proposal.created_by",
            ],
            name="fk_background_check_proposal_resolution_proposal",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["decision_id", "proposal_id", "created_by"],
            [
                f"{SCHEMA}.background_check_decision.id",
                f"{SCHEMA}.background_check_decision.proposal_id",
                f"{SCHEMA}.background_check_decision.approved_by",
            ],
            name="fk_background_check_proposal_resolution_decision",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "outcome IN ('APPROVED', 'REJECTED', 'WITHDRAWN')",
            name="ck_background_check_proposal_resolution_outcome",
        ),
        CheckConstraint(
            "(outcome = 'WITHDRAWN') = (created_by = proposed_by)",
            name="ck_background_check_proposal_resolution_who",
        ),
        CheckConstraint(
            "(outcome = 'APPROVED') = (decision_id IS NOT NULL)",
            name="ck_background_check_proposal_resolution_decision",
        ),
        CheckConstraint(
            "outcome <> 'REJECTED' OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_background_check_proposal_resolution_reason",
        ),
        CheckConstraint(
            "btrim(created_by) <> ''", name="ck_background_check_proposal_resolution_created_by"
        ),
        CheckConstraint(
            "btrim(source) <> ''", name="ck_background_check_proposal_resolution_source"
        ),
        {"schema": SCHEMA},
    )

    #: When it was resolved.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: A copy of the proposal's `created_by`, pinned by the composite foreign key, so the
    #: self-approval rule is one row's CHECK.
    proposed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    #: A `ProposalOutcome` value.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Why. Required to reject; optional otherwise.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The decision an approval wrote. Set exactly when `outcome = APPROVED`.
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: The resolver, from the login session.
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = [
    "APPROVAL_MOVES",
    "BackgroundCheckProposal",
    "BackgroundCheckProposalResolution",
    "ProposalOutcome",
]
