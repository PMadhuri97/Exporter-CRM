"""merge the idempotency expiry-reuse and ledger_ro grants-reconcile branches

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin two branches of the revision graph into a single head.

`idem_0001_expiry_reuse_window` (S3T1 partial uniqueness on `ledger.idempotency_record`)
and `c9d0e1f2a3b4` (ledger_ro grants reconcile) were developed in parallel and both
descend from `9f8e7d6c5b4a`. Each is correct on its own, but together they left the chain
with two heads, which makes `alembic upgrade head` fail outright:

    Multiple head revisions are present for given argument 'head'

They touch unrelated objects — indexes on `ledger.idempotency_record` on one side, role
grants on schema `ledger` on the other — so they do not conflict and no reconciliation
DDL is required. Merging the graph is enough.

A merge revision rather than a re-parent, for the reason `c9d0e1f2a3b4` documents about
itself: Alembic walks the chain forward from the recorded version, so re-parenting
`idem_0001_expiry_reuse_window` onto `c9d0e1f2a3b4` would leave any database already at
`idem_0001_expiry_reuse_window` treating the grants reconcile as history and never
running it. That is precisely the silent-skip failure `c9d0e1f2a3b4` exists to repair,
and re-parenting it here would reintroduce it. Per the rule in `backend/README.md`,
delete this file if the two branches are ever linearised upstream, so it does not become
a branch point of its own.

It lives in the runner rather than in either migrations directory: a merge of a platform
module's branch with a cross-domain one belongs to neither (ARCHITECTURE.md §4 —
`versions/` holds platform-level and cross-domain revisions only).

Revision ID: 0164aa8741c5
Revises: idem_0001_expiry_reuse_window, c9d0e1f2a3b4
Create Date: 2026-08-24
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0164aa8741c5"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = ("idem_0001_expiry_reuse_window", "c9d0e1f2a3b4")

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into two heads requires no DDL either."""
