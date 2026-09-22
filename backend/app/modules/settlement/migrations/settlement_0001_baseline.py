"""settlement module baseline — schema `settlement`

Squash of five sources, expressed as the final desired schema only:

  41735b67723b  settlement_legs (legacy) and its two enums
  b1c2d3e4f5a6  settlement_legs.currency widened to String(8)
  c1a2b3c4d5e3  settlement_legs.amount retyped to BIGINT minor units
  d2e3f4a5b6c7  settlement, settlement_leg, settlement_event, four enums
  e4f5a6b7c8d9  assert_settlement_immutable_fields() and two triggers
  f5a6b7c8d9e0  ck_settlement_edd_rule_consistent and a column comment
  g6b7c8d9e0f1  uq_settlement_leg_settlement_id_leg_sequence

Everything is created inside the dedicated `settlement` schema:

  settlement.settlement       — the settlement aggregate root.
  settlement.settlement_leg   — one rail movement. Ordered by leg_sequence.
  settlement.settlement_event — state transition trail. Append-only.
  settlement.settlement_legs  — LEGACY. See below.

TWO PARALLEL LEG TABLES, BOTH LIVE.
`settlement_legs` (plural, from the initial schema) and `settlement_leg`
(singular, from the aggregate) are different tables with different owners and
different dependencies — the first references payments.transactions, the second
references settlement.settlement and ledger.ledger_transaction. Neither is a
migration of the other and neither is dormant: `settlement_legs` is read and
written by orchestration/application/settlement_activities.py (three call sites),
reconciliation/application/services.py, settlement/application/services.py and
settlement/api/router.py, and is registered in bootstrap.py.

Both are therefore reproduced here as-is. Consolidating them is a domain change,
not a squash, and is deliberately out of scope. See migrations/CUTOVER_MANIFEST.md.

TWO ENUM-LABEL CONVENTIONS, BOTH PRESERVED.
`leg_type_enum` and `leg_status_enum` (legacy) store UPPERCASE labels: their model
uses a plain `Enum(PyEnum, name=...)`, so SQLAlchemy persists `.name`. The four
aggregate enums store lowercase labels: `settlement_aggregate.py` passes
`values_callable`, so SQLAlchemy persists `.value`. The split is not a mistake and
must not be normalised — the stored labels differ.

Note also that `leg_type_enum`/`leg_status_enum` sit alongside
`settlement_leg_type_enum`/`settlement_leg_status_enum`. Four distinct types, two
naming families, one schema. Schema qualification does not disambiguate them
because they already differ by name; they are simply both required.

`settlement_event.from_status` / `.to_status` are `String(64)`, deliberately NOT
`settlement_status_enum`: a historical event must survive a change to the enum.

Column order reproduces the physical order in the pre-squash database.

CROSS-SCHEMA DEPENDENCIES — this is the most connected module in the platform:
  settlement.sender_account_id, .beneficiary_account_id → ledger.ledger_account.id
  settlement_leg.compensation_transaction_id            → ledger.ledger_transaction.id
  settlement_legs.transaction_id                        → payments.transactions.transaction_id
Both the ledger and payments baselines must be applied first.

EXTERNAL DEPENDENCY: `settlement_event_immutable` executes
`public.prevent_mutation()`, which is created by the shared bootstrap migration
a0b1c2d3e4f5 and is not owned by this module. It is referenced schema-qualified
so the reference cannot be broken by a search_path change.
`assert_settlement_immutable_fields()` is owned here and created in this schema.

Constraint names reproduce what the pre-squash database holds. None of these
tables was ever renamed. Where a source migration named a constraint explicitly
that name is used; where it did not, the explicit name below is identical to what
PostgreSQL would generate.

Revision ID: settlement_0001_baseline
Revises: ledger_0001_baseline
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "settlement_0001_baseline"
down_revision: str | None = "c41c3d57d7cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "settlement"
LEDGER_SCHEMA = "ledger"
PAYMENTS_SCHEMA = "payments"

ASSET_CODE_LEN = 16


# ── Enums ─────────────────────────────────────────────────────────────────────
# UPPERCASE pair — legacy settlement_legs. Plain Enum(PyEnum, name=...), so
# SQLAlchemy persists the member NAME.

leg_type_enum = postgresql.ENUM(
    "USD_DEBIT", "USDC_BRIDGE", "INR_PAYOUT",
    name="leg_type_enum", schema=SCHEMA, create_type=False,
)
leg_status_enum = postgresql.ENUM(
    "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED",
    name="leg_status_enum", schema=SCHEMA, create_type=False,
)

# lowercase quartet — the aggregate. settlement_aggregate.py passes
# values_callable, so SQLAlchemy persists the member VALUE. Do not normalise
# these to match the pair above.

settlement_status_enum = postgresql.ENUM(
    "initiated", "funded", "screened", "authorized", "routed", "settling",
    "settled", "reconciled", "failed_pending_compensation", "compensated",
    "recalled", "returned", "recall_failed",
    name="settlement_status_enum", schema=SCHEMA, create_type=False,
)
settlement_leg_type_enum = postgresql.ENUM(
    "fiat", "crypto",
    name="settlement_leg_type_enum", schema=SCHEMA, create_type=False,
)
settlement_leg_status_enum = postgresql.ENUM(
    "pending", "executing", "settled", "failed", "compensated",
    name="settlement_leg_status_enum", schema=SCHEMA, create_type=False,
)
settlement_leg_finality_type_enum = postgresql.ENUM(
    "reversible", "irreversible",
    name="settlement_leg_finality_type_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    leg_type_enum,
    leg_status_enum,
    settlement_status_enum,
    settlement_leg_type_enum,
    settlement_leg_status_enum,
    settlement_leg_finality_type_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline, so a second column adopting
    # one of these types later cannot trigger a duplicate CREATE TYPE.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── settlement_legs (LEGACY) ──────────────────────────────────────────────
    # Still read and written by orchestration, reconciliation and settlement's
    # own service and router. Not dormant, not a predecessor of settlement_leg.
    op.create_table(
        "settlement_legs",
        sa.Column("leg_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("leg_type", leg_type_enum, nullable=False),
        sa.Column("status", leg_status_enum, nullable=False),
        # Blockchain tx id or bank reference.
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        # Rule 1: integer minor units. Retyped from NUMERIC(18,6) by c1a2b3c4d5e3.
        sa.Column("amount", sa.BigInteger(), nullable=False),
        # String(8), not String(3): widened by b1c2d3e4f5a6.
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="settlement_legs_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("leg_id", name="settlement_legs_pkey"),
        schema=SCHEMA,
    )

    # ── settlement ────────────────────────────────────────────────────────────
    op.create_table(
        "settlement",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status", settlement_status_enum, nullable=False, server_default="initiated"
        ),
        sa.Column("sender_account_id", sa.UUID(), nullable=False),
        sa.Column("beneficiary_account_id", sa.UUID(), nullable=False),
        # Rule 1: integer minor units, scaled by the currency registry precision.
        sa.Column("send_amount", sa.BigInteger(), nullable=False),
        sa.Column("send_asset_code", sa.String(length=ASSET_CODE_LEN), nullable=False),
        # NULL until FX is applied.
        sa.Column("receive_amount", sa.BigInteger(), nullable=True),
        sa.Column("receive_asset_code", sa.String(length=ASSET_CODE_LEN), nullable=False),
        # A ratio, not money — deliberately outside Rule 1, like the ledger's own
        # rate columns.
        sa.Column("fx_rate", sa.BigInteger(), nullable=True),
        sa.Column("fx_rate_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("route", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Unconstrained against the compliance registries: the codes are validated
        # in the service layer, and no FK has ever existed.
        sa.Column("purpose_code", sa.String(length=64), nullable=False),
        sa.Column("sector_code", sa.String(length=64), nullable=False),
        sa.Column("edd_required", sa.Boolean(), nullable=False),
        sa.Column("edd_trigger_rule", sa.String(length=255), nullable=True),
        sa.Column("screening_reference", sa.UUID(), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(length=255), nullable=True),
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
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sender_account_id"],
            [f"{LEDGER_SCHEMA}.ledger_account.id"],
            name="settlement_sender_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_account_id"],
            [f"{LEDGER_SCHEMA}.ledger_account.id"],
            name="settlement_beneficiary_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="settlement_pkey"),
        sa.UniqueConstraint("idempotency_key", name="uq_settlement_idempotency_key"),
        sa.CheckConstraint("send_amount > 0", name="ck_settlement_send_amount_positive"),
        sa.CheckConstraint(
            "receive_amount IS NULL OR receive_amount > 0",
            name="ck_settlement_receive_amount_positive",
        ),
        # From f5a6b7c8d9e0: the rule is populated exactly when EDD is required.
        sa.CheckConstraint(
            "edd_required = (edd_trigger_rule IS NOT NULL)",
            name="ck_settlement_edd_rule_consistent",
        ),
        schema=SCHEMA,
    )
    # idempotency_key's index is the one the UNIQUE constraint creates implicitly
    # — no separate ix_ is added for it.
    op.create_index(
        "ix_settlement_correlation_id", "settlement", ["correlation_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_status", "settlement", ["status"], unique=False, schema=SCHEMA
    )
    op.create_index(
        "ix_settlement_sender_account", "settlement", ["sender_account_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_beneficiary_account", "settlement", ["beneficiary_account_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_created_at", "settlement", ["created_at"],
        unique=False, schema=SCHEMA,
    )

    # ── settlement_leg ────────────────────────────────────────────────────────
    op.create_table(
        "settlement_leg",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("settlement_id", sa.UUID(), nullable=False),
        sa.Column("leg_sequence", sa.Integer(), nullable=False),
        sa.Column("leg_type", settlement_leg_type_enum, nullable=False),
        # NULL until the Routed transition assigns a rail.
        sa.Column("rail_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status", settlement_leg_status_enum, nullable=False, server_default="pending"
        ),
        # Rule 1: integer minor units.
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("asset_code", sa.String(length=ASSET_CODE_LEN), nullable=False),
        # Reference from the rail on submission.
        sa.Column("rail_reference", sa.String(length=255), nullable=True),
        sa.Column("finality_type", settlement_leg_finality_type_enum, nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        # The compensating ledger transaction, once the saga reverses this leg.
        sa.Column("compensation_transaction_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            [f"{SCHEMA}.settlement.id"],
            name="settlement_leg_settlement_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["compensation_transaction_id"],
            [f"{LEDGER_SCHEMA}.ledger_transaction.id"],
            name="settlement_leg_compensation_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="settlement_leg_pkey"),
        sa.CheckConstraint("leg_sequence > 0", name="ck_settlement_leg_sequence_positive"),
        sa.CheckConstraint("amount > 0", name="ck_settlement_leg_amount_positive"),
        # Enforces one leg per (settlement, sequence). Added by g6b7c8d9e0f1 after
        # the pre-squash schema shipped without it.
        sa.UniqueConstraint(
            "settlement_id", "leg_sequence",
            name="uq_settlement_leg_settlement_id_leg_sequence",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_leg_settlement", "settlement_leg", ["settlement_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_leg_sequence", "settlement_leg", ["leg_sequence"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_leg_status", "settlement_leg", ["status"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_leg_rail_reference", "settlement_leg", ["rail_reference"],
        unique=False, schema=SCHEMA,
    )

    # ── settlement_event ──────────────────────────────────────────────────────
    op.create_table(
        "settlement_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("settlement_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        # String, not the enum: from_status is NULL for the creation event, and a
        # historical event must survive a change to settlement_status_enum.
        sa.Column("from_status", sa.String(length=64), nullable=True),
        sa.Column("to_status", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("produced_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            [f"{SCHEMA}.settlement.id"],
            name="settlement_event_settlement_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="settlement_event_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_event_settlement", "settlement_event", ["settlement_id"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_event_created_at", "settlement_event", ["created_at"],
        unique=False, schema=SCHEMA,
    )
    op.create_index(
        "ix_settlement_event_type", "settlement_event", ["event_type"],
        unique=False, schema=SCHEMA,
    )

    # ── Column comments ───────────────────────────────────────────────────────
    op.execute(
        f"""
        COMMENT ON COLUMN {SCHEMA}.settlement.edd_trigger_rule IS
            'The rule that triggered EDD. Populated exactly when edd_required is true '
            '(ck_settlement_edd_rule_consistent) and immutable once set '
            '(settlement_immutable_fields). Setting it post-insert therefore requires '
            'flipping edd_required in the same UPDATE.';
        """
    )

    # ── Functions ─────────────────────────────────────────────────────────────
    # Owned by this schema. ANER3 mirrors the ledger's core-field guard code.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_settlement_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.created_at IS NOT NULL AND NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'settlement.created_at is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.created_by IS NOT NULL AND NEW.created_by IS DISTINCT FROM OLD.created_by THEN
                RAISE EXCEPTION 'settlement.created_by is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.route IS NOT NULL AND NEW.route IS DISTINCT FROM OLD.route THEN
                RAISE EXCEPTION 'settlement.route is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF OLD.edd_trigger_rule IS NOT NULL
                AND NEW.edd_trigger_rule IS DISTINCT FROM OLD.edd_trigger_rule THEN
                RAISE EXCEPTION 'settlement.edd_trigger_rule is immutable once set'
                    USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # settlement_event is the state-transition trail and is append-only.
    # prevent_mutation() is owned by the shared root migration and lives in
    # public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER settlement_event_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.settlement_event
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    # settlement itself is mutable — status, amounts and timestamps advance
    # through the saga — but four fields are frozen once set.
    op.execute(
        f"""
        CREATE TRIGGER settlement_immutable_fields
        BEFORE UPDATE ON {SCHEMA}.settlement
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_settlement_immutable_fields();
        """
    )


def downgrade() -> None:
    # CASCADE reaches all four tables, their keys, the twelve indexes, both
    # triggers, the owned function and all six enum types in one statement.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
