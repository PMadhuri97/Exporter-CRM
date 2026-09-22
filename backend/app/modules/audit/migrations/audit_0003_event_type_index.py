"""audit: index audit_events on (event_type, created_at)

Two reads filter ``audit.audit_events`` by event type and page it newest first: the
audit API's own filtered feed (``AuditEventRepository.query``), and the idempotency
violations query, which asks for one event type out of a table every module writes
to. The table had indexes on ``correlation_id`` and ``synced_to_sink_at`` only, so
both reads scanned the whole log and sorted it on every page.

This table is the platform-wide compliance record and is retained for seven years —
it only grows. (event_type, created_at) gives an equality match on the leading
column and serves ``ORDER BY created_at DESC`` by walking the index backwards, so a
page costs its own size rather than the log's.

CONCURRENTLY
BUILD.md #14: the table holds production data, and the plain form takes ACCESS
EXCLUSIVE for the whole build, blocking every audit write in the platform for its
duration. It cannot run in a transaction, hence ``autocommit_block()``. A failed
concurrent build leaves an INVALID index that a retry will not replace, so the
downgrade drops by name IF EXISTS — the retry is then just downgrade, upgrade.

Revision ID: audit_0003_event_type_index
Revises: b3e8d1f6a902
Create Date: 2026-09-10
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "audit_0003_event_type_index"
down_revision: str | None = "b3e8d1f6a902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "audit"
TABLE = "audit_events"
#: Exposed so the test suite asserts against the index this revision creates.
INDEX_NAME = "ix_audit_events_event_type_created_at"
INDEX_COLUMNS = ["event_type", "created_at"]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX_NAME,
            TABLE,
            INDEX_COLUMNS,
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX_NAME,
            table_name=TABLE,
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
