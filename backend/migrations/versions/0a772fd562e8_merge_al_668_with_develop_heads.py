"""merge AL-668 heads with develop heads

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin multiple branches of the revision graph into a single head.

Revision ID: 0a772fd562e8
Revises: audit_0003_event_type_index, e849a8d1c41e, onboarding_0003_kyb_vendors, rails_0003_polling_schedule
Create Date: 2026-09-15
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0a772fd562e8"
down_revision: tuple[str, ...] | None = (
    "audit_0003_event_type_index",
    "e849a8d1c41e",
    "onboarding_0003_kyb_vendors",
    "rails_0003_polling_schedule",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
