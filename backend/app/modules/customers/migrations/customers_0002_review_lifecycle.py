"""Ongoing due diligence — review lifecycle tables

Epic 4.1 verifies a business once, at onboarding. Nothing it establishes stays
true: directors resign, ownership changes hands, a company in good standing is
struck off. These five tables carry the schedule that decides when to look
again, the events that force an unscheduled look, the review itself, the
baseline it compares against, and the differences it finds.

Table names are singular and reproduce the epic data model verbatim, following
the precedent set by the onboarding orchestration schema. This is a known
deviation from the pluralised style of the older financial tables, which were
judged too risky to rename.

Three design points worth stating here rather than rediscovering in review:

`customer_baseline_snapshot` and `detected_change` are append-only, guarded by
`public.prevent_mutation()`. A review compares against a snapshot rather than
against the live customer record, because the live record moves for reasons that
are not findings, and because evidence that can be edited is not evidence.

`customer_review.baseline_snapshot_ref` is a foreign key, not merely NOT NULL. A
ref that points at no snapshot is worth no more than a null one.

Every index here is built with the plain, transactional `CREATE INDEX`. The
constraint requiring `CONCURRENTLY` applies to tables that may hold production
data; these five are created empty in this same migration and hold none.

Revision ID: customers_0002_review_lifecycle
Revises: onboarding_0002_orchestration
Create Date: 2026-09-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "customers_0002_review_lifecycle"
down_revision: str | None = "onboarding_0002_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "customers"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Stored labels are the uppercase Python member names: these models do not pass
# values_callable, so SQLAlchemy persists `.name`.
#
# `review_risk_rating_enum` is deliberately distinct from the existing
# `customers.risk_rating_enum`. That one ends in ENHANCED; the review ladder ends
# in PROHIBITED. Reusing it would let a review store a band it cannot act on.

review_risk_rating_enum = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "PROHIBITED",
    name="review_risk_rating_enum", schema=SCHEMA, create_type=False,
)
review_schedule_status_enum = postgresql.ENUM(
    "SCHEDULED", "IN_PROGRESS", "OVERDUE", "SUSPENDED_PENDING_OFFBOARDING",
    name="review_schedule_status_enum", schema=SCHEMA, create_type=False,
)
review_trigger_severity_enum = postgresql.ENUM(
    "CRITICAL", "HIGH", "MEDIUM", "LOW",
    name="review_trigger_severity_enum", schema=SCHEMA, create_type=False,
)
review_trigger_action_enum = postgresql.ENUM(
    "IMMEDIATE_REVIEW", "ACCELERATE_SCHEDULE", "FLAG_AT_NEXT_REVIEW", "NO_ACTION",
    name="review_trigger_action_enum", schema=SCHEMA, create_type=False,
)
customer_restriction_level_enum = postgresql.ENUM(
    "MONITORING_ONLY", "NEW_CORRIDOR_BLOCKED", "LIMIT_REDUCED",
    "OUTBOUND_BLOCKED", "FULL_BLOCK",
    name="customer_restriction_level_enum", schema=SCHEMA, create_type=False,
)
customer_review_type_enum = postgresql.ENUM(
    "PERIODIC", "EVENT_TRIGGERED", "AD_HOC", "REMEDIATION_FOLLOWUP",
    name="customer_review_type_enum", schema=SCHEMA, create_type=False,
)
customer_review_status_enum = postgresql.ENUM(
    "INITIATED", "VERIFICATION_RUNNING", "AWAITING_CUSTOMER", "UNDER_ASSESSMENT",
    "PENDING_APPROVAL", "COMPLETED", "CANCELLED",
    name="customer_review_status_enum", schema=SCHEMA, create_type=False,
)
customer_review_outcome_enum = postgresql.ENUM(
    "NO_CHANGE", "RATING_CHANGED", "RESTRICTED", "SUSPENDED",
    "REFERRED_TO_OFFBOARDING", "REMEDIATION_REQUIRED",
    name="customer_review_outcome_enum", schema=SCHEMA, create_type=False,
)
baseline_snapshot_reason_enum = postgresql.ENUM(
    "ONBOARDING_COMPLETED", "REVIEW_COMPLETED", "REMEDIATION_COMPLETED", "MANUAL_CAPTURE",
    name="baseline_snapshot_reason_enum", schema=SCHEMA, create_type=False,
)
detected_change_type_enum = postgresql.ENUM(
    "ADDED", "REMOVED", "MODIFIED", "UNCHANGED_BUT_REVERIFIED",
    name="detected_change_type_enum", schema=SCHEMA, create_type=False,
)
detected_change_materiality_enum = postgresql.ENUM(
    "MATERIAL", "NOTABLE", "IMMATERIAL",
    name="detected_change_materiality_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    review_risk_rating_enum,
    review_schedule_status_enum,
    review_trigger_severity_enum,
    review_trigger_action_enum,
    customer_restriction_level_enum,
    customer_review_type_enum,
    customer_review_status_enum,
    customer_review_outcome_enum,
    baseline_snapshot_reason_enum,
    detected_change_type_enum,
    detected_change_materiality_enum,
)

MIN_OUTCOME_RATIONALE_LENGTH = 50

# Column-level immutability. The shared public.prevent_mutation() rejects a whole
# statement; this rejects a change to a named column while leaving the rest of
# the row writable, which is what a record that transitions through states but
# must not have its identity or its completion rewritten needs. A column is
# guarded only once it holds a value, so `completed_at` may be set once and
# never again.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION {schema}.prevent_field_mutation_when_set()
RETURNS TRIGGER AS $func$
DECLARE
    col_name text;
    old_json jsonb := to_jsonb(OLD);
    new_json jsonb := to_jsonb(NEW);
BEGIN
    FOR i IN 0 .. array_upper(TG_ARGV, 1) LOOP
        col_name := TG_ARGV[i];
        IF jsonb_typeof(old_json->col_name) IS DISTINCT FROM 'null'
           AND old_json->col_name IS DISTINCT FROM new_json->col_name THEN
            RAISE EXCEPTION 'Column % is immutable once set.', col_name;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$func$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()

    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    op.execute(_IMMUTABILITY_FUNCTION.format(schema=SCHEMA))

    # ── review_trigger_definition ─────────────────────────────────────────────
    # First: customer_review carries a foreign key to its trigger_code.
    op.create_table(
        "review_trigger_definition",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("trigger_code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_epic", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("severity", review_trigger_severity_enum, nullable=False),
        sa.Column("review_action", review_trigger_action_enum, nullable=False),
        sa.Column("auto_restrict", sa.Boolean(), nullable=False),
        sa.Column("restriction_level", customer_restriction_level_enum, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_trigger_definition"),
        sa.UniqueConstraint("trigger_code", name="uq_review_trigger_definition_code"),
        sa.CheckConstraint(
            "auto_restrict = (restriction_level IS NOT NULL)",
            name="ck_review_trigger_definition_restriction_paired",
        ),
        schema=SCHEMA,
    )

    # ── customer_baseline_snapshot ────────────────────────────────────────────
    op.create_table(
        "customer_baseline_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("snapshot_ref", sa.String(length=64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_reason", baseline_snapshot_reason_enum, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_review_ref", sa.String(length=64), nullable=True),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("registered_identifiers", postgresql.JSONB(), nullable=True),
        sa.Column("registered_address", postgresql.JSONB(), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("registration_status", sa.String(length=50), nullable=True),
        sa.Column("directors", postgresql.JSONB(), nullable=True),
        sa.Column("beneficial_owners", postgresql.JSONB(), nullable=True),
        sa.Column("declared_sectors", postgresql.JSONB(), nullable=True),
        sa.Column("declared_corridors", postgresql.JSONB(), nullable=True),
        sa.Column("declared_volumes", postgresql.JSONB(), nullable=True),
        sa.Column("risk_rating", review_risk_rating_enum, nullable=False),
        sa.Column("screening_status", sa.String(length=50), nullable=True),
        sa.Column("entitlements_snapshot", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_customer_baseline_snapshot"),
        sa.UniqueConstraint("snapshot_ref", name="uq_customer_baseline_snapshot_ref"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_customer_baseline_snapshot_customer_id",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_customer_baseline_snapshot_customer_time",
        "customer_baseline_snapshot",
        ["customer_id", "captured_at"],
        schema=SCHEMA,
    )

    # ── customer_review ───────────────────────────────────────────────────────
    op.create_table(
        "customer_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("review_ref", sa.String(length=64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_type", customer_review_type_enum, nullable=False),
        sa.Column("trigger_code", sa.String(length=100), nullable=True),
        sa.Column("trigger_event_detail", postgresql.JSONB(), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initiated_by", sa.String(length=255), nullable=False),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", customer_review_status_enum, nullable=False),
        sa.Column("baseline_snapshot_ref", sa.String(length=64), nullable=False),
        sa.Column("verification_result_refs", postgresql.JSONB(), nullable=True),
        sa.Column("changes_detected", postgresql.JSONB(), nullable=True),
        sa.Column("material_change_count", sa.Integer(), nullable=False),
        sa.Column("risk_rating_before", review_risk_rating_enum, nullable=False),
        sa.Column("risk_rating_after", review_risk_rating_enum, nullable=True),
        sa.Column("rating_changed", sa.Boolean(), nullable=False),
        sa.Column("outcome", customer_review_outcome_enum, nullable=True),
        sa.Column("outcome_rationale", sa.Text(), nullable=True),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_customer_review"),
        sa.UniqueConstraint("review_ref", name="uq_customer_review_ref"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_customer_review_customer_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_code"],
            [f"{SCHEMA}.review_trigger_definition.trigger_code"],
            name="fk_customer_review_trigger_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_snapshot_ref"],
            [f"{SCHEMA}.customer_baseline_snapshot.snapshot_ref"],
            name="fk_customer_review_baseline_snapshot_ref",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "review_ref ~ '^REV-[0-9]{4}-[0-9]+$'",
            name="ck_customer_review_ref_format",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR ("
            " outcome IS NOT NULL"
            f" AND char_length(btrim(outcome_rationale)) >= {MIN_OUTCOME_RATIONALE_LENGTH}"
            ")",
            name="ck_customer_review_completion_recorded",
        ),
        sa.CheckConstraint(
            "outcome IS NULL"
            " OR outcome NOT IN ('SUSPENDED', 'RESTRICTED', 'REFERRED_TO_OFFBOARDING')"
            " OR approval_request_id IS NOT NULL",
            name="ck_customer_review_consequential_outcome_approved",
        ),
        sa.CheckConstraint(
            "(review_type = 'EVENT_TRIGGERED' AND trigger_code IS NOT NULL)"
            " OR (review_type = 'PERIODIC' AND trigger_code IS NULL)"
            " OR review_type IN ('AD_HOC', 'REMEDIATION_FOLLOWUP')",
            name="ck_customer_review_trigger_code_consistent",
        ),
        sa.CheckConstraint(
            "CASE WHEN risk_rating_after IS NULL"
            " THEN rating_changed = false"
            " ELSE rating_changed = (risk_rating_before IS DISTINCT FROM risk_rating_after)"
            " END",
            name="ck_customer_review_rating_changed_derived",
        ),
        sa.CheckConstraint(
            "material_change_count >= 0",
            name="ck_customer_review_material_change_count_non_negative",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_customer_review_customer_time",
        "customer_review",
        ["customer_id", "initiated_at"],
        schema=SCHEMA,
    )

    # ── detected_change ───────────────────────────────────────────────────────
    op.create_table(
        "detected_change",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("change_ref", sa.String(length=64), nullable=False),
        sa.Column("review_ref", sa.String(length=64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute", sa.String(length=255), nullable=False),
        sa.Column("change_type", detected_change_type_enum, nullable=False),
        sa.Column("baseline_value", postgresql.JSONB(), nullable=True),
        sa.Column("current_value", postgresql.JSONB(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("materiality", detected_change_materiality_enum, nullable=False),
        sa.Column("verification_source", sa.String(length=100), nullable=False),
        sa.Column("requires_customer_confirmation", sa.Boolean(), nullable=False),
        sa.Column("customer_response", sa.Text(), nullable=True),
        sa.Column("assessor_note", sa.Text(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_detected_change"),
        sa.UniqueConstraint("change_ref", name="uq_detected_change_ref"),
        sa.ForeignKeyConstraint(
            ["review_ref"],
            [f"{SCHEMA}.customer_review.review_ref"],
            name="fk_detected_change_review_ref",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_detected_change_customer_id",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_detected_change_review_materiality",
        "detected_change",
        ["review_ref", "materiality"],
        schema=SCHEMA,
    )

    # ── review_schedule ───────────────────────────────────────────────────────
    op.create_table(
        "review_schedule",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_risk_rating", review_risk_rating_enum, nullable=False),
        sa.Column("review_frequency_months", sa.Integer(), nullable=False),
        sa.Column("last_review_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_review_ref", sa.String(length=64), nullable=True),
        sa.Column("next_review_due", sa.Date(), nullable=False),
        sa.Column("grace_period_days", sa.Integer(), nullable=False),
        sa.Column("overdue", sa.Boolean(), nullable=False),
        sa.Column("schedule_status", review_schedule_status_enum, nullable=False),
        sa.Column("accelerated_from", sa.Date(), nullable=True),
        sa.Column("acceleration_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_review_schedule"),
        sa.UniqueConstraint("customer_id", name="uq_review_schedule_customer_id"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.customer_id"],
            name="fk_review_schedule_customer_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "review_frequency_months > 0",
            name="ck_review_schedule_frequency_positive",
        ),
        sa.CheckConstraint(
            "grace_period_days >= 0",
            name="ck_review_schedule_grace_period_non_negative",
        ),
        sa.CheckConstraint(
            "accelerated_from IS NULL OR acceleration_reason IS NOT NULL",
            name="ck_review_schedule_acceleration_reason_present",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_review_schedule_due_sweep",
        "review_schedule",
        ["next_review_due", "schedule_status"],
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # A review transitions through states, so it is not append-only; but its
    # identity, its start, and its completion are written once.
    op.execute(f"""
        CREATE TRIGGER trg_customer_review_field_immutability
        BEFORE UPDATE ON {SCHEMA}.customer_review
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set(
            'review_ref', 'initiated_at', 'completed_at', 'completed_by'
        );
    """)

    for table in ("customer_baseline_snapshot", "detected_change"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.prevent_mutation();
        """)


def downgrade() -> None:
    for table in ("detected_change", "customer_baseline_snapshot"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {SCHEMA}.{table};")
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_customer_review_field_immutability "
        f"ON {SCHEMA}.customer_review;"
    )

    # Reverse dependency order. Each table's indexes go with it.
    op.drop_table("review_schedule", schema=SCHEMA)
    op.drop_table("detected_change", schema=SCHEMA)
    op.drop_table("customer_review", schema=SCHEMA)
    op.drop_table("customer_baseline_snapshot", schema=SCHEMA)
    op.drop_table("review_trigger_definition", schema=SCHEMA)

    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_field_mutation_when_set() CASCADE;")

    bind = op.get_bind()
    for pg_enum in reversed(_ENUMS):
        pg_enum.drop(bind, checkfirst=False)
