"""merge AL-66 settlement jurisdiction branch with FAILED-status/idempotency-archive branch

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin two branches of the revision graph into a single head.

`a1c2e3f4b5d6` (AL-66's `edd_trigger_jurisdiction` column) and `46d518356296` (the
settlement `FAILED` status, followed by the idempotency-archive table and the
ledger_ro grants reconciliation) were developed in parallel and both descend from
`9f8e7d6c5b4a`. Each is correct on its own, but together they left the chain with two
heads, which makes `alembic upgrade head` fail outright:

    Multiple head revisions are present for given argument 'head'

They touch different schemas and objects, so they do not conflict and no
reconciliation DDL is required — merging the graph is enough.

It lives in the runner rather than in either module's migrations directory: a merge
of two branches belongs to neither (ARCHITECTURE.md §4 — `versions/` holds
platform-level and cross-domain revisions only).

Revision ID: 644aa8fe5a7e
Revises: c9d0e1f2a3b4, a1c2e3f4b5d6
Create Date: 2026-08-24
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "644aa8fe5a7e"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = ("c9d0e1f2a3b4", "a1c2e3f4b5d6")

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into two heads requires no DDL either."""
