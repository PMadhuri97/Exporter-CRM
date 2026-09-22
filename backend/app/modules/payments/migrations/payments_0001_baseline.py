"""payments module baseline — schema `payments`

Squash of the payments portion of 41735b67723b (three tables, two enums, one
immutability trigger) together with the two payments column changes made later:
`transactions.amount` retyped to BIGINT minor units by c1a2b3c4d5e3, and
`source_currency` / `destination_currency` widened to String(8) by b1c2d3e4f5a6.
Expressed as the final desired schema only.

Everything is created inside the dedicated `payments` schema:

  payments.transactions               — the payment instruction.
  payments.transaction_status_history — append-only status audit trail.
  payments.idempotency_keys           — 24h duplicate-submission guard.

`payments.transactions` is the highest fan-in object in the platform: nine
foreign keys from six other modules terminate on `transaction_id`. None of them
are declared here — each referencing module declares its own — but every one of
those modules must be ordered after payments at cutover.

The module owns no functions and no sequences. All three primary keys are
supplied by the application (two UUID, one natural VARCHAR key).

Column order reproduces the physical order in the pre-squash database. In
`transaction_status_history` that puts `id` and `created_at` at positions 6 and
7, because the original autogenerate emitted the AppendOnlyModel mixin columns
last. The ORM declares them first; the database is what this baseline reproduces.

CROSS-SCHEMA DEPENDENCY: both `transactions` customer references point at
`customers.customers.customer_id`, created by the customers baseline. That
baseline must be applied first.

EXTERNAL DEPENDENCY: `transaction_status_history_immutable` executes
`public.prevent_mutation()`, which is created by the shared bootstrap migration
a0b1c2d3e4f5 and is not owned by this module. It is referenced schema-qualified
so the reference cannot be broken by a search_path change.

Constraint names reproduce what the pre-squash database holds. None of these
tables was ever renamed, so PostgreSQL's auto-generated names and the explicit
names below are identical; they are spelled out only so the baseline states the
full schema rather than relying on generation rules.

Revision ID: payments_0001_baseline
Revises: customers_0001_baseline
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "payments_0001_baseline"
down_revision: str | None = "customers_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "payments"
CUSTOMERS_SCHEMA = "customers"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: these models do not pass
# values_callable, so SQLAlchemy persists `.name`. The stored labels must match.

transaction_status_enum = postgresql.ENUM(
    "INITIATED",
    "VALIDATED",
    "UNDER_REVIEW",
    "APPROVED",
    "FUNDED",
    "DIGITAL_ASSET_SETTLED",
    "SETTLING",
    "SETTLED",
    "RECONCILED",
    "VALIDATION_FAILED",
    "BLOCKED",
    "DECLINED",
    "FAILED",
    "RECALLED_VIA_COMPENSATION",
    name="transaction_status_enum",
    schema=SCHEMA,
    create_type=False,
)
# Named for settlement but owned by payments: it types transactions.settlement_route,
# and no settlement table uses it. Schema qualification makes that unambiguous.
settlement_route_enum = postgresql.ENUM(
    "FIAT", "DIGITAL_ASSET_BRIDGE",
    name="settlement_route_enum",
    schema=SCHEMA,
    create_type=False,
)

_ENUMS = (transaction_status_enum, settlement_route_enum)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front, not inline: transaction_status_enum types three
    # columns across two tables, so letting create_table emit it would attempt
    # CREATE TYPE more than once.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── transactions ──────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("sender_customer_id", sa.UUID(), nullable=False),
        sa.Column("beneficiary_customer_id", sa.UUID(), nullable=False),
        # Rule 1: integer minor units, scaled by source_currency's registry
        # precision. Retyped from String(30) by c1a2b3c4d5e3, which stored
        # whatever text the caller sent.
        sa.Column("amount", sa.BigInteger(), nullable=False),
        # String(8), not String(3): widened by b1c2d3e4f5a6 so these can hold
        # registry asset codes such as USDC alongside ISO-4217 currencies.
        sa.Column("source_currency", sa.String(length=8), nullable=False),
        sa.Column("destination_currency", sa.String(length=8), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("invoice_reference", sa.String(length=100), nullable=True),
        sa.Column("status", transaction_status_enum, nullable=False),
        sa.Column("settlement_route", settlement_route_enum, nullable=True),
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
        # RESTRICT on both, unlike beneficiary_bank_accounts' CASCADE: a
        # transaction is a financial record and must outlive any attempt to
        # remove the counterparty that created it.
        sa.ForeignKeyConstraint(
            ["sender_customer_id"],
            [f"{CUSTOMERS_SCHEMA}.customers.customer_id"],
            name="transactions_sender_customer_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_customer_id"],
            [f"{CUSTOMERS_SCHEMA}.customers.customer_id"],
            name="transactions_beneficiary_customer_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transaction_id", name="transactions_pkey"),
        # Uniqueness here is the idempotency guarantee — a replayed submission
        # collides on this key rather than creating a second payment.
        sa.UniqueConstraint("idempotency_key", name="transactions_idempotency_key_key"),
        schema=SCHEMA,
    )

    # ── transaction_status_history ────────────────────────────────────────────
    op.create_table(
        "transaction_status_history",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        # NULL on the first row: a transaction's initial status has no predecessor.
        sa.Column("from_status", transaction_status_enum, nullable=True),
        sa.Column("to_status", transaction_status_enum, nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        # Positions 6 and 7, not 1 and 2: the original autogenerate emitted the
        # AppendOnlyModel mixin columns last, and that is the live ordering.
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CASCADE, unlike every other reference to transactions: the trail has no
        # meaning without its transaction. The append-only trigger below blocks
        # row-level DELETE, so this cascade is reachable only by dropping the
        # parent, which the platform never does.
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{SCHEMA}.transactions.transaction_id"],
            name="transaction_status_history_transaction_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="transaction_status_history_pkey"),
        schema=SCHEMA,
    )

    # ── idempotency_keys ──────────────────────────────────────────────────────
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=255), nullable=False),
        # Deliberately unconstrained: the key is written before the transaction
        # exists and must survive a submission that never produced one.
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name="idempotency_keys_pkey"),
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # transaction_status_history is the status audit trail and must be
    # append-only. prevent_mutation() is owned by the shared root migration and
    # lives in public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER transaction_status_history_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.transaction_status_history
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    # CASCADE reaches the three tables, their keys, the trigger and both enum
    # types in one statement, plus the nine foreign keys other schemas hold into
    # payments.transactions.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
