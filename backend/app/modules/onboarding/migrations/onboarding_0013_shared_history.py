"""Generalise the lifecycle history table into the shared CRM history log.

`exporter_lifecycle_history` records one thing today: a move of
`exporter_profile.lifecycle_status`. The target model has a company moving along
a journey **and** three gauges that move independently **and** any number of
deals with stages of their own, and section 3.1 of the architecture requires all
of it to be readable as one story. Five append-only tables with five shapes
cannot answer that question; one table with a `dimension` can.

Three columns:

* ``dimension`` — which row of the model changed (``journey``,
  ``qualification``, ``conversation``, ``background_check``, ``deal``,
  ``marker``, ``profile``, ``verification``). The contract in
  ``docs/contracts/history-row.md`` owns the list.
* ``deal_id`` — the deal a row is about, when it is about one.
* ``reason`` — why, in the actor's words. Several moves in section 3 require
  one; the column stays nullable because most do not, and a NOT NULL column
  would make writers invent text.

**Why the backfill is a column default and not an UPDATE.**
``trg_exporter_lifecycle_history_append_only`` fires ``BEFORE UPDATE OR DELETE``
and raises unconditionally, so ``UPDATE ... SET dimension = 'journey'`` would be
refused by the table's own guard — correctly, since that guard is the whole
point of the table. Dropping the trigger to run the backfill and recreating it
afterwards would leave a window in which the history is editable, during a
migration, which is exactly the property that must never be false.

``ADD COLUMN ... NOT NULL DEFAULT 'journey'`` avoids the problem outright: it is
DDL, so no row trigger fires, and since Postgres 11 it fills existing rows
without rewriting the table. Every one of the rows that exists today is a
journey move, so ``journey`` is the correct value for all of them, not a
placeholder.

The default is then **dropped**. Keeping it would mean a writer that forgot
``dimension`` silently recorded a journey move — the failure this column exists
to prevent. After the drop, an insert must say which dimension it is, and
``ExporterLifecycleHistory`` passes it explicitly.

**No foreign key** (decision U3). ``customer_id`` stays a bare indexed uuid.
Migration 0014 (Dev 2) recreates the CRM's own tables and already owns the real
links for contacts, activities and screening items; the history link goes in
with them. Adding it here would force 0014 to drop the constraint before
recreating ``exporter_profile`` and re-add it afterwards, for no gain — both
land in the same week. Measured at the time of writing: 1,498 history rows, zero
orphans, so the constraint will apply cleanly when 0014 adds it.

**Nothing is renamed.** ``from_status``/``to_status`` now carry values that are
not statuses of the journey, and ``from_value``/``to_value`` would read better.
Renaming them is not done here: it would touch every writer and reader in a
migration whose job is to add three columns, and the contract does not ask for
it.

No ``ALTER TYPE`` in this migration, so no ``autocommit_block()`` and none of
the split-state risk that comes with it (``migrations/README.md``, item 2). The
history columns are deliberately ``varchar``, never enums, so that a value added
to a gauge never needs a migration against this table before it can be recorded.

Revision ID: onboarding_0013_shared_history
Revises: onboarding_0012_risk_critical
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0013_shared_history"
down_revision: str | None = "onboarding_0012_risk_critical"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_lifecycle_history"

#: What every row written before this migration is. All of them record a move
#: of `exporter_profile.lifecycle_status`, which is the journey.
JOURNEY = "journey"

DIMENSION_INDEX = "ix_exporter_lifecycle_history_dimension_recent"
DEAL_INDEX = "ix_exporter_lifecycle_history_deal_recent"


def upgrade() -> None:
    # ── dimension ────────────────────────────────────────────────────────────
    # NOT NULL with a default in one statement: DDL, so the append-only trigger
    # does not fire, and existing rows are filled without a table rewrite.
    op.add_column(
        TABLE,
        sa.Column(
            "dimension",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text(f"'{JOURNEY}'"),
        ),
        schema=SCHEMA,
    )
    # Drop the default so a future insert cannot silently become a journey row.
    op.alter_column(TABLE, "dimension", server_default=None, schema=SCHEMA)

    # ── deal_id ──────────────────────────────────────────────────────────────
    # Bare uuid, like `customer_id`: the deal table does not exist yet (0018),
    # and the FK story for this table is 0014's (decision U3).
    op.add_column(
        TABLE,
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )

    # ── reason ───────────────────────────────────────────────────────────────
    # Text, not varchar(n): a compliance reason for flagging a company is
    # prose, and truncating it at an arbitrary limit loses the part that
    # mattered. The service enforces a reason where section 3 requires one.
    op.add_column(TABLE, sa.Column("reason", sa.Text(), nullable=True), schema=SCHEMA)

    # ── indexes ──────────────────────────────────────────────────────────────
    # One company's history filtered to one dimension — what a gauge panel asks
    # for. Column order and direction mirror the query exactly, so Postgres
    # satisfies the ordering from the index instead of sorting.
    op.create_index(
        DIMENSION_INDEX,
        TABLE,
        [
            "customer_id",
            "dimension",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        schema=SCHEMA,
    )
    # One deal's history. Partial, because `deal_id` is NULL on every
    # company-level row and always will be on most of them — indexing those
    # NULLs would double the index for entries no query can use.
    op.create_index(
        DEAL_INDEX,
        TABLE,
        ["deal_id", sa.text("created_at DESC")],
        schema=SCHEMA,
        postgresql_where=sa.text("deal_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the three columns and the two indexes.

    **Lossy for anything but a journey row.** Dropping `dimension` discards
    which gauge each row described, and dropping `reason` discards why a
    compliance decision was taken — neither is recoverable from what remains.
    While `journey` is the only dimension being written this is a clean
    reversal; once another developer's writer has run it is not. Downgrade only
    if you mean it.

    The append-only trigger and the three original indexes are untouched
    throughout, in both directions.
    """
    op.drop_index(DEAL_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_index(DIMENSION_INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_column(TABLE, "reason", schema=SCHEMA)
    op.drop_column(TABLE, "deal_id", schema=SCHEMA)
    op.drop_column(TABLE, "dimension", schema=SCHEMA)
