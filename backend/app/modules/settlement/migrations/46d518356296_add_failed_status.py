"""add_failed_status

Revision ID: 46d518356296
Revises: 9f8e7d6c5b4a
Create Date: 2026-08-07 13:44:26.708966

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "46d518356296"
down_revision: str | None = "9f8e7d6c5b4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Disable transaction since ALTER TYPE ADD VALUE cannot run inside a transaction block in older postgres.
    # However, Alembic might wrap in transaction by default. We can use op.execute.
    op.execute("ALTER TYPE settlement.settlement_status_enum ADD VALUE IF NOT EXISTS 'failed'")


def downgrade() -> None:
    # Postgres doesn't easily support dropping an enum value.
    pass
