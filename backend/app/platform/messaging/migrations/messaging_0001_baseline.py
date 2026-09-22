"""messaging platform module baseline — schema `messaging`

Squash of b7e4a1c92f10 — the module's only migration — expressed as the final
desired schema only. Nothing else in the chain ever touched these tables, so the
baseline is a straight relocation into a dedicated schema.

Everything is created inside the dedicated `messaging` schema:

  messaging.event_log        — write-once record of every consumed event.
  messaging.processed_events — per-consumer-group idempotency ledger.

`messaging` is a first-class platform module and owns its migrations here, under
`app/platform/messaging/migrations/`, not under `app/modules/` and not in the
runner's `migrations/versions/`. Its directory must be added to
`version_locations` in `alembic.ini` at cutover — it is not registered today.

The module owns no enums, no functions and no sequences.

`event_log.transaction_id` deliberately carries **no** foreign key. It is an
indexed soft reference to `payments.transactions`: an event log with seven-year
retention must outlive the transaction it describes, and constraining it would
couple the consumer tier's write path to payments. Reproduced here as an indexed
but unconstrained UUID — this is the reason messaging has **no cross-schema
foreign key** and can be applied at any point in the chain.

`event_log.occurred_at` is `VARCHAR(40)`, not `TIMESTAMPTZ`. It is the producer's
own timestamp string, preserved verbatim as received rather than parsed. This is
the only timestamp stored as text anywhere in the platform; it is pre-existing
behaviour and is reproduced, not corrected.

`processed_events` has a composite primary key `(consumer_group, event_id)` and
no surrogate key — each consumer group processes an event exactly once while
other groups still see it.

Column order reproduces the physical order in the pre-squash database. In
`event_log` that puts `id` and `created_at` at positions 10 and 11, because the
original autogenerate emitted the AppendOnlyModel mixin columns after the domain
columns. The ORM declares them first; the database does not.

EXTERNAL DEPENDENCY: `event_log_immutable` executes `public.prevent_mutation()`,
which is created by the shared bootstrap migration a0b1c2d3e4f5 and is not owned by
this module. It is referenced schema-qualified so the reference cannot be broken
by a search_path change.

Constraint names reproduce what the pre-squash database holds. Neither table was
ever renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical; they are spelled out only so the baseline states the full schema
rather than relying on generation rules.

Revision ID: messaging_0001_baseline
Revises: auth_0001_baseline
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "messaging_0001_baseline"
down_revision: str | None = "auth_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "messaging"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── event_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "event_log",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("partition_key", sa.String(length=100), nullable=False),
        # Indexed soft reference to payments.transactions — deliberately no FK.
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("producer", sa.String(length=100), nullable=False),
        # VARCHAR, not TIMESTAMPTZ — the producer's timestamp string, verbatim.
        sa.Column("occurred_at", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="event_log_pkey"),
        # The broker's event id, distinct from the row's surrogate key. Kafka
        # delivers at-least-once, so this is what makes a redelivery detectable.
        sa.UniqueConstraint("event_id", name="event_log_event_id_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_event_log_transaction_id",
        "event_log",
        ["transaction_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ── processed_events ──────────────────────────────────────────────────────
    op.create_table(
        "processed_events",
        sa.Column("consumer_group", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Composite, no surrogate key: each consumer group acts on an event once
        # while other groups still see it.
        sa.PrimaryKeyConstraint(
            "consumer_group", "event_id", name="processed_events_pkey"
        ),
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # event_log is write-once — the Audit Service's durable store, 7-year
    # retention. prevent_mutation() is owned by the shared root migration and
    # lives in public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER event_log_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.event_log
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    # CASCADE reaches both tables, their keys, the index and the trigger in one
    # statement. The schema owns no enums or functions.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
