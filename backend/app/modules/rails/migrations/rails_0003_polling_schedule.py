"""add the polling schedule to rails.leg_submission_record

The Polling Manager's durable queue.

One nullable column and one partial index. There is no separate queue table,
and that is the point: the poll queue must survive a service restart with no
legs lost, so it has to be the same row the submission dispatcher already writes for
every submission attempt. A side table would be a second source of truth for
"is this leg still in flight", which ``leg_submission_record`` already answers.

  polling_next_at   when this leg is next due to be polled. NULL means "not in
                    the poll queue" — which covers a non-polling rail, a leg
                    that has reached a terminal status, and a superseded retry
                    row, in one predicate.

Deliberately NOT added: a column recording that a stuck_leg alert was emitted.
"Alert exactly once, durably" is what ``ledger.idempotency_record`` already
does, and the polling manager registers an internal derived key there instead —
see ``PollingManager._alert_if_stuck``. A second column would have been a second
idempotency mechanism for a platform that has one.

WHY AN UPDATE OF THIS TABLE IS LEGAL
------------------------------------
``rails_0001_baseline`` attaches ``public.prevent_mutation()`` — which rejects
every UPDATE and DELETE — to ``leg_status_update_record`` only. What
``leg_submission_record`` carries is the narrower, field-level
``rails.assert_leg_submission_record_immutable_fields()`` trigger
(``rails_0001_baseline.py:358-373``), which freezes exactly three columns:
``submission_request``, ``submission_response`` and ``submitted_at``. Every
other column on this table is, and always has been, mutable. The
"append-only, all UPDATEs rejected" wording in the model docstring and the
module README described an intent the schema never implemented; both are
corrected alongside this migration rather than left to mislead the next reader.

The submission *record* stays immutable in the sense that matters: what was
sent, what came back, and when, cannot be rewritten. A polling cursor is
neither — it is scheduling state about a row, not a claim about what happened.

EXISTING ROWS
-------------
Backfilled to NULL by the ALTER itself, with no data migration and no table
rewrite (a nullable column with no default is metadata-only from PG 11). That
is correct by construction rather than by convenience: every pre-existing row
predates the polling manager, so its leg is either already terminal or is being
driven by the settlement saga's ``query_rail_status_activity``. Enqueuing them
retroactively would poll rails about legs nothing is waiting on.

Revision ID: rails_0003_polling_schedule
Revises: settlement_0002_signal_outbox
Create Date: 2026-09-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "rails_0003_polling_schedule"
down_revision: str | None = "settlement_0002_signal_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rails"
TABLE = "leg_submission_record"

#: Partial, not total. The due-poll query is always
#: ``WHERE polling_next_at IS NOT NULL AND polling_next_at <= now()``, and this
#: table grows with every submission attempt the platform ever makes while the
#: live queue stays small. A total index would grow with the table forever to
#: serve a scan that only ever touches the in-flight subset; the partial index
#: is sized by the queue instead.
INDEX_NAME = "ix_leg_submission_polling_next_at"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("polling_next_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        INDEX_NAME,
        TABLE,
        ["polling_next_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("polling_next_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE, schema=SCHEMA)
    op.drop_column(TABLE, "polling_next_at", schema=SCHEMA)
