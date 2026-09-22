"""create idempotency_record table

Originally authored against the pre-squash schema, where every table lived in
`public` and this revision chained off b6c7d8e9f0a1. AL-550 replaced that history
with one baseline per module, each owning a PostgreSQL schema, so two things
changed here and nothing else:

  * down_revision now points at ledger_0001_baseline, the tail of the baseline chain.
    b6c7d8e9f0a1 no longer exists.
  * the table, its two enums, its indexes, its guard function and its trigger are
    all created in the `ledger` schema rather than `public`, which is what
    keeps the "no application tables in public" guarantee intact.

The DDL itself — columns, constraints, index definitions, trigger behaviour — is
unchanged from the original.

Revision ID: c41c3d57d7cf
Revises: ledger_0001_baseline
Create Date: 2026-08-03 18:53:34.506524

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c41c3d57d7cf'
down_revision: str | None = 'ledger_0001_baseline'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"

# Created explicitly up front with create_type=False, matching the convention in
# payments_0001_baseline.py: it keeps CREATE TYPE out of create_table, so a second
# column adopting either type later cannot emit a duplicate.
idempotency_key_type_enum = postgresql.ENUM(
    'customer_key', 'internal_derived_key', 'rail_reference',
    name='idempotency_key_type_enum', schema=SCHEMA, create_type=False,
)
idempotency_status_enum = postgresql.ENUM(
    'active', 'completed', 'expired', 'failed',
    name='idempotency_status_enum', schema=SCHEMA, create_type=False,
)

_ENUMS = (idempotency_key_type_enum, idempotency_status_enum)


def upgrade() -> None:
    bind = op.get_bind()
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    op.create_table(
        'idempotency_record',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key_value', sa.String(length=256), nullable=False),
        sa.Column('scope_id', sa.String(length=255), nullable=False),
        sa.Column('key_type', idempotency_key_type_enum, nullable=False),
        sa.Column('operation_type', sa.String(length=100), nullable=False),
        sa.Column('status', idempotency_status_enum, nullable=False),
        sa.Column('response_cache', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response_reference', sa.String(length=1024), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correlation_id', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_value', 'scope_id', name='uq_idempotency_record_key_scope'),
        sa.CheckConstraint(
            'response_cache IS NULL OR octet_length(response_cache::text) <= 65536',
            name='ck_response_cache_size'
        ),
        schema=SCHEMA,
    )

    op.create_index(
        'ix_idempotency_record_scope_status', 'idempotency_record',
        ['scope_id', 'status'], schema=SCHEMA,
    )
    op.create_index(
        'ix_idempotency_record_expires_at', 'idempotency_record',
        ['expires_at'], schema=SCHEMA,
    )

    op.execute(f"""
    CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_first_seen_at_update()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.first_seen_at <> OLD.first_seen_at THEN
            RAISE EXCEPTION 'first_seen_at is immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute(f"""
    CREATE TRIGGER trigger_idempotency_first_seen_at_immutable
    BEFORE UPDATE ON {SCHEMA}.idempotency_record
    FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_first_seen_at_update();
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trigger_idempotency_first_seen_at_immutable "
        f"ON {SCHEMA}.idempotency_record;"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_first_seen_at_update();")
    op.drop_index('ix_idempotency_record_expires_at', table_name='idempotency_record', schema=SCHEMA)
    op.drop_index('ix_idempotency_record_scope_status', table_name='idempotency_record', schema=SCHEMA)
    op.drop_table('idempotency_record', schema=SCHEMA)
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.idempotency_status_enum;")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.idempotency_key_type_enum;")
