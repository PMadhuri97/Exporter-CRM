"""merge AL-107 feature branch head with AL-103 rails blockchain submission head

Structural, not schema: this revision creates no tables and issues no DDL.  It exists
solely to rejoin two branches of the revision graph into a single head.

After merging ``origin/develop`` (which now carries ``c7ef0b666cf7`` — the three-way
merge of ``0164aa8741c5``, ``644aa8fe5a7e`` and ``rails_0002_blockchain_submission``)
into ``feature/AL-107`` (which already had ``40e7fd9681f3`` — a two-way merge of the
first two), both merge-points became independent heads.  They share all ancestors and
touch disjoint objects, so no reconciliation DDL is required.

Per ``backend/README.md``, merge revisions that span multiple modules live in
``migrations/versions/`` and must not modify migrations already merged into develop.

Revision ID: 5a3b7c9d1e2f
Revises: 40e7fd9681f3, c7ef0b666cf7
Create Date: 2026-08-26
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5a3b7c9d1e2f"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = ("40e7fd9681f3", "c7ef0b666cf7")

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into two heads requires no DDL either."""
