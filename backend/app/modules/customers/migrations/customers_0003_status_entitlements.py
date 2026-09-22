"""Ongoing due diligence — status, entitlement and attestation tables

A review that concludes a customer should be restricted, with no mechanism to
restrict them, has achieved nothing. These three tables are that mechanism:
the record of how a customer's standing changed, what they are consequently
permitted to do, and the flow through which they confirm or update what they
declared.

`customer_status_history` is append-only. Current status is the latest row, not
a column an operator can overwrite; a suspension edited out of the record is not
a suspension anyone can defend at audit.

`customer_entitlement.approval_request_id` is NOT NULL outright rather than
conditionally required. No entitlement exists without a recorded approval behind
it, including the ones granted at onboarding.

`customer_restriction_level_enum` is reused from customers_0002 rather than
recreated — the ladder a trigger auto-applies and the ladder a status change
records are the same ladder.

Every index here is built with the plain, transactional `CREATE INDEX`. The
constraint requiring `CONCURRENTLY` applies to tables that may hold production
data; these three are created empty in this same migration and hold none.

Revision ID: customers_0003_entitlements
Revises: customers_0002_review_lifecycle
Create Date: 2026-09-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Shorter than the module and table names would suggest: alembic_version
# .version_num is varchar(32), and a longer id fails at the very end of an
# otherwise successful upgrade, when the stamp is written.
revision: str = "customers_0003_entitlements"
down_revision: str | None = "customers_0002_review_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "customers"


# ── Enums ─────────────────────────────────────────────────────────────────────

customer_status_enum = postgresql.ENUM(
    "ACTIVE", "UNDER_REVIEW", "RESTRICTED", "SUSPENDED",
    "PENDING_OFFBOARDING", "OFFBOARDED",
    name="customer_status_enum", schema=SCHEMA, create_type=False,
)
entitlement_type_enum = postgresql.ENUM(
    "CORRIDOR_ACCESS", "TRANSACTION_LIMIT", "AGGREGATE_LIMIT",
    "PRODUCT_ACCESS", "ASSET_ACCESS",
    name="entitlement_type_enum", schema=SCHEMA, create_type=False,
)
entitlement_limit_period_enum = postgresql.ENUM(
    "PER_TRANSACTION", "DAILY", "MONTHLY",
    name="entitlement_limit_period_enum", schema=SCHEMA, create_type=False,
)
entitlement_source_enum = postgresql.ENUM(
    "ONBOARDING", "REVIEW_OUTCOME", "MANUAL_GRANT", "RESTRICTION_APPLIED",
    name="entitlement_source_enum", schema=SCHEMA, create_type=False,
)
attestation_status_enum = postgresql.ENUM(
    "PENDING", "PARTIALLY_RESPONDED", "COMPLETED", "OVERDUE", "ESCALATED",
    name="attestation_status_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    customer_status_enum,
    entitlement_type_enum,
    entitlement_limit_period_enum,
    entitlement_source_enum,
    attestation_status_enum,
)

# Created by customers_0002. Referenced here, never created or dropped.
customer_restriction_level_enum = postgresql.ENUM(
    "MONITORING_ONLY", "NEW_CORRIDOR_BLOCKED", "LIMIT_REDUCED",
    "OUTBOUND_BLOCKED", "FULL_BLOCK",
    name="customer_restriction_level_enum", schema=SCHEMA, create_type=False,
)

MIN_REASON_DETAIL_LENGTH = 20


def upgrade() -> None:
    bind = op.get_bind()

    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── customer_status_history ───────────────────────────────────────────────
    op.create_table(
        "customer_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", customer_status_enum, nullable=True),
        sa.Column("to_status", customer_status_enum, nullable=False),
        sa.Column("restriction_level", customer_restriction_level_enum, nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initiated_by", sa.String(length=255), nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_review_ref", sa.String(length=64), nullable=True),
        sa.Column("customer_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_ref", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_customer_status_history"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_customer_status_history_customer_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_review_ref"],
            [f"{SCHEMA}.customer_review.review_ref"],
            name="fk_customer_status_history_source_review_ref",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"char_length(btrim(reason_detail)) >= {MIN_REASON_DETAIL_LENGTH}",
            name="ck_customer_status_history_reason_detail_substantive",
        ),
        sa.CheckConstraint(
            "(restriction_level IS NOT NULL) = (to_status = 'RESTRICTED')",
            name="ck_customer_status_history_restriction_level_paired",
        ),
        # The `from_status IS NOT NULL` guard is load-bearing: NULL IN (...) is
        # NULL and a CHECK passes on NULL, so without it the first row of a
        # customer's history would slip past this rule entirely.
        sa.CheckConstraint(
            "NOT ("
            " to_status IN ('SUSPENDED', 'RESTRICTED')"
            " OR ("
            "  to_status = 'ACTIVE'"
            "  AND from_status IS NOT NULL"
            "  AND from_status IN ('SUSPENDED', 'RESTRICTED')"
            " )"
            ") OR approval_request_id IS NOT NULL",
            name="ck_customer_status_history_consequential_change_approved",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_customer_status_history_period_ordered",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_customer_status_history_customer_time",
        "customer_status_history",
        ["customer_id", "effective_from"],
        schema=SCHEMA,
    )

    # ── customer_entitlement ──────────────────────────────────────────────────
    op.create_table(
        "customer_entitlement",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entitlement_type", entitlement_type_enum, nullable=False),
        sa.Column("entitlement_key", sa.String(length=100), nullable=True),
        sa.Column("permitted", sa.Boolean(), nullable=False),
        sa.Column("limit_value_minor", sa.BigInteger(), nullable=True),
        sa.Column("limit_currency", sa.String(length=8), nullable=True),
        sa.Column("limit_period", entitlement_limit_period_enum, nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", sa.String(length=255), nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", entitlement_source_enum, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customer_entitlement"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_customer_entitlement_customer_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(limit_value_minor IS NULL) = (limit_currency IS NULL)",
            name="ck_customer_entitlement_limit_paired",
        ),
        sa.CheckConstraint(
            "(limit_value_minor IS NULL) = (limit_period IS NULL)",
            name="ck_customer_entitlement_limit_period_paired",
        ),
        sa.CheckConstraint(
            "limit_value_minor IS NULL OR limit_value_minor >= 0",
            name="ck_customer_entitlement_limit_non_negative",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_customer_entitlement_period_ordered",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_customer_entitlement_lookup",
        "customer_entitlement",
        ["customer_id", "entitlement_type", "active"],
        schema=SCHEMA,
    )

    # ── re_attestation_request ────────────────────────────────────────────────
    op.create_table(
        "re_attestation_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attestation_ref", sa.String(length=64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_ref", sa.String(length=64), nullable=False),
        sa.Column("requested_items", postgresql.JSONB(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_by", sa.Date(), nullable=False),
        sa.Column("reminder_schedule", postgresql.JSONB(), nullable=True),
        sa.Column("status", attestation_status_enum, nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by", sa.String(length=255), nullable=True),
        sa.Column("signatory_authority_verified", sa.Boolean(), nullable=False),
        sa.Column("response_detail", postgresql.JSONB(), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_re_attestation_request"),
        sa.UniqueConstraint("attestation_ref", name="uq_re_attestation_request_ref"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_re_attestation_request_customer_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_ref"],
            [f"{SCHEMA}.customer_review.review_ref"],
            name="fk_re_attestation_request_review_ref",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR ("
            " signatory_authority_verified IS TRUE"
            " AND responded_at IS NOT NULL"
            " AND responded_by IS NOT NULL"
            ")",
            name="ck_re_attestation_request_completion_authorised",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_re_attestation_request_due",
        "re_attestation_request",
        ["status", "due_by"],
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    op.execute(f"""
        CREATE TRIGGER trg_customer_status_history_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.customer_status_history
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.prevent_mutation();
    """)

    # An attestation moves through states, but neither its identity nor when it
    # was asked for may be rewritten afterwards.
    op.execute(f"""
        CREATE TRIGGER trg_re_attestation_request_field_immutability
        BEFORE UPDATE ON {SCHEMA}.re_attestation_request
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set(
            'attestation_ref', 'requested_at'
        );
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_re_attestation_request_field_immutability "
        f"ON {SCHEMA}.re_attestation_request;"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_customer_status_history_append_only "
        f"ON {SCHEMA}.customer_status_history;"
    )

    op.drop_table("re_attestation_request", schema=SCHEMA)
    op.drop_table("customer_entitlement", schema=SCHEMA)
    op.drop_table("customer_status_history", schema=SCHEMA)

    # customer_restriction_level_enum belongs to customers_0002 and is left for
    # that migration's downgrade to drop.
    bind = op.get_bind()
    for pg_enum in reversed(_ENUMS):
        pg_enum.drop(bind, checkfirst=False)
