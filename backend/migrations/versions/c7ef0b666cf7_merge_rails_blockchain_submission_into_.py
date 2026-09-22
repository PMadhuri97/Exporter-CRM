"""merge the rails blockchain-submission branch into the two develop heads

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin three branches of the revision graph into a single head.

All three descend from `c9d0e1f2a3b4` (ledger_ro grants reconcile) and were developed in
parallel:

  * `rails_0002_blockchain_submission` — Epic 2.3 / S2T3, `rails.blockchain_submission`.
  * `0164aa8741c5` — merge of S3T1 idempotency expiry-reuse (partial uniqueness on
    `ledger.idempotency_record`) with the grants reconcile.
  * `644aa8fe5a7e` — merge of AL-66 settlement EDD trigger jurisdiction with the same.

Two of them were already a fork before this branch merged develop: `0164aa8741c5` and
`644aa8fe5a7e` are each a merge point, but nothing joined them to each other, so develop
carried two heads on its own. Merging AL-103's rails branch in made a third. Alembic
takes any number of parents, so one revision closes all three rather than stacking two:

    Multiple head revisions are present for given argument 'head'

They touch disjoint objects — a new table and indexes in schema `rails`, indexes on
`ledger.idempotency_record`, and trigger/column work in schema `settlement` — so there is
nothing to reconcile between them and merging the graph is enough.

A merge revision rather than a re-parent, for the reason `0164aa8741c5` documents at
length: Alembic walks the chain forward from the recorded version, so re-parenting a head
onto another would leave any database already at that head treating the other branch as
history and never running it. Per the rule in `backend/README.md`, delete this file if
these branches are ever linearised upstream, so it does not become a branch point of its
own.

It lives in the runner rather than in any module's migrations directory: a merge spanning
a module branch and two cross-domain ones belongs to none of them (ARCHITECTURE.md §4 —
`versions/` holds platform-level and cross-domain revisions only).

Revision ID: c7ef0b666cf7
Revises: 0164aa8741c5, 644aa8fe5a7e, rails_0002_blockchain_submission
Create Date: 2026-08-25
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c7ef0b666cf7"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = (
    "0164aa8741c5",
    "644aa8fe5a7e",
    "rails_0002_blockchain_submission",
)

branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: a merge point joins the graph, it does not change the schema."""


def downgrade() -> None:
    """No-op: splitting back into three heads requires no DDL either."""
