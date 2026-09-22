"""idempotency: append-only log of duplicate detections

Creates ``ledger.duplicate_detection``, one row per idempotency key that was
re-presented and correctly short-circuited. A detection is the mechanism
working, not failing: the operation did not run twice. Violations — keys that
failed to deduplicate — are a different event recorded elsewhere.

Until now a detection produced only a Prometheus counter increment. A counter is
labelled by operation type and key type and cannot carry a key value without an
unbounded cardinality explosion, so it can say how many duplicates an operation
saw but never which keys, whose callers, or when. This table is the individual
history the S4T3 audit query reads; the counter stays and continues to drive the
dashboard.

IMMUTABILITY
The table reuses ``public.prevent_mutation()`` (a0b1c2d3e4f5) rather than
defining a function of its own — the same function twelve other triggers across
eight schemas already use. It rejects both UPDATE and DELETE, which is exactly
this table's requirement.

INDEX, NOT CONCURRENTLY
BUILD.md #14 requires CONCURRENTLY on any table that may hold production data,
and permits the plain form only on a table that is provably small and provably
not yet in production. A table created three statements earlier in this same
migration is empty by construction, so the plain form is correct here and the
autocommit_block dance would buy nothing.

PRIVILEGES
No GRANT is issued. ``b7e4c9a15d20`` set ALTER DEFAULT PRIVILEGES on schema
ledger for the role that runs migrations, so a table created here grants SELECT
to ``ledger_ro`` automatically — which is what lets the audit interface read it
without a new role. The test suite asserts that rather than assuming it.

Revision ID: idem_0003_duplicate_detection
Revises: idem_0002_audit_query_indexes
Create Date: 2026-08-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "idem_0003_duplicate_detection"
down_revision: str | None = "idem_0002_audit_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"
TABLE = "duplicate_detection"
IMMUTABILITY_TRIGGER = "duplicate_detection_immutable"

#: The index S4T3's "duplicates for an operation over a window" query needs.
#: Exposed so the test suite asserts against the name this migration creates
#: rather than against a second copy of it that can drift.
OPERATION_INDEX = "ix_duplicate_detection_operation_detected"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("operation_type", sa.String(length=100), nullable=False),
        # No FK to idempotency_record: the archival job DELETEs from that table
        # after copying to idempotency_archive, and a RESTRICT reference would
        # make the nightly run fail on the first archived key.
        sa.Column("original_request_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("caller_identity", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("time_since_original_ms", sa.BigInteger(), nullable=False),
        sa.Column("returned_result_ref", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )

    op.create_index(
        OPERATION_INDEX, TABLE, ["operation_type", "detected_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_duplicate_detection_key_scope",
        TABLE,
        ["idempotency_key", "scope_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_duplicate_detection_correlation_id", TABLE, ["correlation_id"], schema=SCHEMA
    )

    # Append-only, enforced by the database rather than by convention: a
    # detection is evidence that the idempotency control operated, and evidence
    # that can be edited afterwards is not evidence.
    op.execute(
        f"""
        CREATE TRIGGER {IMMUTABILITY_TRIGGER}
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{TABLE}
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {IMMUTABILITY_TRIGGER} ON {SCHEMA}.{TABLE}")
    op.drop_table(TABLE, schema=SCHEMA)
