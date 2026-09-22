"""idempotency: partial uniqueness so an expired key can be registered again

S3T1. Three schema changes and one data change, all on ledger.idempotency_record.

Uniqueness
----------
(key_value, scope_id) was an unconditional UNIQUE constraint, which meant an expired
record kept occupying its key's slot forever — the key could never be registered again,
and because registration uses ON CONFLICT DO NOTHING the caller was silently handed the
dead record instead of an error. This revision replaces the constraint with a PARTIAL
unique index over the live rows only:

    UNIQUE (key_value, scope_id) WHERE status <> 'expired'

so at most one live record exists per pair while unlimited expired generations sit beside
it for audit. The name is carried over deliberately: existing tests assert on it both in
pg_indexes and in UniqueViolation messages, and a unique index satisfies both.

Note this forces a matching change in the application: ON CONFLICT cannot name a partial
index as a constraint, so registration switched to index inference. Old application code
naming the dropped constraint will fail against this schema — migrate and deploy together.

Sweep index
-----------
ix_idempotency_record_ck_expiry supports the S3T1 time-based expiry job (added in a later
phase; the index is inert until then). Its predicate names key_type = 'customer_key'
because IDK and RR must never expire on a clock — their lifecycle ends when the parent
settlement reaches a terminal state, which S3T2 owns. Putting that rule in the index makes
it structural: a sweep query that drops the key_type filter also loses the index.

Backfill of existing rows
-------------------------
Rows written before S3T1 may carry expires_at IS NULL, because the column existed but
nothing ever computed it. Those rows would never expire and their keys would never become
reusable, so customer-key rows are given the window they should always have had:

    expires_at = first_seen_at + INTERVAL '24 hours'

Anchored on first_seen_at, NEVER on now(). Deriving from migration-execution time would
hand records whose window closed weeks ago a fresh 24 hours; deriving from first_seen_at
correctly states that the window already elapsed, so the first sweep expires them. If this
migration is ever re-run against restored data, the result is identical — now() would not
be.

The literal INTERVAL is deliberate and is NOT the application's configuration mechanism.
A migration is a historical record: it states the window that was in force when it ran, and
must keep producing that same data if replayed. Reading the GitOps key-expiry configuration
here would make the migration's output change whenever that file changes. The configurable
window that S3T1 requirement 3 is about lives in the application and is added in a later
phase.

The backfill deliberately does not touch:
  * rows with a non-NULL expires_at  — a caller-supplied value is not ours to overwrite
  * internal_derived_key / rail_reference rows — they do not expire on a clock at all
  * rows already in 'expired' status — writing a retroactive window onto a terminal record
    would fabricate an audit fact

Revision ID: idem_0001_expiry_reuse_window
Revises: 9f8e7d6c5b4a
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "idem_0001_expiry_reuse_window"
down_revision: str | None = "9f8e7d6c5b4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"
TABLE = "idempotency_record"

UNIQUE_INDEX_NAME = "uq_idempotency_record_key_scope"
CK_SWEEP_INDEX_NAME = "ix_idempotency_record_ck_expiry"

# Kept textually identical to LIVE_RECORD_PREDICATE_SQL / CK_SWEEP_PREDICATE_SQL in
# app/platform/idempotency/models.py. The first of these is also the ON CONFLICT
# index_where in services.py, and Postgres only infers the index when the predicates match.
LIVE_RECORD_PREDICATE = "status <> 'expired'"
CK_SWEEP_PREDICATE = "key_type = 'customer_key' AND status IN ('completed', 'failed')"

# The window in force when this revision was authored. See the module docstring: this is a
# historical constant, not configuration.
HISTORICAL_CK_EXPIRY_WINDOW = "24 hours"

# Exposed at module level so the test suite asserts against the statement this migration
# actually runs, rather than against a copy of it that can drift.
BACKFILL_SQL = f"""
UPDATE {SCHEMA}.{TABLE}
   SET expires_at = first_seen_at + INTERVAL '{HISTORICAL_CK_EXPIRY_WINDOW}'
 WHERE key_type   = 'customer_key'
   AND expires_at IS NULL
   AND status <> 'expired';
"""


def upgrade() -> None:
    op.drop_constraint(UNIQUE_INDEX_NAME, TABLE, schema=SCHEMA, type_="unique")

    op.create_index(
        UNIQUE_INDEX_NAME,
        TABLE,
        ["key_value", "scope_id"],
        schema=SCHEMA,
        unique=True,
        postgresql_where=sa.text(LIVE_RECORD_PREDICATE),
    )

    op.create_index(
        CK_SWEEP_INDEX_NAME,
        TABLE,
        ["expires_at"],
        schema=SCHEMA,
        postgresql_where=sa.text(CK_SWEEP_PREDICATE),
    )

    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    """Restore the unconditional unique constraint, or refuse and say why.

    Once a key has been reused after expiry the table legitimately holds several rows per
    (key_value, scope_id), and an unconditional UNIQUE cannot be recreated over them. The
    only ways through are to delete the expired history — destroying the audit trail this
    revision exists to preserve — or to stop. This stops, and names the rows in the way.

    The backfilled expires_at values are intentionally left in place. There is no record of
    which rows the UPDATE touched versus which already carried a caller-supplied value, so
    nulling them out would destroy real data to undo a derived default.
    """
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT count(*) FROM (
                    SELECT key_value, scope_id
                      FROM {SCHEMA}.{TABLE}
                     GROUP BY key_value, scope_id
                    HAVING count(*) > 1
                ) AS d;
                """
            )
        )
        .scalar_one()
    )

    if duplicates:
        raise RuntimeError(
            f"Cannot downgrade {revision}: {duplicates} (key_value, scope_id) pair(s) have "
            f"more than one row, which the unconditional UNIQUE constraint this downgrade "
            f"restores does not permit. These are expired records kept for audit plus their "
            f"live successors. Decide explicitly whether that history may be deleted, and if "
            f"so remove the expired rows before downgrading."
        )

    op.drop_index(CK_SWEEP_INDEX_NAME, table_name=TABLE, schema=SCHEMA)
    op.drop_index(UNIQUE_INDEX_NAME, table_name=TABLE, schema=SCHEMA)

    op.create_unique_constraint(
        UNIQUE_INDEX_NAME, TABLE, ["key_value", "scope_id"], schema=SCHEMA
    )
