"""merge the fx_rate_expiry head with the settlement_ro grants head

Structural, not schema: this revision creates no tables and issues no DDL. It
exists solely to rejoin two branches of the revision graph into a single head.

``e5f6a7b8c9d0`` (adds ``settlement.fx_rate_expiry``) and ``6201c6deb330``
(grants the settlement read-only role) were authored independently against the
same parent, ``5a3b7c9d1e2f``, so both became heads the moment they landed
together. They share all ancestors and touch disjoint objects — one adds a
column, the other grants privileges — so no reconciliation DDL is required.

Without this, ``alembic upgrade head`` cannot resolve a single target and fails
with "Multiple head revisions are present", which stops both CI and a clean
local database from migrating at all.

Per ``backend/README.md``, merge revisions that span multiple modules live in
``migrations/versions/`` and must not modify migrations already merged into
develop.

Revision ID: d4f2a1b8c360
Revises: e5f6a7b8c9d0, 6201c6deb330
Create Date: 2026-09-02
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d4f2a1b8c360"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = ("e5f6a7b8c9d0", "6201c6deb330")

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into two heads requires no DDL either."""
