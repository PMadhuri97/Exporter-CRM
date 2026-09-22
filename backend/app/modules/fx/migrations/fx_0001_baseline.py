"""fx module baseline — schema `fx`

Squash of the fx portion of 41735b67723b (one table) together with the three
later changes that touched it:

  a3f9c12d8e45  transaction_id relaxed to nullable
  b1c2d3e4f5a6  from_currency / to_currency widened to String(8)
  c1a2b3c4d5e3  source_amount / destination_amount retyped to BIGINT minor units,
                spread widened to NUMERIC(9,6), mid_rate added

Expressed as the final desired schema only.

Everything is created inside the dedicated `fx` schema:

  fx.fx_quotes — a priced, time-limited quote for one currency pair.

The module owns no enums, no functions, no triggers, no indexes beyond the
primary key, and no sequences. It is the smallest schema in the platform.

Rates are ratios, not money, and are deliberately outside Rule 1: `rate`,
`spread` and `mid_rate` stay NUMERIC while the two amount columns are BIGINT
integer minor units. `mid_rate` is the pre-spread market rate and carries more
scale than the applied rate because it is an input to a money multiplication.

`transaction_id` is nullable. a3f9c12d8e45 relaxed it so a quote can exist
before — or without — the transaction it will price, which makes fx's only
cross-module reference structurally optional. The foreign key is retained.

Column order reproduces the physical order in the pre-squash database.
`mid_rate` is position 13 because c1a2b3c4d5e3 appended it to an existing table;
the ORM declares it between `to_currency` and `rate`, but the database does not,
and the database is what this baseline reproduces.

CROSS-SCHEMA DEPENDENCY: `transaction_id` references
`payments.transactions.transaction_id`, created by the payments baseline. That
baseline must be applied first.

Constraint names reproduce what the pre-squash database holds. This table was
never renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical; they are spelled out only so the baseline states the full schema
rather than relying on generation rules.

Revision ID: fx_0001_baseline
Revises: onboarding_0001_baseline
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fx_0001_baseline"
down_revision: str | None = "onboarding_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "fx"
PAYMENTS_SCHEMA = "payments"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── fx_quotes ─────────────────────────────────────────────────────────────
    op.create_table(
        "fx_quotes",
        sa.Column("quote_id", sa.UUID(), nullable=False),
        # Nullable since a3f9c12d8e45: a quote may be priced before the
        # transaction that uses it exists, or may never be attached to one.
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        # String(8), not String(3): widened by b1c2d3e4f5a6 so these can hold
        # registry asset codes such as USDC alongside ISO-4217 currencies.
        sa.Column("from_currency", sa.String(length=8), nullable=False),
        sa.Column("to_currency", sa.String(length=8), nullable=False),
        # A ratio, not money — outside Rule 1, stays NUMERIC.
        sa.Column("rate", sa.Numeric(precision=12, scale=6), nullable=False),
        # Widened from NUMERIC(6,4) by c1a2b3c4d5e3: the service quantizes the
        # spread to 6dp, so the 5th and 6th digits were being truncated.
        sa.Column("spread", sa.Numeric(precision=9, scale=6), nullable=False),
        # Rule 1: integer minor units, scaled by the asset's registry precision.
        # Retyped from NUMERIC(18,2) by c1a2b3c4d5e3, which truncated 6dp USDC.
        sa.Column("source_amount", sa.BigInteger(), nullable=False),
        sa.Column("destination_amount", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Position 13, not 5: c1a2b3c4d5e3 appended this column to an existing
        # table. The pre-spread market rate; more scale than `rate` because it
        # feeds a money multiplication.
        sa.Column("mid_rate", sa.Numeric(precision=18, scale=10), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="fx_quotes_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("quote_id", name="fx_quotes_pkey"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # CASCADE reaches the table, its primary key and the foreign key in one
    # statement. The schema owns no enums, functions or triggers.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
