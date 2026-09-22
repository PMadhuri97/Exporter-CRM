"""merge the settlement-version and compliance-limits-action branches

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin two branches of the revision graph into a single head.

`2d3e4f5a6b7c` (settlement optimistic-locking `version` column) and `d8e9f0a1b2c3`
(compliance enhanced-limits check action) were developed in parallel and both descend
from `compliance_0002_std_versions`. Each is correct on its own, but together they left
the chain with two heads, which makes `alembic upgrade head` fail outright:

    Multiple head revisions are present for given argument 'head'

They touch different schemas (`settlement` and `compliance`), so they do not conflict and
no reconciliation DDL is required — merging the graph is enough.

A merge revision rather than a re-parent because both sides were already on `develop`
and may have been applied somewhere; re-parenting an applied revision rewrites history a
deployed database cannot follow. Per the rule in `backend/README.md`, delete this file if
the two branches are ever linearised upstream, so it does not become a branch point of
its own.

It lives in the runner rather than in either module's migrations directory: a merge of
two modules' branches belongs to neither (ARCHITECTURE.md §4 — `versions/` holds
platform-level and cross-domain revisions only).

Revision ID: 9f8e7d6c5b4a
Revises: 2d3e4f5a6b7c, d8e9f0a1b2c3
Create Date: 2026-08-17
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "9f8e7d6c5b4a"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = ("2d3e4f5a6b7c", "d8e9f0a1b2c3")

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into two heads requires no DDL either."""
