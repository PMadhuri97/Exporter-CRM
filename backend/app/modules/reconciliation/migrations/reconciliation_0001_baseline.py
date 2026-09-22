"""reconciliation module baseline — schema `reconciliation`

Squash of c1d2e3f4a5b6 — the module's only migration — expressed as the final
desired schema only. Nothing else in the chain ever touched these tables, so the
baseline is a straight relocation into a dedicated schema.

Everything is created inside the dedicated `reconciliation` schema:

  reconciliation.reconciliations       — one three-way match run. Append-only.
  reconciliation.reconciliation_checks — one row per comparison. Append-only.

The module owns no functions and no sequences.

Both tables are append-only. A transaction may be reconciled many times (for
example on a schedule) and every run is preserved: a re-run inserts a new
`reconciliations` row rather than rewriting the previous one, which is why there
is no unique constraint on `transaction_id`.

`reconciliations.case_id` deliberately carries **no** foreign key. It records the
`compliance_cases` row opened when a run returns BREAK, but the reference has
never been constrained — reconciliation must be able to record a case id without
taking a hard dependency on the compliance schema. Reproduced here as a bare
nullable UUID, not invented as a constraint.

Column order reproduces the physical order in the pre-squash database. In both
tables that puts `id` and `created_at` last, because the original autogenerate
emitted the AppendOnlyModel mixin columns after the domain columns. The ORM
declares them first; the database does not.

CROSS-SCHEMA DEPENDENCY: both tables reference
`payments.transactions.transaction_id`, created by the payments baseline. That
baseline must be applied first.

EXTERNAL DEPENDENCY: both immutability triggers execute
`public.prevent_mutation()`, which is created by the shared bootstrap migration
a0b1c2d3e4f5 and is not owned by this module. It is referenced schema-qualified
so the reference cannot be broken by a search_path change.

Constraint names reproduce what the pre-squash database holds. Neither table was
ever renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical; they are spelled out only so the baseline states the full schema
rather than relying on generation rules.

Revision ID: reconciliation_0001_baseline
Revises: compliance_0001_baseline
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "reconciliation_0001_baseline"
down_revision: str | None = "compliance_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "reconciliation"
PAYMENTS_SCHEMA = "payments"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: these models use a plain
# Enum(PyEnum, name=...), so SQLAlchemy persists `.name`.

reconciliation_status_enum = postgresql.ENUM(
    # MATCHED — all checks passed, Ledger / Settlement / Bank agree.
    # BREAK   — one or more checks failed, investigation required.
    "MATCHED", "BREAK",
    name="reconciliation_status_enum", schema=SCHEMA, create_type=False,
)
reconciliation_check_type_enum = postgresql.ENUM(
    # Ledger internal integrity
    "LEDGER_DOUBLE_ENTRY_BALANCED",
    # Ledger <-> Settlement
    "LEDGER_VS_SETTLEMENT_USD_AMOUNT",
    # Settlement <-> Bank confirmation (USDC bridge partner)
    "SETTLEMENT_VS_BANK_USDC_REFERENCE",
    "SETTLEMENT_VS_BANK_USDC_AMOUNT",
    # Settlement <-> Bank confirmation (INR banking partner)
    "SETTLEMENT_VS_BANK_INR_REFERENCE",
    "SETTLEMENT_VS_BANK_INR_AMOUNT",
    name="reconciliation_check_type_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (reconciliation_status_enum, reconciliation_check_type_enum)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline, so a second column adopting
    # one of these types later cannot trigger a duplicate CREATE TYPE.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── reconciliations ───────────────────────────────────────────────────────
    op.create_table(
        "reconciliations",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("status", reconciliation_status_enum, nullable=False),
        sa.Column("total_checks", sa.Integer(), nullable=False),
        sa.Column("passed_checks", sa.Integer(), nullable=False),
        sa.Column("failed_checks", sa.Integer(), nullable=False),
        sa.Column("break_reason", sa.Text(), nullable=True),
        # Full structured report (source views + every check) for audit / replay.
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Set when a BREAK opens a RECONCILIATION_BREAK compliance case.
        # Deliberately unconstrained — see module docstring.
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="reconciliations_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="reconciliations_pkey"),
        schema=SCHEMA,
    )
    # Not unique: a transaction may be reconciled repeatedly and every run is kept.
    op.create_index(
        "ix_reconciliations_transaction_id",
        "reconciliations",
        ["transaction_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ── reconciliation_checks ─────────────────────────────────────────────────
    op.create_table(
        "reconciliation_checks",
        sa.Column("reconciliation_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("check_type", reconciliation_check_type_enum, nullable=False),
        sa.Column("source_a", sa.String(length=30), nullable=False),
        sa.Column("source_b", sa.String(length=30), nullable=False),
        sa.Column("value_a", sa.String(length=255), nullable=True),
        sa.Column("value_b", sa.String(length=255), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE: a check is evidence and outlives any attempt to
        # remove the run it belongs to. The append-only trigger blocks row-level
        # DELETE on the parent anyway.
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            [f"{SCHEMA}.reconciliations.id"],
            name="reconciliation_checks_reconciliation_id_fkey",
            ondelete="RESTRICT",
        ),
        # Denormalised from the parent run so a check can be located by
        # transaction without a join.
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="reconciliation_checks_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="reconciliation_checks_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_reconciliation_checks_reconciliation_id",
        "reconciliation_checks",
        ["reconciliation_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # A reconciliation run is an immutable point-in-time record, as is each of
    # its checks. prevent_mutation() is owned by the shared root migration and
    # lives in public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER reconciliations_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.reconciliations
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER reconciliation_checks_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.reconciliation_checks
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    # CASCADE reaches both tables, their keys, both indexes, both triggers and
    # both enum types in one statement.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
