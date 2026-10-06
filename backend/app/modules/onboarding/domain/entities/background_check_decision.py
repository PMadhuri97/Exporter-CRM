"""``BackgroundCheckDecision`` and ``BackgroundCheckEvidence``
(``docs/contracts/background-check.md`` §5, §6).

Both are locked at both layers, the same pair of guarantees ``FollowUpCompletion``
and ``ExporterLifecycleHistory`` have: ``AppendOnlyRepository`` exposes no update
and no delete, and ``public.prevent_mutation()`` refuses both at the database
whatever code tries (``trg_background_check_decision_append_only``,
``trg_background_check_evidence_append_only``, migration ``onboarding_0015_bg_check``).

A move on the gauge is a **new** decision that names the one it supersedes. A reopen
or a reassessment never edits the decision it follows.

The constraints are declared here as well as in the migration so the model states
the same invariants the database enforces; the migration is what creates them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"

#: The nine legal moves (architecture §3.3, contract §3). The service refuses anything
#: else before writing; `ck_background_check_decision_move` refuses it at the database.
LEGAL_MOVES: frozenset[tuple[BackgroundCheckState, BackgroundCheckState]] = frozenset(
    {
        (BackgroundCheckState.NOT_STARTED, BackgroundCheckState.IN_REVIEW),
        (BackgroundCheckState.IN_REVIEW, BackgroundCheckState.CLEAR),
        (BackgroundCheckState.IN_REVIEW, BackgroundCheckState.MORE_INFO),
        (BackgroundCheckState.MORE_INFO, BackgroundCheckState.IN_REVIEW),
        (BackgroundCheckState.IN_REVIEW, BackgroundCheckState.FLAGGED),
        (BackgroundCheckState.FLAGGED, BackgroundCheckState.ON_HOLD),
        (BackgroundCheckState.FLAGGED, BackgroundCheckState.IN_REVIEW),
        (BackgroundCheckState.ON_HOLD, BackgroundCheckState.IN_REVIEW),
        (BackgroundCheckState.CLEAR, BackgroundCheckState.IN_REVIEW),
    }
)

_MOVE_CONSTRAINT = " OR ".join(
    f"(from_value = '{from_value.value}' AND to_value = '{to_value.value}')"
    for from_value, to_value in sorted(LEGAL_MOVES, key=lambda move: (move[0].value, move[1].value))
)


class BackgroundCheckDecision(AppendOnlyModel):
    """One move of one company's background check, as decided. Locked.

    ``from_value`` → ``to_value`` is the move; ``to_value`` is the decision's outcome.
    ``supersedes_decision_id`` names the company's previous decision, so one company's
    decisions form a single chain from ``NOT_STARTED``; the chain head is the latest
    decision (contract §5.4).
    """

    __tablename__ = "background_check_decision"
    __table_args__ = (
        # At most one direct successor: two concurrent moves cannot fork the chain.
        UniqueConstraint("supersedes_decision_id", name="uq_background_check_decision_supersedes"),
        UniqueConstraint(
            "id", "company_id", "to_value", name="uq_background_check_decision_chain_key"
        ),
        # The predecessor belongs to the same company and ended at this move's start.
        ForeignKeyConstraint(
            ["supersedes_decision_id", "company_id", "from_value"],
            [
                f"{SCHEMA}.background_check_decision.id",
                f"{SCHEMA}.background_check_decision.company_id",
                f"{SCHEMA}.background_check_decision.to_value",
            ],
            name="fk_background_check_decision_supersedes",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_MOVE_CONSTRAINT, name="ck_background_check_decision_move"),
        CheckConstraint(
            "from_value = 'NOT_STARTED' OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_background_check_decision_reason",
        ),
        CheckConstraint(
            "to_value <> 'CLEAR' OR risk_rating IS NOT NULL",
            name="ck_background_check_decision_clear_risk",
        ),
        CheckConstraint(
            "to_value = 'CLEAR' OR risk_rating IS NULL",
            name="ck_background_check_decision_risk_only_on_clear",
        ),
        CheckConstraint(
            "decided_by_kind <> 'MANUAL' OR (decided_by IS NOT NULL AND btrim(decided_by) <> '')",
            name="ck_background_check_decision_decided_by",
        ),
        CheckConstraint(
            "(from_value = 'NOT_STARTED') = (supersedes_decision_id IS NULL)",
            name="ck_background_check_decision_first",
        ),
        Index(
            "uq_background_check_decision_first_per_company",
            "company_id",
            unique=True,
            postgresql_where=text("supersedes_decision_id IS NULL"),
        ),
        # Newest first; `decided_at` follows the chain, `id` breaks an exact tie.
        Index(
            "ix_background_check_decision_company_recent",
            "company_id",
            text("decided_at DESC"),
            text("id DESC"),
        ),
        # 0025: the cycle a decision was taken in, and a cycle
        # of the same company.
        ForeignKeyConstraint(
            ["cycle_id", "company_id"],
            [f"{SCHEMA}.check_cycle.id", f"{SCHEMA}.check_cycle.company_id"],
            name="fk_background_check_decision_cycle",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_background_check_decision_cycle_id",
            "cycle_id",
            postgresql_where=text("cycle_id IS NOT NULL"),
        ),
        # 0026: an approved decision names its proposal — of the
        # same company, by the same proposer (`decided_by`), for the same move — and
        # was approved by someone else. `use_alter`: the proposal names its base
        # decision too, so the two tables refer to each other.
        ForeignKeyConstraint(
            ["proposal_id", "company_id", "decided_by", "from_value", "to_value"],
            [
                f"{SCHEMA}.background_check_proposal.id",
                f"{SCHEMA}.background_check_proposal.company_id",
                f"{SCHEMA}.background_check_proposal.created_by",
                f"{SCHEMA}.background_check_proposal.from_value",
                f"{SCHEMA}.background_check_proposal.to_value",
            ],
            name="fk_background_check_decision_proposal",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint("proposal_id", name="uq_background_check_decision_proposal"),
        UniqueConstraint(
            "id", "proposal_id", "approved_by", name="uq_background_check_decision_approval_key"
        ),
        CheckConstraint(
            "(proposal_id IS NULL) = (approved_by IS NULL) "
            "AND (approved_by IS NULL) = (approved_at IS NULL)",
            name="ck_background_check_decision_approval",
        ),
        CheckConstraint(
            "approved_by IS NULL OR approved_by <> decided_by",
            name="ck_background_check_decision_maker_checker",
        ),
        # 0027: only a CLEAR expires, and after it was decided.
        CheckConstraint(
            "expires_at IS NULL OR (to_value = 'CLEAR' AND expires_at > decided_at)",
            name="ck_background_check_decision_expiry",
        ),
        {"schema": SCHEMA},
    )

    #: The company. `RESTRICT`: a company with decisions cannot be deleted.
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_background_check_decision_company_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    from_value: Mapped[BackgroundCheckState] = mapped_column(
        Enum(BackgroundCheckState, name="background_check_enum", schema=SCHEMA),
        nullable=False,
    )
    to_value: Mapped[BackgroundCheckState] = mapped_column(
        Enum(BackgroundCheckState, name="background_check_enum", schema=SCHEMA),
        nullable=False,
    )
    #: Who, from the login session — never from a request body. `NULL` only for a
    #: platform-originated move (`AUTOMATED`), and none exists until RXIL intake.
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_by_kind: Mapped[BackgroundCheckDecidedByKind] = mapped_column(
        Enum(
            BackgroundCheckDecidedByKind,
            name="background_check_decided_by_kind_enum",
            schema=SCHEMA,
        ),
        nullable=False,
    )
    source: Mapped[BackgroundCheckDecisionSource] = mapped_column(
        Enum(
            BackgroundCheckDecisionSource,
            name="background_check_decision_source_enum",
            schema=SCHEMA,
        ),
        nullable=False,
    )
    #: Server time. Not set by callers.
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    #: The reason, or the note of what is needed / what arrived. Required on every
    #: move but the start (`ck_background_check_decision_reason`, contract §4).
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Required on `CLEAR` (`ck_background_check_decision_clear_risk`) and refused on
    #: every other move (`ck_background_check_decision_risk_only_on_clear`).
    risk_rating: Mapped[BackgroundCheckRisk | None] = mapped_column(
        Enum(BackgroundCheckRisk, name="background_check_risk_enum", schema=SCHEMA),
        nullable=True,
    )
    #: The company's previous decision; `NULL` exactly on its first
    #: (`ck_background_check_decision_first`).
    supersedes_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    #: IDs a reader needs without a second query. Never evidence content or PII.
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: The Clear rules in force when the decision was taken:
    #: `background_check_views.CLEAR_RULES_V2` on every decision recorded since
    #: migration 0025. `NULL` on the decisions before it, which the documented read
    #: rule takes as `CLEAR_RULES_V1` — the eight-item checklist.
    rules_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The check cycle the decision was taken in; `NULL` = cycle 1 by rule.
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: Maker-checker: the proposal this decision
    #: approved, who approved it and when. All three or none
    #: (`ck_background_check_decision_approval`); the approver is never the decider
    #: (`ck_background_check_decision_maker_checker`). `NULL` on every decision recorded
    #: by one person — before maker-checker, or a move that needs no approval.
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: When this CLEAR stops being current: `decided_at`
    #: + the validity setting, on every CLEAR since migration 0027. `NULL` on a CLEAR
    #: before it, which the documented read rule takes as `decided_at` + one year,
    #: and on every other move.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundCheckEvidence(AppendOnlyModel):
    """One id a decision relied on, pinned when the decision was made. Locked.

    IDs only, never content (contract §6). Exactly the column for ``kind`` is set
    (``ck_background_check_evidence_kind``). ``verification_review_id`` is a bare uuid
    with no foreign key on purpose: the review table belongs to verification (contract §6.1).
    """

    __tablename__ = "background_check_evidence"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'DOCUMENT' AND crm_document_id IS NOT NULL AND verification_result_id IS NULL"
            " AND verification_review_id IS NULL AND screening_review_item_id IS NULL)"
            " OR (kind = 'VERIFICATION_RESULT' AND verification_result_id IS NOT NULL"
            " AND crm_document_id IS NULL AND screening_review_item_id IS NULL)"
            " OR (kind = 'SCREENING_ITEM' AND screening_review_item_id IS NOT NULL"
            " AND crm_document_id IS NULL AND verification_result_id IS NULL"
            " AND verification_review_id IS NULL)",
            name="ck_background_check_evidence_kind",
        ),
        UniqueConstraint(
            "decision_id", "crm_document_id", name="uq_background_check_evidence_document"
        ),
        UniqueConstraint(
            "decision_id",
            "verification_result_id",
            name="uq_background_check_evidence_verification",
        ),
        UniqueConstraint(
            "decision_id",
            "screening_review_item_id",
            name="uq_background_check_evidence_screening",
        ),
        Index(
            "ix_background_check_evidence_crm_document_id",
            "crm_document_id",
            postgresql_where=text("crm_document_id IS NOT NULL"),
        ),
        Index(
            "ix_background_check_evidence_verification_result_id",
            "verification_result_id",
            postgresql_where=text("verification_result_id IS NOT NULL"),
        ),
        Index(
            "ix_background_check_evidence_screening_review_item_id",
            "screening_review_item_id",
            postgresql_where=text("screening_review_item_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.background_check_decision.id",
            name="fk_background_check_evidence_decision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    kind: Mapped[BackgroundCheckEvidenceKind] = mapped_column(
        Enum(
            BackgroundCheckEvidenceKind,
            name="background_check_evidence_kind_enum",
            schema=SCHEMA,
        ),
        nullable=False,
    )
    #: The CRM's `crm_document` — no second document system.
    crm_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.crm_document.id",
            name="fk_background_check_evidence_crm_document_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    verification_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.verification_result.id",
            name="fk_background_check_evidence_verification_result_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    #: The review the result's standing rested on. Bare uuid (contract §6.1).
    verification_review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    #: The exact checklist row, since screening rows keep being added after a decision.
    screening_review_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.screening_review_item.id",
            name="fk_background_check_evidence_screening_review_item_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )


__all__ = ["LEGAL_MOVES", "BackgroundCheckDecision", "BackgroundCheckEvidence"]
