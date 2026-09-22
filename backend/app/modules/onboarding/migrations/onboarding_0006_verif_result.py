"""EXP-2: generalized verification results (`onboarding.verification_result`)

Adds the new, broader results table the EXP-2 plan calls for: one row per
check ever run — KYC on a director, a bank-account check on an exporter, a
shipment/vessel check, or anything not yet anticipated — through the
generalized `VerificationAdapter` protocol
(`app.modules.onboarding.domain.workflow_dependencies`).

`kyb_vendor_result` is left exactly as it is: unmigrated, still written by
`kyb`'s existing path. This is confirmed in the EXP-2 plan as an
implementation-time call — `verification_result` is additive, for everything
`kyb_vendor_result` doesn't cover, not a replacement for it.

Reused trigger function
------------------------
`reviewed_by`/`review_status` are immutable once set, using the exact
`onboarding.prevent_field_mutation_when_set()` function `onboarding_0002_
orchestration_schema` already created (and `onboarding_0003_kyb_vendors` /
`onboarding_0004_screening_fix` already reused for their own tables) — no new
trigger function is created here, only a new trigger that calls the existing
one with this table's column names.

Fork note (parallel-worktree migration, expected and now reconciled):
this revision originally chained onto `onboarding_0004_screening_fix`
directly, the same parent EXP-1's `onboarding_0005_exporter_crm` chained
onto independently in its own worktree — both built against the same
starting point without knowledge of each other. Unlike the `2807a84d72ba`
precedent this docstring used to cite (`gateway`'s migration, already
merged into master before EXP-1/EXP-2 existed, reconciled with a proper
no-op merge revision because both sides were already real, on-branch
history), neither `onboarding_0005_exporter_crm` nor this revision had
been applied anywhere but a disposable, per-ticket test container at
reconciliation time — so this fork was resolved with a direct, in-place
edit of `down_revision` below (now `onboarding_0005_exporter_crm`) rather
than a new merge revision. `2807a84d72ba` itself turned out to still be a sibling of
`onboarding_0004_screening_fix` (it was already real, on-branch history
in master before either EXP worktree existed) — once this revision's
`down_revision` moved onto `onboarding_0005_exporter_crm`, that left
`2807a84d72ba` and this revision as the two remaining heads. *That* is
the on-branch case, fixed the same way `2807a84d72ba` was itself
originally created — a new no-op merge revision, not another in-place
edit: see `f1c7a3e6b9d2_merge_gateway_head_with_exp_crm_verification.py`.

Revision ID: onboarding_0006_verif_result
Revises: onboarding_0005_exporter_crm
Create Date: 2026-09-21

(Revision id shortened to "onboarding_0006_verif_result" — 29 chars — rather
than the more readable "onboarding_0006_verification_result" (36 chars):
alembic_version.version_num is VARCHAR(32), and the longer id fails the stamp
write *after* every DDL statement in the migration has already applied
(rolled back on this transactional-DDL backend, but the mistake was live long
enough to be worth naming here): see `tests/contract/test_migration_discovery
.py::test_no_revision_id_exceeds_the_version_table_width`, which exists for
exactly this failure mode.)
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0006_verif_result"
down_revision: str | None = "onboarding_0005_exporter_crm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

# ── Enums ─────────────────────────────────────────────────────────────────────

verification_type_enum = postgresql.ENUM(
    "KYC", "KYB", "AML", "CFT", "SANCTIONS", "PEP", "ADVERSE_MEDIA",
    "COMPANY_REGISTRY", "UBO", "GST", "IEC", "BANK_ACCOUNT", "BUYER",
    "INVOICE", "INVOICE_DUPLICATION", "SHIPMENT", "VESSEL", "INSURANCE",
    name="verification_type_enum", schema=SCHEMA, create_type=False,
)

verification_entity_type_enum = postgresql.ENUM(
    "EXPORTER", "BUYER", "DIRECTOR", "INVOICE", "VESSEL", "SHIPMENT",
    name="verification_entity_type_enum", schema=SCHEMA, create_type=False,
)

verification_result_status_enum = postgresql.ENUM(
    "PENDING", "PASSED", "FAILED", "REVIEW",
    name="verification_result_status_enum", schema=SCHEMA, create_type=False,
)

verification_risk_level_enum = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH",
    name="verification_risk_level_enum", schema=SCHEMA, create_type=False,
)

verification_review_status_enum = postgresql.ENUM(
    "ACCEPTED", "REJECTED", "ESCALATED",
    name="verification_review_status_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    verification_type_enum,
    verification_entity_type_enum,
    verification_result_status_enum,
    verification_risk_level_enum,
    verification_review_status_enum,
)


def upgrade() -> None:
    # 1. Enums
    for e in _ENUMS:
        e.create(op.get_bind())

    # 2. Table. No FK on entity_reference: entity_type determines which table
    #    it actually points at (several of which — buyer, vessel, shipment —
    #    don't exist yet in this checkout), the same bare-reference convention
    #    ComplianceCase.customer_id/settlement_id/onboarding_id already uses.
    op.create_table(
        "verification_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("verification_type", verification_type_enum, nullable=False),
        sa.Column("entity_type", verification_entity_type_enum, nullable=False),
        sa.Column("entity_reference", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("status", verification_result_status_enum, nullable=False),
        sa.Column("risk_level", verification_risk_level_enum, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        # PII / encrypted-at-rest documentation gap for raw_result — see
        # VerificationResult's docstring. Same already-accepted gap as
        # onboarding_request.tax_identification_number and
        # kyb_vendor_result.raw_vendor_response; no new encryption mechanism
        # invented here.
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_reference", sa.String(length=1024), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_status", verification_review_status_enum, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_verification_result_entity", "verification_result",
        ["entity_type", "entity_reference"], schema=SCHEMA,
    )
    op.create_index(
        "ix_verification_result_provider_reference", "verification_result",
        ["provider_reference"], schema=SCHEMA,
    )

    # 3. Immutability trigger — reuses onboarding.prevent_field_mutation_when_set(),
    #    created by onboarding_0002_orchestration_schema. No new function.
    op.execute(f"""
    CREATE TRIGGER trg_verification_result_field_immutability
    BEFORE UPDATE ON {SCHEMA}.verification_result
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('reviewed_by', 'review_status');
    """)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_verification_result_field_immutability ON {SCHEMA}.verification_result;")
    op.drop_table("verification_result", schema=SCHEMA)

    for e in _ENUMS:
        e.drop(op.get_bind())
