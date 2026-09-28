"""The background check: the gauge on the company, locked decisions, and their
evidence snapshots (L4-03, L4-04, L4-06, L4-08) — **owner: Developer 4A**.

Revision ID: onboarding_0015_bg_check
Revises: onboarding_0019_documents

Numbered 0015 because the migration register reserves 0015 for the background
check, and parented on 0019 because 0019 is the head when this is written. Numbers
are labels, not order; ``down_revision`` is the order (register §2). Developer 4B's
``onboarding_0021_verif_review`` starts from the same head: **whichever Dev4 PR
merges second re-parents its own ``down_revision`` onto the first** (a one-line
change) and tells Developer 1 the register row to add. Never a merge revision.

``onboarding_0015_bg_check`` is 24 characters, inside the register's 32-character
limit on ``alembic_version.version_num``.

What it adds, all in the ``onboarding`` schema, and nothing else
(``docs/dev4/4a-task.md`` §10; ``docs/contracts/background-check.md``):

* Five enum types, all Developer 4A's:
  ``background_check_enum`` (the six gauge values), ``background_check_risk_enum``
  (``LOW``/``MEDIUM``/``HIGH``/``CRITICAL`` — D13: a type of Dev4A's own, **not**
  Developer 4B's ``verification_risk_level_enum``), ``background_check_decided_by_kind_enum``,
  ``background_check_decision_source_enum`` and ``background_check_evidence_kind_enum``.
* ``exporter_profile.background_check`` — ``NOT NULL DEFAULT 'NOT_STARTED'``, the field
  ``company-record.md`` §2.4 reserves for Developer 4. It is a column on Developer 2's
  table, so **this migration needs Developer 2's review**, as 0016 did. **No risk
  column is added to the company** — that is D5, open.
* ``background_check_decision`` — one locked row per move, chained by
  ``supersedes_decision_id``. The constraints make one company's decisions a single
  unbroken chain that can only grow at its head (contract §5.3).
* ``background_check_evidence`` — one locked row per id a decision relied on. Foreign
  keys to ``crm_document``, ``verification_result`` and ``screening_review_item``, which
  all exist already. The verification **review** id is a bare uuid on purpose: Developer
  4B's review table is theirs, in their own unmerged migration, and an FK to it would
  make the two Dev4 migrations depend on each other (contract §6.1).

Nothing verification- or screening-shaped is created or altered; Developer 4B's
tables are only referenced.

**Enum types are created in the ordinary transactional body**, never with
``ALTER TYPE … ADD VALUE`` in an autocommit block (register §2).

Downgrade drops everything this adds, **including every recorded decision and every
evidence snapshot** — lossy, and those are locked records of who decided what and on
what evidence, so downgrade only if you mean it. History rows with
``dimension = 'background_check'`` survive, because ``exporter_lifecycle_history``
stores values as strings and is not touched here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0015_bg_check"
down_revision: str | None = "onboarding_0019_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The six gauge values (architecture §3.3, contract §2).
BACKGROUND_CHECK_VALUES = (
    "NOT_STARTED",
    "IN_REVIEW",
    "CLEAR",
    "MORE_INFO",
    "FLAGGED",
    "ON_HOLD",
)
#: The CRM risk scale (decision 6, contract §7).
RISK_VALUES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: The nine legal moves (architecture §3.3, contract §3). Everything else is refused,
#: including `CLEAR -> FLAGGED` and a move to the value already held.
LEGAL_MOVES = (
    ("NOT_STARTED", "IN_REVIEW"),
    ("IN_REVIEW", "CLEAR"),
    ("IN_REVIEW", "MORE_INFO"),
    ("MORE_INFO", "IN_REVIEW"),
    ("IN_REVIEW", "FLAGGED"),
    ("FLAGGED", "ON_HOLD"),
    ("FLAGGED", "IN_REVIEW"),
    ("ON_HOLD", "IN_REVIEW"),
    ("CLEAR", "IN_REVIEW"),
)


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, schema=SCHEMA, create_type=False)


background_check_enum = _enum("background_check_enum", *BACKGROUND_CHECK_VALUES)
risk_enum = _enum("background_check_risk_enum", *RISK_VALUES)
decided_by_kind_enum = _enum("background_check_decided_by_kind_enum", "MANUAL", "AUTOMATED")
source_enum = _enum("background_check_decision_source_enum", "MANUAL", "RXIL")
evidence_kind_enum = _enum(
    "background_check_evidence_kind_enum", "DOCUMENT", "VERIFICATION_RESULT", "SCREENING_ITEM"
)
_ENUMS = (background_check_enum, risk_enum, decided_by_kind_enum, source_enum, evidence_kind_enum)

_MOVE_CONSTRAINT = " OR ".join(
    f"(from_value = '{from_value}' AND to_value = '{to_value}')"
    for from_value, to_value in LEGAL_MOVES
)
#: Every move but the start carries text (contract §4): the note of what is needed or
#: what arrived, or the reason. Includes `CLEAR` (architecture §4.1 step 9) and
#: `MORE_INFO -> IN_REVIEW`, which `history-row.md` §4 omits (D14).
_REASON_CONSTRAINT = (
    "from_value = 'NOT_STARTED' OR (reason IS NOT NULL AND btrim(reason) <> '')"
)
_EVIDENCE_KIND_CONSTRAINT = (
    "(kind = 'DOCUMENT' AND crm_document_id IS NOT NULL AND verification_result_id IS NULL"
    " AND verification_review_id IS NULL AND screening_review_item_id IS NULL)"
    " OR (kind = 'VERIFICATION_RESULT' AND verification_result_id IS NOT NULL"
    " AND crm_document_id IS NULL AND screening_review_item_id IS NULL)"
    " OR (kind = 'SCREENING_ITEM' AND screening_review_item_id IS NOT NULL"
    " AND crm_document_id IS NULL AND verification_result_id IS NULL"
    " AND verification_review_id IS NULL)"
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=False)

    # ── 1. The gauge on the company record (Developer 2 reviews) ─────────────
    op.add_column(
        "exporter_profile",
        sa.Column(
            "background_check",
            background_check_enum,
            nullable=False,
            server_default="NOT_STARTED",
        ),
        schema=SCHEMA,
    )
    # Beside `ix_exporter_profile_conversation` (0016): lists filter on the gauge, and
    # §3.8 keeps the current value on the record so that needs no join.
    op.create_index(
        "ix_exporter_profile_background_check",
        "exporter_profile",
        ["background_check"],
        schema=SCHEMA,
    )

    # ── 2. Decisions — one locked row per move ──────────────────────────────
    op.create_table(
        "background_check_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_value", background_check_enum, nullable=False),
        sa.Column("to_value", background_check_enum, nullable=False),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_by_kind", decided_by_kind_enum, nullable=False),
        sa.Column("source", source_enum, nullable=False),
        # `clock_timestamp()`, not `now()`: a move inserts its decision only after it
        # holds the company row lock, so wall-clock time at insert follows the chain.
        # `now()` is transaction-start time, and a move that waited on the lock would
        # sort *before* the decision it supersedes.
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("risk_rating", risk_enum, nullable=True),
        sa.Column("supersedes_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_background_check_decision"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_background_check_decision_company_id",
            ondelete="RESTRICT",
        ),
        # A decision has at most one direct successor: two concurrent moves on one
        # company cannot both extend the chain from the same decision.
        sa.UniqueConstraint(
            "supersedes_decision_id", name="uq_background_check_decision_supersedes"
        ),
        # The target of the chain FK below: a decision, its company and its outcome.
        sa.UniqueConstraint(
            "id", "company_id", "to_value", name="uq_background_check_decision_chain_key"
        ),
        sa.CheckConstraint(_MOVE_CONSTRAINT, name="ck_background_check_decision_move"),
        sa.CheckConstraint(_REASON_CONSTRAINT, name="ck_background_check_decision_reason"),
        sa.CheckConstraint(
            "to_value <> 'CLEAR' OR risk_rating IS NOT NULL",
            name="ck_background_check_decision_clear_risk",
        ),
        # Risk is compliance's rating at the moment of clearing (contract §7), so it
        # belongs to `CLEAR` decisions only. Without this, any move — including an
        # OPERATIONS start — could carry a rating the reader would then report.
        sa.CheckConstraint(
            "to_value = 'CLEAR' OR risk_rating IS NULL",
            name="ck_background_check_decision_risk_only_on_clear",
        ),
        sa.CheckConstraint(
            "decided_by_kind <> 'MANUAL' OR (decided_by IS NOT NULL AND btrim(decided_by) <> '')",
            name="ck_background_check_decision_decided_by",
        ),
        # The first decision is the start, and every later one names its predecessor.
        sa.CheckConstraint(
            "(from_value = 'NOT_STARTED') = (supersedes_decision_id IS NULL)",
            name="ck_background_check_decision_first",
        ),
        schema=SCHEMA,
    )
    # The predecessor is a decision of the same company, and this move starts from the
    # value that decision ended at. `MATCH SIMPLE`: the first decision (no predecessor)
    # is not checked. Added after the table so its unique target already exists.
    op.create_foreign_key(
        "fk_background_check_decision_supersedes",
        "background_check_decision",
        "background_check_decision",
        ["supersedes_decision_id", "company_id", "from_value"],
        ["id", "company_id", "to_value"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    # One chain per company: at most one decision with no predecessor.
    op.create_index(
        "uq_background_check_decision_first_per_company",
        "background_check_decision",
        ["company_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("supersedes_decision_id IS NULL"),
    )
    # One company's decisions, newest first. `decided_at` is insert-time wall clock, so
    # it follows the chain; `id` only breaks a (theoretical) exact tie. Also serves the
    # company FK.
    op.create_index(
        "ix_background_check_decision_company_recent",
        "background_check_decision",
        ["company_id", sa.text("decided_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )
    op.execute(
        f"CREATE TRIGGER trg_background_check_decision_append_only "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.background_check_decision "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_mutation();"
    )

    # ── 3. Evidence snapshots — one locked row per pinned id ────────────────
    op.create_table(
        "background_check_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", evidence_kind_enum, nullable=False),
        sa.Column("crm_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verification_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Bare on purpose — Developer 4B's review table (contract §6.1).
        sa.Column("verification_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("screening_review_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_background_check_evidence"),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            [f"{SCHEMA}.background_check_decision.id"],
            name="fk_background_check_evidence_decision_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["crm_document_id"],
            [f"{SCHEMA}.crm_document.id"],
            name="fk_background_check_evidence_crm_document_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_result_id"],
            [f"{SCHEMA}.verification_result.id"],
            name="fk_background_check_evidence_verification_result_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["screening_review_item_id"],
            [f"{SCHEMA}.screening_review_item.id"],
            name="fk_background_check_evidence_screening_review_item_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_EVIDENCE_KIND_CONSTRAINT, name="ck_background_check_evidence_kind"),
        # An item appears at most once in one decision's snapshot. Each leads with
        # `decision_id`, so together they also serve "the snapshot of this decision".
        sa.UniqueConstraint(
            "decision_id", "crm_document_id", name="uq_background_check_evidence_document"
        ),
        sa.UniqueConstraint(
            "decision_id",
            "verification_result_id",
            name="uq_background_check_evidence_verification",
        ),
        sa.UniqueConstraint(
            "decision_id",
            "screening_review_item_id",
            name="uq_background_check_evidence_screening",
        ),
        schema=SCHEMA,
    )
    # "Which decisions relied on this?" — and what the `RESTRICT` checks use when
    # someone tries to delete a pinned row. Partial: each column is set on one kind only.
    for column in ("crm_document_id", "verification_result_id", "screening_review_item_id"):
        op.create_index(
            f"ix_background_check_evidence_{column}",
            "background_check_evidence",
            [column],
            schema=SCHEMA,
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    op.execute(
        f"CREATE TRIGGER trg_background_check_evidence_append_only "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.background_check_evidence "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_mutation();"
    )


def downgrade() -> None:
    # Lossy: every decision and every evidence snapshot goes, and both are locked
    # records of who decided what and on what. Downgrade only if you mean it.
    # `background_check` history rows survive — stored as strings, not touched here.
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_background_check_evidence_append_only "
        f"ON {SCHEMA}.background_check_evidence"
    )
    op.drop_table("background_check_evidence", schema=SCHEMA)
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_background_check_decision_append_only "
        f"ON {SCHEMA}.background_check_decision"
    )
    op.drop_table("background_check_decision", schema=SCHEMA)

    op.drop_index(
        "ix_exporter_profile_background_check", table_name="exporter_profile", schema=SCHEMA
    )
    op.drop_column("exporter_profile", "background_check", schema=SCHEMA)

    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=False)
