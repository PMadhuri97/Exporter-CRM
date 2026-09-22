"""merge ANER-4.3 case management heads with AL-176 rail performance tracking

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin two branches of the revision graph — Epic 4.3's case management
migrations and AL-176's rail performance tracking migration, both built independently
on top of the 0a772fd562e8 merge point — into a single head.

Revision ID: 87608d21fcb5
Revises: cases_0004_rxil_evidence, rails_0004_rail_perf_hourly
Create Date: 2026-09-18
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "87608d21fcb5"
down_revision: tuple[str, ...] | None = (
    "cases_0004_rxil_evidence",
    "rails_0004_rail_perf_hourly",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
