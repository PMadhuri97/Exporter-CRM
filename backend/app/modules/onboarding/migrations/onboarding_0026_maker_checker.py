"""Maker-checker.

Revision ID: onboarding_0026_maker_checker
Revises: onboarding_0025_check_cycle

``onboarding_0026_maker_checker`` is 29 characters, inside the register's 32-character
limit on ``alembic_version.version_num``.

The design: **proposal records, gauge unchanged.** A move
that needs a second person — ``IN_REVIEW → CLEAR``, ``IN_REVIEW → FLAGGED`` and
``FLAGGED → ON_HOLD`` — is first recorded as a *proposal*. The gauge does not
move: it stays ``IN_REVIEW`` (or ``FLAGGED`` while an ``ON_HOLD`` is proposed), and
"awaiting approval" is a sub-state the API serves. A different COMPLIANCE or ADMIN user
approves (which writes the decision), rejects it, or the proposer withdraws it. So no
change to ``background_check_enum``, the move constraint, the chain foreign key,
promotion or the handover guard.

What it adds, all in the ``onboarding`` schema
-----------------------------------------------
* ``background_check_proposal`` — **append-only** (``public.prevent_mutation()``). One
  row per proposed move: the company, the decision it was based on (the chain head
  then), ``from_value`` → ``to_value``, the risk (``CLEAR`` only), the reason, the
  SHA-256 ``inputs_fingerprint`` of the evidence selection the proposer saw, how many
  items that was, the check cycle and the Clear rules in force. Provenance:
  ``created_by`` (**the proposer**, from the login session), ``created_at`` (when it
  was proposed: ``clock_timestamp()``, like ``decided_at``), ``source``, ``source_ref``.
* ``background_check_proposal_resolution`` — **append-only**, at most one per
  proposal (``uq_…_proposal``, which is also what lets only one of two concurrent
  approve/reject requests win). ``outcome`` ``APPROVED`` / ``REJECTED`` / ``WITHDRAWN``,
  the reason (required to reject), the decision an approval wrote, and a copy of the
  proposer so the self-approval rule holds **inside one row**:
  ``(outcome = 'WITHDRAWN') = (created_by = proposed_by)`` — only the proposer
  withdraws, and only someone else approves or rejects. The copy is pinned to the
  proposal by a composite foreign key, so it cannot lie.
* ``background_check_decision`` gains ``proposal_id``, ``approved_by``,
  ``approved_at`` (nullable; all three or none), with
  ``CHECK (approved_by IS NULL OR approved_by <> decided_by)``. A composite foreign key
  pins an approved decision to its proposal **of the same company, by the same
  proposer, for the same move** — the database refuses a decision that claims a
  proposal it does not match. One decision per proposal (``uq_…_proposal``).

"One open proposal per company" is enforced by the service under the company row lock:
"open" is the absence of a resolution row, which a constraint cannot see.

No data is written: there are no legacy proposals. Every existing decision keeps
``proposal_id IS NULL`` — it was recorded before maker-checker, by one person
(before maker-checker existed).

``ADD COLUMN`` and ``ADD CONSTRAINT`` on the append-only decision table fire no row
trigger, so no protected row is updated (0013's pattern).

Downgrade
---------
Drops the decision columns and constraints and both tables. **Lossy**: every proposal,
resolution and approval recorded since is lost; the decisions themselves stay, without
their approver. Restore from the pre-upgrade ``pg_dump`` if they matter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0026_maker_checker"
down_revision: str | None = "onboarding_0025_check_cycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
PROPOSAL = "background_check_proposal"
RESOLUTION = "background_check_proposal_resolution"
DECISION = "background_check_decision"
CYCLE = "check_cycle"
PROFILE = "exporter_profile"

#: The moves that need a second approver (decided 1 October 2026).
APPROVAL_MOVES = (("IN_REVIEW", "CLEAR"), ("IN_REVIEW", "FLAGGED"), ("FLAGGED", "ON_HOLD"))
OUTCOMES = ("APPROVED", "REJECTED", "WITHDRAWN")

_PROPOSAL_MOVE_SQL = " OR ".join(
    f"(from_value = '{from_value}' AND to_value = '{to_value}')"
    for from_value, to_value in APPROVAL_MOVES
)


def _state_enum() -> postgresql.ENUM:
    return postgresql.ENUM(name="background_check_enum", schema=SCHEMA, create_type=False)


def _risk_enum() -> postgresql.ENUM:
    return postgresql.ENUM(name="background_check_risk_enum", schema=SCHEMA, create_type=False)


def _append_only(table: str) -> str:
    return f"""
        CREATE TRIGGER trg_{table}_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.prevent_mutation();
        """


def upgrade() -> None:
    # ── background_check_proposal ────────────────────────────────────────────
    op.create_table(
        PROPOSAL,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("based_on_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_value", _state_enum(), nullable=False),
        sa.Column("to_value", _state_enum(), nullable=False),
        sa.Column("risk_rating", _risk_enum(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("inputs_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rules_version", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_background_check_proposal"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{SCHEMA}.{PROFILE}.customer_id"],
            name="fk_background_check_proposal_company_id",
            ondelete="RESTRICT",
        ),
        # The chain head it was based on: a decision of the same company that ended at
        # this proposal's starting value (`uq_background_check_decision_chain_key`).
        sa.ForeignKeyConstraint(
            ["based_on_decision_id", "company_id", "from_value"],
            [
                f"{SCHEMA}.{DECISION}.id",
                f"{SCHEMA}.{DECISION}.company_id",
                f"{SCHEMA}.{DECISION}.to_value",
            ],
            name="fk_background_check_proposal_based_on",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id", "company_id"],
            [f"{SCHEMA}.{CYCLE}.id", f"{SCHEMA}.{CYCLE}.company_id"],
            name="fk_background_check_proposal_cycle",
            ondelete="RESTRICT",
        ),
        # Targets of the composite keys below: a resolution names the proposer it
        # copied, and an approved decision names the proposal's company, proposer
        # and move.
        sa.UniqueConstraint("id", "created_by", name="uq_background_check_proposal_proposer"),
        sa.UniqueConstraint(
            "id",
            "company_id",
            "created_by",
            "from_value",
            "to_value",
            name="uq_background_check_proposal_key",
        ),
        sa.CheckConstraint(_PROPOSAL_MOVE_SQL, name="ck_background_check_proposal_move"),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_background_check_proposal_reason"),
        sa.CheckConstraint(
            "(to_value = 'CLEAR') = (risk_rating IS NOT NULL)",
            name="ck_background_check_proposal_risk",
        ),
        sa.CheckConstraint(
            "inputs_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_background_check_proposal_fingerprint",
        ),
        sa.CheckConstraint(
            "evidence_count >= 0", name="ck_background_check_proposal_evidence_count"
        ),
        sa.CheckConstraint(
            "btrim(created_by) <> ''", name="ck_background_check_proposal_created_by"
        ),
        sa.CheckConstraint("btrim(source) <> ''", name="ck_background_check_proposal_source"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_background_check_proposal_company_recent",
        PROPOSAL,
        ["company_id", sa.text("created_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )
    op.execute(_append_only(PROPOSAL))

    # ── background_check_decision: who approved, and on which proposal ────────
    op.add_column(
        DECISION,
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        DECISION, sa.Column("approved_by", sa.String(length=255), nullable=True), schema=SCHEMA
    )
    op.add_column(
        DECISION,
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_background_check_decision_proposal",
        DECISION,
        PROPOSAL,
        ["proposal_id", "company_id", "decided_by", "from_value", "to_value"],
        ["id", "company_id", "created_by", "from_value", "to_value"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_background_check_decision_proposal", DECISION, ["proposal_id"], schema=SCHEMA
    )
    op.create_unique_constraint(
        "uq_background_check_decision_approval_key",
        DECISION,
        ["id", "proposal_id", "approved_by"],
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_background_check_decision_approval",
        DECISION,
        "(proposal_id IS NULL) = (approved_by IS NULL) "
        "AND (approved_by IS NULL) = (approved_at IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_background_check_decision_maker_checker",
        DECISION,
        "approved_by IS NULL OR approved_by <> decided_by",
        schema=SCHEMA,
    )

    # ── background_check_proposal_resolution ─────────────────────────────────
    op.create_table(
        RESOLUTION,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_by", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_background_check_proposal_resolution"),
        sa.UniqueConstraint(
            "proposal_id", name="uq_background_check_proposal_resolution_proposal"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id", "proposed_by"],
            [f"{SCHEMA}.{PROPOSAL}.id", f"{SCHEMA}.{PROPOSAL}.created_by"],
            name="fk_background_check_proposal_resolution_proposal",
            ondelete="RESTRICT",
        ),
        # An approval names the decision it wrote — one of this proposal, approved by
        # this resolver.
        sa.ForeignKeyConstraint(
            ["decision_id", "proposal_id", "created_by"],
            [
                f"{SCHEMA}.{DECISION}.id",
                f"{SCHEMA}.{DECISION}.proposal_id",
                f"{SCHEMA}.{DECISION}.approved_by",
            ],
            name="fk_background_check_proposal_resolution_decision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "outcome IN ('APPROVED', 'REJECTED', 'WITHDRAWN')",
            name="ck_background_check_proposal_resolution_outcome",
        ),
        # The maker-checker rule inside one row: only the proposer withdraws; only
        # someone else approves or rejects.
        sa.CheckConstraint(
            "(outcome = 'WITHDRAWN') = (created_by = proposed_by)",
            name="ck_background_check_proposal_resolution_who",
        ),
        sa.CheckConstraint(
            "(outcome = 'APPROVED') = (decision_id IS NOT NULL)",
            name="ck_background_check_proposal_resolution_decision",
        ),
        sa.CheckConstraint(
            "outcome <> 'REJECTED' OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_background_check_proposal_resolution_reason",
        ),
        sa.CheckConstraint(
            "btrim(created_by) <> ''", name="ck_background_check_proposal_resolution_created_by"
        ),
        sa.CheckConstraint(
            "btrim(source) <> ''", name="ck_background_check_proposal_resolution_source"
        ),
        schema=SCHEMA,
    )
    op.execute(_append_only(RESOLUTION))


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{RESOLUTION}_append_only ON {SCHEMA}.{RESOLUTION};")
    op.drop_table(RESOLUTION, schema=SCHEMA)

    for name in (
        "ck_background_check_decision_maker_checker",
        "ck_background_check_decision_approval",
    ):
        op.drop_constraint(name, DECISION, schema=SCHEMA, type_="check")
    for name in (
        "uq_background_check_decision_approval_key",
        "uq_background_check_decision_proposal",
    ):
        op.drop_constraint(name, DECISION, schema=SCHEMA, type_="unique")
    op.drop_constraint(
        "fk_background_check_decision_proposal", DECISION, schema=SCHEMA, type_="foreignkey"
    )
    for column in ("approved_at", "approved_by", "proposal_id"):
        op.drop_column(DECISION, column, schema=SCHEMA)

    op.execute(f"DROP TRIGGER IF EXISTS trg_{PROPOSAL}_append_only ON {SCHEMA}.{PROPOSAL};")
    op.drop_index(
        "ix_background_check_proposal_company_recent", table_name=PROPOSAL, schema=SCHEMA
    )
    op.drop_table(PROPOSAL, schema=SCHEMA)
