"""create idempotency_archive table

Adds the ``ledger.idempotency_archive`` table that mirrors every column in
``ledger.idempotency_record`` plus an ``archived_at`` timestamp written at move
time. The archive table is the landing zone for records moved out of the hot
registry by the nightly archival job (S3T3).

No unique constraint on ``(key_value, scope_id)`` — a single key may appear more
than once in the archive because the same key can be re-used after expiry (a new
record is created in the hot table, the old one is eventually archived).

A DELETE-blocking trigger prevents accidental removal of archived records at the
database level, matching the immutability contract of the GCS audit bucket. The
``public.prevent_mutation()`` function is NOT reused: that function blocks both
UPDATE and DELETE, but the archive table needs UPDATE (``archived_at`` might be
backfilled in a future migration) while only DELETE must be forbidden.

Revision ID: a1b2c3d4e5f6
Revises: 46d518356296
Create Date: 2026-08-19
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "46d518356296"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "c41c3d57d7cf"


SCHEMA = "ledger"

# Reference the existing enums with create_type=False — they are already created
# by c41c3d57d7cf and must not be duplicated.
idempotency_key_type_enum = postgresql.ENUM(
    "customer_key", "internal_derived_key", "rail_reference",
    name="idempotency_key_type_enum", schema=SCHEMA, create_type=False,
)
idempotency_status_enum = postgresql.ENUM(
    "active", "completed", "expired", "failed",
    name="idempotency_status_enum", schema=SCHEMA, create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "idempotency_archive",
        # Same columns as idempotency_record …
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key_value", sa.String(length=256), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("key_type", idempotency_key_type_enum, nullable=False),
        sa.Column("operation_type", sa.String(length=100), nullable=False),
        sa.Column("status", idempotency_status_enum, nullable=False),
        sa.Column("response_cache", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_reference", sa.String(length=1024), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # … plus the archival timestamp
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    # Index for audit look-ups: "find all archived records for this key + scope"
    op.create_index(
        "ix_idempotency_archive_key_scope",
        "idempotency_archive",
        ["key_value", "scope_id"],
        schema=SCHEMA,
    )

    # Index for retention queries: "find all archives older than N years"
    op.create_index(
        "ix_idempotency_archive_archived_at",
        "idempotency_archive",
        ["archived_at"],
        schema=SCHEMA,
    )

    # DELETE-blocking trigger — archive records are immutable once written.
    op.execute(f"""
    CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_archive_delete()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'DELETE on idempotency_archive is forbidden — records are retained for audit compliance';
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute(f"""
    CREATE TRIGGER trigger_idempotency_archive_no_delete
    BEFORE DELETE ON {SCHEMA}.idempotency_archive
    FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_archive_delete();
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trigger_idempotency_archive_no_delete "
        f"ON {SCHEMA}.idempotency_archive;"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_archive_delete();")
    op.drop_index("ix_idempotency_archive_archived_at", table_name="idempotency_archive", schema=SCHEMA)
    op.drop_index("ix_idempotency_archive_key_scope", table_name="idempotency_archive", schema=SCHEMA)
    op.drop_table("idempotency_archive", schema=SCHEMA)
