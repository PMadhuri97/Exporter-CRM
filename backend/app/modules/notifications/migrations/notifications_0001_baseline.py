"""notifications module baseline — schema `notifications`

Squash of the notifications portion of 41735b67723b (one table, one enum)
together with d4e5f6a7b8c9, which added the `channel` and `recipient` columns,
created `notification_channel_enum`, and relaxed `webhook_url` to nullable.
Expressed as the final desired schema only.

Everything is created inside the dedicated `notifications` schema:

  notifications.notification_events — outbound delivery attempts, per channel.

The module owns no functions, no triggers, no indexes and no sequences.
`notification_events` is deliberately **mutable**: `attempt_count`, `status`,
`last_attempted_at`, `delivered_at` and `failure_reason` are rewritten on every
retry, so unlike audit_events or transaction_status_history it carries no
immutability guard. That is the pre-squash behaviour and is reproduced here.

Column order reproduces the physical order in the pre-squash database. `channel`
and `recipient` are positions 13 and 14 because d4e5f6a7b8c9 appended them to an
existing table — the ORM declares them next to `event_type` and `webhook_url`,
but the database does not, and the database is what this baseline reproduces.

`channel` carries **no** server default. d4e5f6a7b8c9 added it with
`server_default='WEBHOOK'` purely to backfill existing rows and dropped the
default immediately afterwards, so the application must supply the value. The
backfill default is migration history and is deliberately not carried forward.

`webhook_url` is nullable: it is populated only for WEBHOOK-channel rows, and
EMAIL-channel rows use `recipient` instead. Nothing in the database enforces
"exactly one of the two is set" — there is no check constraint on this table,
and none is invented here.

CROSS-SCHEMA DEPENDENCY: `transaction_id` references
`payments.transactions.transaction_id`, created by the payments baseline. That
baseline must be applied first.

Constraint names reproduce what the pre-squash database holds. This table was
never renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical; they are spelled out only so the baseline states the full schema
rather than relying on generation rules.

Revision ID: notifications_0001_baseline
Revises: fx_0001_baseline
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "notifications_0001_baseline"
down_revision: str | None = "fx_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "notifications"
PAYMENTS_SCHEMA = "payments"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: these models do not pass
# values_callable, so SQLAlchemy persists `.name`. The stored labels must match.

webhook_status_enum = postgresql.ENUM(
    "PENDING", "DELIVERED", "FAILED", "EXHAUSTED",
    name="webhook_status_enum",
    schema=SCHEMA,
    create_type=False,
)
notification_channel_enum = postgresql.ENUM(
    "WEBHOOK", "EMAIL",
    name="notification_channel_enum",
    schema=SCHEMA,
    create_type=False,
)

_ENUMS = (webhook_status_enum, notification_channel_enum)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline, so a second column adopting
    # one of these types later cannot trigger a duplicate CREATE TYPE.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── notification_events ───────────────────────────────────────────────────
    op.create_table(
        "notification_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        # Nullable since d4e5f6a7b8c9: only WEBHOOK-channel rows carry a URL.
        sa.Column("webhook_url", sa.String(length=2048), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", webhook_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        # Positions 13 and 14, not 4 and 5: d4e5f6a7b8c9 appended both columns to
        # an existing table. No server default on `channel` — see module docstring.
        sa.Column("channel", notification_channel_enum, nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=True),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{PAYMENTS_SCHEMA}.transactions.transaction_id"],
            name="notification_events_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name="notification_events_pkey"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # CASCADE reaches the table, its key, the foreign key and both enum types in
    # one statement.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
