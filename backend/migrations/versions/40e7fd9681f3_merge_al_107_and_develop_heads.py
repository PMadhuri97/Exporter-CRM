"""merge AL-107 idempotency-expiry and develop AL-66-settlement-jurisdiction heads

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin two branches of the revision graph into a single head.

`0164aa8741c5` (merge of S3T1 partial uniqueness + ledger_ro grants reconcile) was
created on feature/AL-107. `644aa8fe5a7e` (merge of AL-66 settlement jurisdiction +
FAILED-status/idempotency-archive) was created on develop. Merging feature/AL-107
into develop brings both into the same tree with two heads, which makes
`alembic upgrade head` fail outright:

    Multiple head revisions are present for given argument 'head'

They touch unrelated objects — idempotency indexes on one side, settlement columns
and role grants on the other — so they do not conflict and no reconciliation DDL is
required. Merging the graph is enough.

Revision ID: 40e7fd9681f3
Revises: 0164aa8741c5, 644aa8fe5a7e
Create Date: 2026-08-25
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "40e7fd9681f3"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = ("0164aa8741c5", "644aa8fe5a7e")

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into two heads requires no DDL either."""
