"""Add version column for optimistic locking on settlement transitions.

Revision ID: 2d3e4f5a6b7c
Revises    : compliance_0002_std_versions
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d3e4f5a6b7c"
down_revision: str | None = "d8e9f0a1b2c3"

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "settlement",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="settlement",
    )


def downgrade() -> None:
    op.drop_column("settlement", "version", schema="settlement")
