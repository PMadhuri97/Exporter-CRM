"""create rails.rail_performance_hourly table

Operational performance tracking that computes and exposes operational statistics
for each rail over time.

Revision ID: rails_0004_rail_perf_hourly
Revises: settlement_0002_signal_outbox
Create Date: 2026-09-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "rails_0004_rail_perf_hourly"
down_revision: str | None = "0a772fd562e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rails"
TABLE = "rail_performance_hourly"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rail_id", sa.String(length=64), nullable=False),
        sa.Column("hour_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submission_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submission_success_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("settlement_success_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("average_settlement_time_minutes", sa.Float(), nullable=True),
        sa.Column("p95_settlement_time_minutes", sa.Float(), nullable=True),
        sa.Column("failure_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("timeout_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="rail_performance_hourly_pkey"),
        sa.UniqueConstraint("rail_id", "hour_bucket", name="uq_rail_performance_hourly_rail_bucket"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rail_performance_hourly_rail_id",
        TABLE,
        ["rail_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_rail_performance_hourly_hour_bucket",
        TABLE,
        ["hour_bucket"],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_rail_performance_hourly_hour_bucket", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_rail_performance_hourly_rail_id", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
