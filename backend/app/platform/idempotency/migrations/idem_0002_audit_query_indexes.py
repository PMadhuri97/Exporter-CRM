"""idempotency: index the scope-and-date access path on both registry tables

The audit query interface reconstructs what happened during a settlement by
asking for every record in a family of scopes, optionally bounded by date. That
predicate — ``scope_id IN (...) AND first_seen_at BETWEEN ... `` — runs against
the hot table and the archive as one union, and neither side could serve it.

The hot table has ``ix_idempotency_record_scope_status`` on (scope_id, status),
whose leading column matches but which cannot help with the date bound or the
ordering, so every matching scope is read and then sorted. The archive is worse:
it carries indexes on (key_value, scope_id) and archived_at only, so a query by
scope alone has no usable leading column and reads the whole table. That is the
side which grows without bound — the hot table is swept nightly, the archive
never is.

Both get (scope_id, first_seen_at). Equality on the leading column, range and
ordering on the second, which is the shape the planner wants for this query and
also lets the ORDER BY be satisfied by the index rather than by a sort.

WHY NOT operation_type
----------------------
The other query the epic asks for — duplicates within a time window, by
operation type — is not implemented, because the registry stores one row per key
and records nothing about a key being re-presented. An index has a real write
cost on every insert, so the one that would serve that query is deliberately
left until the query exists.

CONCURRENTLY
------------
Both tables may hold production data, so the plain form is not available: it
takes ACCESS EXCLUSIVE for the whole build and blocks every read and write on
the table for the duration. The concurrent form cannot run inside a transaction
block, hence ``autocommit_block()``.

A failed concurrent build leaves an INVALID index behind, which will not be used
by the planner and will not be replaced by a retry — so ``downgrade()`` drops by
name IF EXISTS, making the retry path simply "downgrade, upgrade" rather than
manual cleanup.

Revision ID: idem_0002_audit_query_indexes
Revises: d4f2a9c7b118
Create Date: 2026-08-28
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "idem_0002_audit_query_indexes"
down_revision: str | None = "d4f2a9c7b118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"

#: (index name, table, columns). Exposed at module level so the test suite
#: asserts against the indexes this revision actually creates rather than
#: against a second copy of the list that can drift from it.
AUDIT_QUERY_INDEXES = (
    ("ix_idempotency_record_scope_first_seen", "idempotency_record", ["scope_id", "first_seen_at"]),
    (
        "ix_idempotency_archive_scope_first_seen",
        "idempotency_archive",
        ["scope_id", "first_seen_at"],
    ),
)


def upgrade() -> None:
    # Outside the surrounding transaction: CREATE INDEX CONCURRENTLY is rejected
    # inside a transaction block.
    with op.get_context().autocommit_block():
        for name, table, columns in AUDIT_QUERY_INDEXES:
            op.create_index(
                name,
                table,
                columns,
                schema=SCHEMA,
                postgresql_concurrently=True,
                if_not_exists=True,
            )


def downgrade() -> None:
    # IF EXISTS, because a failed concurrent build leaves an INVALID index that a
    # retry will not overwrite. Dropping by name is what makes the retry clean.
    with op.get_context().autocommit_block():
        for name, table, _columns in reversed(AUDIT_QUERY_INDEXES):
            op.drop_index(
                name,
                table_name=table,
                schema=SCHEMA,
                postgresql_concurrently=True,
                if_exists=True,
            )
