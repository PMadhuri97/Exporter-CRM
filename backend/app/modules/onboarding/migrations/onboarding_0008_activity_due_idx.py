"""Index `exporter_activity` for the cross-exporter pending/follow-up list
(Exporter CRM Piece 2).

`ExporterContactActivityService.list_pending_activities` answers "everything
pending, across every exporter, for a given person" (or, with no `actor_id`,
a manager's team-wide view) by filtering `exporter_activity` to rows that
carry a `due_at` at all (the append-only log's only stand-in for "this is a
follow-up item, not just a note"), optionally scoped to one `actor_id`, and
ordered by `due_at`. The table's only existing index
(`ix_exporter_activity_customer_id`, `onboarding_0005_exporter_crm`) doesn't
help this access pattern at all — it's keyed on the wrong column for a query
that deliberately spans every `customer_id`.

Partial or on-the-whole-table index?
--------------------------------------
`due_at` is non-NULL only for the minority of rows that are TASK/FOLLOW_UP
entries with a deadline (see `exporter_activity.py`'s module docstring) — a
CALL/MEETING/EMAIL/NOTE almost never carries one. A partial index scoped to
`due_at IS NOT NULL` is therefore both smaller and a better match for this
query's own `WHERE due_at IS NOT NULL` than an index over the whole table
would be, the same reasoning `uq_onboarding_request_active_customer`
(`onboarding_0002_orchestration_schema`) already applies to its own
`WHERE status = 'ACTIVE'`.

The per-actor ("my pending items") case is the one this index is built for:
`(actor_id, due_at)` supports both the `WHERE actor_id = :actor_id` filter
and the `ORDER BY due_at` that follows it in one index scan. The team-wide,
no-`actor_id` case (a manager's view across every actor) cannot use this
index for its own ordering, since `actor_id` isn't fixed in that query's
`WHERE` clause — it falls back to the (still `due_at IS NOT NULL`-scoped, so
still small) partial-index-or-seq-scan Postgres judges cheaper. Acceptable at
today's scale; revisit with a second, `due_at`-only partial index if the
team-wide view becomes a hot path.

Revision ID: onboarding_0008_activity_due_idx
Revises: onboarding_0007_reg_optional
Create Date: 2026-09-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0008_activity_due_idx"
down_revision: str | None = "onboarding_0007_reg_optional"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
_INDEX = "ix_exporter_activity_actor_due_at_pending"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "exporter_activity",
        ["actor_id", "due_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("due_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="exporter_activity", schema=SCHEMA)
