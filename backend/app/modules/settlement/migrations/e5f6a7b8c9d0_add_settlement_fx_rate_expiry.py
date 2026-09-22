"""Add fx_rate_expiry column to settlement table.

Revision ID: e5f6a7b8c9d0
Revises    : 5a3b7c9d1e2f
Create Date: 2026-08-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "5a3b7c9d1e2f"

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "settlement",
        sa.Column("fx_rate_expiry", sa.DateTime(timezone=True), nullable=True),
        schema="settlement",
    )


def downgrade() -> None:
    op.drop_column("settlement", "fx_rate_expiry", schema="settlement")
