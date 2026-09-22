"""Add NOT_SUPPORTED to KybNormalisedResult

Revision ID: 45ede5960506
Revises: onboarding_0002_orchestration
Create Date: 2026-09-11 18:03:45.322045

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "45ede5960506"
down_revision: str | None = "onboarding_0002_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE onboarding.kyb_normalised_result_enum ADD VALUE IF NOT EXISTS 'NOT_SUPPORTED'"
    )


def downgrade() -> None:
    pass
