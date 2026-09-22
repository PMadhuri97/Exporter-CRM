"""merge the idempotency audit-query branch with develop's settlement-outbox head

Structural, not schema: this revision creates no tables and issues no DDL. It exists
solely to rejoin two branches of the revision graph into a single head.

Both branches descend from `5a3b7c9d1e2f`. One carries the read-only roles, audit
indexes and duplicate-detection log (`d4f2a9c7b118` → `idem_0002_audit_query_indexes`
→ `idem_0003_duplicate_detection`); the other carries develop's fx-rate expiry,
settlement grants, onboarding, customer-review, rail-event and leg-signal-outbox work,
ending at `settlement_0002_signal_outbox`. Left apart they make `alembic upgrade head`
fail outright:

    Multiple head revisions are present for given argument 'head'

NOT FULLY INDEPENDENT. Unlike most merge points, the two branches touch one shared
concern: read access to the settlement schema. `d4f2a9c7b118` provisions a dedicated
`settlement_ro` role, per BUILD.md #15's one-role-per-module rule. `6201c6deb330`, on
the other branch, grants USAGE and SELECT on schema settlement to `ledger_ro`. Both
apply cleanly and neither undoes the other, so the merge needs no reconciliation DDL —
but the resulting database has settlement readable under two roles, and this revision
takes no position on which is intended. That is a design question for the owners of
both changes, not something a merge point should settle by issuing a REVOKE.

A merge revision rather than a re-parent: a database already at either head would
otherwise treat the other branch's revisions as history and skip them. Delete this file
if the branches are ever linearised upstream, so it does not become a branch point of
its own.

Revision ID: b3e8d1f6a902
Revises: idem_0003_duplicate_detection, settlement_0002_signal_outbox
Create Date: 2026-09-10
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b3e8d1f6a902"
# A tuple, not a string: this is what makes the revision a merge point.
down_revision: tuple[str, ...] | None = (
    "idem_0003_duplicate_detection",
    "settlement_0002_signal_outbox",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
