"""S1T1 onboarding orchestration schema

Revision ID: onboarding_0002_orchestration
Revises: 5a3b7c9d1e2f
Create Date: 2026-08-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0002_orchestration"
down_revision: str | None = "d4f2a1b8c360"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
AUDIT_SCHEMA = "audit"

# ── Enums ─────────────────────────────────────────────────────────────────────

onboarding_request_status_enum = postgresql.ENUM(
    "DRAFT", "ENTITY_VERIFICATION_IN_PROGRESS", "ENTITY_VERIFIED",
    "UBO_MAPPING_IN_PROGRESS", "UBO_MAPPING_COMPLETE",
    "DOCUMENT_COLLECTION_IN_PROGRESS", "DOCUMENT_COLLECTION_COMPLETE",
    "SCREENING_IN_PROGRESS", "SCREENING_COMPLETE",
    "RISK_RATING_IN_PROGRESS", "RISK_RATED",
    "PENDING_COMPLIANCE_APPROVAL", "APPROVED",
    "ACCOUNT_CREATION_IN_PROGRESS", "ACTIVE",
    "REJECTED", "ABANDONED", "UNDER_REVIEW",
    name="onboarding_request_status_enum", schema=SCHEMA, create_type=False,
)

onboarding_entity_type_enum = postgresql.ENUM(
    "CORPORATION", "PARTNERSHIP", "SOLE_TRADER", "TRUST", "FUND",
    name="onboarding_entity_type_enum", schema=SCHEMA, create_type=False,
)

onboarding_risk_rating_enum = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL",
    name="onboarding_risk_rating_enum", schema=SCHEMA, create_type=False,
)

onboarding_screening_result_enum = postgresql.ENUM(
    "CLEAR", "REVIEW_REQUIRED", "HARD_BLOCK",
    name="onboarding_screening_result_enum", schema=SCHEMA, create_type=False,
)

onboarding_compliance_decision_enum = postgresql.ENUM(
    "APPROVED", "REJECTED",
    name="onboarding_compliance_decision_enum", schema=SCHEMA, create_type=False,
)

onboarding_rejection_category_enum = postgresql.ENUM(
    "KYB_FAILURE", "SCREENING_BLOCK", "COMPLIANCE_REJECTION", "DOCUMENT_FRAUD", "TIMEOUT",
    name="onboarding_rejection_category_enum", schema=SCHEMA, create_type=False,
)

ubo_control_type_enum = postgresql.ENUM(
    "DIRECT_OWNERSHIP", "INDIRECT_OWNERSHIP", "VOTING_RIGHTS", "OTHER_CONTROL",
    name="ubo_control_type_enum", schema=SCHEMA, create_type=False,
)

ubo_identification_type_enum = postgresql.ENUM(
    "PASSPORT", "NATIONAL_ID", "DRIVING_LICENCE",
    name="ubo_identification_type_enum", schema=SCHEMA, create_type=False,
)

ubo_kyc_result_enum = postgresql.ENUM(
    "VERIFIED", "FAILED", "PENDING", "NOT_STARTED",
    name="ubo_kyc_result_enum", schema=SCHEMA, create_type=False,
)

ubo_pep_status_enum = postgresql.ENUM(
    "NOT_PEP", "PEP", "PEP_ASSOCIATE",
    name="ubo_pep_status_enum", schema=SCHEMA, create_type=False,
)

onboarding_document_type_enum = postgresql.ENUM(
    "CERTIFICATE_OF_INCORPORATION", "MEMORANDUM_OF_ASSOCIATION", "PROOF_OF_ADDRESS",
    "BANK_STATEMENT", "AUDITED_ACCOUNTS", "LICENCE", "UBO_DECLARATION", "OTHER",
    name="onboarding_document_type_enum", schema=SCHEMA, create_type=False,
)

onboarding_validation_status_enum = postgresql.ENUM(
    "PENDING", "VALID", "INVALID", "EXPIRED",
    name="onboarding_validation_status_enum", schema=SCHEMA, create_type=False,
)

kyb_normalised_result_enum = postgresql.ENUM(
    "VERIFIED", "NOT_FOUND", "REJECTED", "REQUIRES_MANUAL_REVIEW", "PENDING",
    name="kyb_normalised_result_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    onboarding_request_status_enum,
    onboarding_entity_type_enum,
    onboarding_risk_rating_enum,
    onboarding_screening_result_enum,
    onboarding_compliance_decision_enum,
    onboarding_rejection_category_enum,
    ubo_control_type_enum,
    ubo_identification_type_enum,
    ubo_kyc_result_enum,
    ubo_pep_status_enum,
    onboarding_document_type_enum,
    onboarding_validation_status_enum,
    kyb_normalised_result_enum,
)

def upgrade() -> None:
    # 1. Enums
    for e in _ENUMS:
        e.create(op.get_bind())

    # 2. Trigger function
    op.execute(f"""
    CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_field_mutation_when_set()
    RETURNS TRIGGER AS $$
    DECLARE
        col_name text;
        old_json jsonb := to_jsonb(OLD);
        new_json jsonb := to_jsonb(NEW);
    BEGIN
        FOR i IN 0 .. array_upper(TG_ARGV, 1) LOOP
            col_name := TG_ARGV[i];
            IF old_json->col_name IS NOT NULL AND jsonb_typeof(old_json->col_name) != 'null' AND old_json->col_name IS DISTINCT FROM new_json->col_name THEN
                RAISE EXCEPTION 'Column % is immutable once set.', col_name;
            END IF;
        END LOOP;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # 3. Tables
    op.create_table(
        "onboarding_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", onboarding_request_status_enum, nullable=False),
        sa.Column("entity_type", onboarding_entity_type_enum, nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("trading_name", sa.String(length=255), nullable=True),
        sa.Column("registration_number", sa.String(length=100), nullable=False),
        sa.Column("tax_identification_number", sa.String(length=512), nullable=True),
        sa.Column("incorporation_country", sa.String(length=2), nullable=False),
        sa.Column("incorporation_date", sa.Date(), nullable=True),
        sa.Column("registered_address", postgresql.JSONB(), nullable=False),
        sa.Column("trading_address", postgresql.JSONB(), nullable=True),
        sa.Column("industry_code", sa.String(length=50), nullable=True),
        sa.Column("declared_monthly_volume_usd", sa.BigInteger(), nullable=True),
        sa.Column("corridor_intent", postgresql.JSONB(), nullable=True),
        sa.Column("account_ids", postgresql.JSONB(), nullable=True),
        sa.Column("initial_user_id", sa.String(length=255), nullable=False),
        sa.Column("initial_user_roles", postgresql.JSONB(), nullable=True),
        sa.Column("kyb_result", onboarding_screening_result_enum, nullable=True),
        sa.Column("ubo_mapping", postgresql.JSONB(), nullable=True),
        sa.Column("screening_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("risk_rating", onboarding_risk_rating_enum, nullable=True),
        sa.Column("risk_rating_factors", postgresql.JSONB(), nullable=True),
        sa.Column("compliance_approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("compliance_decision", onboarding_compliance_decision_enum, nullable=True),
        sa.Column("rejection_category", onboarding_rejection_category_enum, nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_onboarding_request_tenant_idem_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_request_tenant_id", "onboarding_request", ["tenant_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_onboarding_request_customer_id", "onboarding_request", ["customer_id"], schema=SCHEMA
    )
    op.create_index(
        "uq_onboarding_request_active_customer", "onboarding_request", ["customer_id"],
        unique=True, postgresql_where=sa.text("status = 'ACTIVE'"), schema=SCHEMA
    )

    op.create_table(
        "ubo_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("onboarding_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=512), nullable=True),
        sa.Column("nationality", sa.String(length=2), nullable=True),
        sa.Column("residence_country", sa.String(length=2), nullable=True),
        sa.Column("identification_type", ubo_identification_type_enum, nullable=True),
        sa.Column("identification_number", sa.String(length=512), nullable=True),
        sa.Column("control_type", ubo_control_type_enum, nullable=False),
        sa.Column("ownership_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("kyc_result", ubo_kyc_result_enum, nullable=False),
        sa.Column("screening_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pep_status", ubo_pep_status_enum, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["onboarding_request_id"], [f"{SCHEMA}.onboarding_request.id"], ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ubo_record_onboarding_request_id", "ubo_record", ["onboarding_request_id"], schema=SCHEMA
    )

    op.create_table(
        "onboarding_document",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("onboarding_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", onboarding_document_type_enum, nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("validation_status", onboarding_validation_status_enum, nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["onboarding_request_id"], [f"{SCHEMA}.onboarding_request.id"], ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_document_onboarding_request_id", "onboarding_document", ["onboarding_request_id"], schema=SCHEMA
    )

    op.create_table(
        "onboarding_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("onboarding_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("from_status", sa.String(length=100), nullable=True),
        sa.Column("to_status", sa.String(length=100), nullable=True),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["onboarding_request_id"], [f"{SCHEMA}.onboarding_request.id"], ondelete="RESTRICT"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_event_onboarding_request_id", "onboarding_event", ["onboarding_request_id"], schema=SCHEMA
    )

    op.create_table(
        "kyb_vendor_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("onboarding_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_name", sa.String(length=100), nullable=False),
        sa.Column("vendor_reference_id", sa.String(length=255), nullable=True),
        sa.Column("normalised_result", kyb_normalised_result_enum, nullable=False),
        sa.Column("raw_vendor_response", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["onboarding_request_id"], [f"{SCHEMA}.onboarding_request.id"], ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_kyb_vendor_result_onboarding_request_id", "kyb_vendor_result", ["onboarding_request_id"], schema=SCHEMA
    )

    # 4. Triggers
    op.execute(f"""
    CREATE TRIGGER trg_onboarding_request_field_immutability
    BEFORE UPDATE ON {SCHEMA}.onboarding_request
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('kyb_result', 'ubo_mapping', 'risk_rating_factors');
    """)

    op.execute(f"""
    CREATE TRIGGER trg_ubo_record_field_immutability
    BEFORE UPDATE ON {SCHEMA}.ubo_record
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('created_at');
    """)

    op.execute(f"""
    CREATE TRIGGER trg_onboarding_document_field_immutability
    BEFORE UPDATE ON {SCHEMA}.onboarding_document
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('submitted_at');
    """)

    op.execute(f"""
    CREATE TRIGGER trg_kyb_vendor_result_field_immutability
    BEFORE UPDATE ON {SCHEMA}.kyb_vendor_result
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('retrieved_at');
    """)

    # onboarding_event is full append-only, using the shared function
    op.execute(f"""
    CREATE TRIGGER trg_onboarding_event_append_only
    BEFORE UPDATE OR DELETE ON {SCHEMA}.onboarding_event
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.prevent_mutation();
    """)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_onboarding_event_append_only ON {SCHEMA}.onboarding_event;")
    op.execute(f"DROP TRIGGER IF EXISTS trg_kyb_vendor_result_field_immutability ON {SCHEMA}.kyb_vendor_result;")
    op.execute(f"DROP TRIGGER IF EXISTS trg_onboarding_document_field_immutability ON {SCHEMA}.onboarding_document;")
    op.execute(f"DROP TRIGGER IF EXISTS trg_ubo_record_field_immutability ON {SCHEMA}.ubo_record;")
    op.execute(f"DROP TRIGGER IF EXISTS trg_onboarding_request_field_immutability ON {SCHEMA}.onboarding_request;")

    op.drop_table("kyb_vendor_result", schema=SCHEMA)
    op.drop_table("onboarding_event", schema=SCHEMA)
    op.drop_table("onboarding_document", schema=SCHEMA)
    op.drop_table("ubo_record", schema=SCHEMA)
    op.drop_table("onboarding_request", schema=SCHEMA)

    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_field_mutation_when_set() CASCADE;")

    for e in _ENUMS:
        e.drop(op.get_bind())
