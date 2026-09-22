"""create settlement.leg_signal_outbox

Epic 2.4 / S5 — transactional outbox for settlement-workflow signals.

`leg_status_update_record` and the `leg_settled` signal that should follow a
settled update were previously coupled by a best-effort Temporal call inside the
normaliser: a transient Temporal outage dropped the signal and the leg only
advanced when the workflow's poll-fallback timed out. This table lets the
normaliser record the signal intent in the same transaction as the status
update; `LegSignalRelay` delivers it with retries.

Mutable (the relay updates status/attempts), so no `prevent_mutation` trigger.
The unique (leg_id, signal_name) is the enqueue idempotency: both the webhook
and poll paths INSERT ... ON CONFLICT DO NOTHING on a settled update.

Revision ID: settlement_0002_signal_outbox
Revises: rails_0003_rail_event_id
Create Date: 2026-09-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# <= 32 chars: alembic_version stores this in a VARCHAR(32).
revision: str = "settlement_0002_signal_outbox"
down_revision: str | None = "rails_0003_rail_event_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "settlement"
TABLE = "leg_signal_outbox"
ENUM_NAME = "leg_signal_status_enum"

_status_enum = postgresql.ENUM(
    "pending", "delivered", name=ENUM_NAME, schema=SCHEMA, create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    _status_enum.create(bind, checkfirst=False)

    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("settlement_id", sa.UUID(), nullable=False),
        sa.Column("leg_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.String(length=255), nullable=False),
        sa.Column("signal_name", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", _status_enum, server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="leg_signal_outbox_pkey"),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            [f"{SCHEMA}.settlement.id"],
            name="leg_signal_outbox_settlement_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["leg_id"],
            [f"{SCHEMA}.settlement_leg.id"],
            name="leg_signal_outbox_leg_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "leg_id", "signal_name", name="uq_leg_signal_outbox_leg_signal"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_leg_signal_outbox_pending",
        TABLE,
        ["created_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_leg_signal_outbox_settlement", TABLE, ["settlement_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_leg_signal_outbox_settlement", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_leg_signal_outbox_pending", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
    _status_enum.drop(op.get_bind(), checkfirst=False)
