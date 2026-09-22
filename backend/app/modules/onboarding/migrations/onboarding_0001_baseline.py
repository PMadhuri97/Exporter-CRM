"""onboarding module baseline — schema `onboarding`

Squash of two sources, expressed as the final desired schema only:

  f1a2b3c4d5e6  onboarding_customers, onboarding_applicant_mappings,
                onboarding_verifications, onboarding_webhook_events,
                two enums, one immutability trigger
  a1b2c3d4e5f6  onboarding_case, person_profile, kyc_case,
                case_state_transition, four enums, one immutability trigger

Everything is created inside the dedicated `onboarding` schema:

  Provider-integration tables (Sumsub-era foundation):
    onboarding.onboarding_customers          — the identity being verified.
    onboarding.onboarding_applicant_mappings — customer ↔ provider applicant.
    onboarding.onboarding_verifications      — one row per result. Append-only.
    onboarding.onboarding_webhook_events     — inbound webhook audit + dedup.

  Case model:
    onboarding.onboarding_case      — the KYC/KYB case.
    onboarding.person_profile       — 1:1 with a case.
    onboarding.kyc_case             — 1:1 with a case.
    onboarding.case_state_transition — state machine trail. Append-only.

The module owns no functions and no sequences, and — uniquely among the
table-owning modules — **no cross-schema foreign key**. All five foreign keys
are intra-module. Its only external dependency is the shared enum below.

SHARED ENUM — REFERENCED, NOT CREATED.
`case_state_transition.actor_type` uses `audit.actor_type_enum` with
`create_type=False`. Audit owns and creates that type; onboarding does not
declare a copy. This preserves today's single shared type, per the resolved
decision in migrations/CUTOVER_MANIFEST.md, and mirrors what a1b2c3d4e5f6 already
does ("actor_type_enum already exists (audit_events). Never re-created, never
dropped."). Two consequences:

  - the audit baseline must be applied **before** this one;
  - `DROP SCHEMA audit CASCADE` reaches this column, so audit must be downgraded
    **after** onboarding, not before.

`onboarding_case_state_enum` types three columns across two tables
(`onboarding_case.state`, `case_state_transition.previous_state` and
`.next_state`), so all enums are created explicitly up front — letting
`create_table` emit them would attempt CREATE TYPE more than once. This is the
same reason a1b2c3d4e5f6 creates them by hand.

`onboarding_case.provider_route_id` deliberately carries **no** foreign key. The
`provider_route` table does not exist yet; `case.py:77` documents the omission as
intentional and defers the constraint to the route resolver's own migration. It
is reproduced here as a bare nullable UUID, not invented as a constraint.

Column order reproduces the physical order in the pre-squash database. Both
source migrations declared columns in ORM order with `id` first, so unlike the
AppendOnlyModel tables in audit, payments and compliance there is nothing
counter-intuitive here — but the order is still taken from the migrations, not
from the models.

EXTERNAL DEPENDENCY: both immutability triggers execute
`public.prevent_mutation()`, which is created by the shared bootstrap migration
a0b1c2d3e4f5 and is not owned by this module. It is referenced schema-qualified
so the reference cannot be broken by a search_path change.

Constraint names reproduce what the pre-squash database holds. None of these
tables was ever renamed. Where a source migration named a constraint explicitly
that name is used; where it did not, the explicit name below is identical to what
PostgreSQL would generate.

Revision ID: onboarding_0001_baseline
Revises: audit_0001_baseline
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "onboarding_0001_baseline"
down_revision: str | None = "audit_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "onboarding"
AUDIT_SCHEMA = "audit"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: these models use a plain
# Enum(PyEnum, name=...), so SQLAlchemy persists `.name`.

onboarding_status_enum = postgresql.ENUM(
    "PENDING", "IN_REVIEW", "APPROVED", "REJECTED",
    name="onboarding_status_enum", schema=SCHEMA, create_type=False,
)
onboarding_verification_status_enum = postgresql.ENUM(
    "PENDING", "APPROVED", "REJECTED",
    name="onboarding_verification_status_enum", schema=SCHEMA, create_type=False,
)
onboarding_case_state_enum = postgresql.ENUM(
    "DRAFT",
    "SUBMITTED",
    "PROVIDER_PENDING",
    "PROVIDER_COMPLETED",
    "PROVIDER_FAILED",
    "MANUAL_REVIEW_REQUIRED",
    "MORE_INFO_REQUESTED",
    "APPROVED",
    "REJECTED",
    "REVIEW_DUE",
    "CLOSED",
    "REOPENED_BY_EXCEPTION",
    name="onboarding_case_state_enum", schema=SCHEMA, create_type=False,
)
onboarding_case_type_enum = postgresql.ENUM(
    "KYC", "KYB",
    name="onboarding_case_type_enum", schema=SCHEMA, create_type=False,
)
onboarding_subject_type_enum = postgresql.ENUM(
    "INDIVIDUAL", "ENTITY",
    name="onboarding_subject_type_enum", schema=SCHEMA, create_type=False,
)
onboarding_transition_source_enum = postgresql.ENUM(
    "USER_ACTION", "SYSTEM", "PROVIDER_CALLBACK", "ADMIN_OVERRIDE",
    name="onboarding_transition_source_enum", schema=SCHEMA, create_type=False,
)

# Owned by audit. Referenced only — never created, never dropped here.
actor_type_enum = postgresql.ENUM(
    "SYSTEM", "COMPLIANCE_OFFICER", "API_CLIENT",
    name="actor_type_enum", schema=AUDIT_SCHEMA, create_type=False,
)

_OWNED_ENUMS = (
    onboarding_status_enum,
    onboarding_verification_status_enum,
    onboarding_case_state_enum,
    onboarding_case_type_enum,
    onboarding_subject_type_enum,
    onboarding_transition_source_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front, not inline: onboarding_case_state_enum types
    # three columns across two tables, so letting create_table emit it would
    # attempt CREATE TYPE more than once. audit.actor_type_enum is absent from
    # this list on purpose — audit owns it.
    for pg_enum in _OWNED_ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── onboarding_customers ──────────────────────────────────────────────────
    op.create_table(
        "onboarding_customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        # The stable id handed to the identity provider as `externalUserId`.
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("level_name", sa.String(length=100), nullable=False),
        sa.Column("status", onboarding_status_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="onboarding_customers_pkey"),
        schema=SCHEMA,
    )
    # Uniqueness is carried by unique indexes, not table constraints — the source
    # migration used create_index(unique=True) for both.
    op.create_index(
        "ix_onboarding_customers_email",
        "onboarding_customers",
        ["email"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_customers_external_user_id",
        "onboarding_customers",
        ["external_user_id"],
        unique=True,
        schema=SCHEMA,
    )

    # ── onboarding_applicant_mappings ─────────────────────────────────────────
    op.create_table(
        "onboarding_applicant_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        # Nullable: some providers create the applicant asynchronously.
        sa.Column("applicant_id", sa.String(length=255), nullable=True),
        sa.Column("level_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.onboarding_customers.id"],
            name="onboarding_applicant_mappings_customer_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="onboarding_applicant_mappings_pkey"),
        # One applicant mapping per customer per provider.
        sa.UniqueConstraint(
            "customer_id", "provider", name="uq_onboarding_mapping_customer_provider"
        ),
        # A provider applicant id is unique within a provider.
        sa.UniqueConstraint(
            "provider", "applicant_id", name="uq_onboarding_mapping_provider_applicant"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_applicant_mappings_customer_id",
        "onboarding_applicant_mappings",
        ["customer_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ── onboarding_verifications ──────────────────────────────────────────────
    op.create_table(
        "onboarding_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        # Provider reference — applicantId / inspectionId.
        sa.Column("provider_ref", sa.String(length=255), nullable=True),
        # Raw provider fields, preserved verbatim for audit.
        sa.Column("review_status", sa.String(length=50), nullable=True),
        sa.Column("review_answer", sa.String(length=50), nullable=True),
        sa.Column("status", onboarding_verification_status_enum, nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.onboarding_customers.id"],
            name="onboarding_verifications_customer_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="onboarding_verifications_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_verifications_customer_id",
        "onboarding_verifications",
        ["customer_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ── onboarding_webhook_events ─────────────────────────────────────────────
    op.create_table(
        "onboarding_webhook_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("applicant_id", sa.String(length=255), nullable=True),
        # SHA-256 hex of the raw request body — the idempotency key.
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="onboarding_webhook_events_pkey"),
        schema=SCHEMA,
    )
    # A redelivered identical webhook is rejected at insert time.
    op.create_index(
        "ix_onboarding_webhook_events_dedup_key",
        "onboarding_webhook_events",
        ["dedup_key"],
        unique=True,
        schema=SCHEMA,
    )

    # ── onboarding_case ───────────────────────────────────────────────────────
    op.create_table(
        "onboarding_case",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("external_case_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("cell_id", sa.String(length=64), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("case_type", onboarding_case_type_enum, nullable=False),
        sa.Column("subject_type", onboarding_subject_type_enum, nullable=False),
        sa.Column("product_context", sa.String(length=64), nullable=True),
        sa.Column("policy_id", sa.String(length=64), nullable=True),
        # Deliberately NO foreign key: the `provider_route` table does not exist
        # yet. The constraint belongs to the route resolver's own migration.
        sa.Column("provider_route_id", sa.UUID(), nullable=True),
        sa.Column("state", onboarding_case_state_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="onboarding_case_pkey"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_onboarding_case_tenant_idem_key"
        ),
        sa.UniqueConstraint(
            "tenant_id", "external_case_id", name="uq_onboarding_case_tenant_external_id"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_onboarding_case_tenant_id", "onboarding_case", ["tenant_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_onboarding_case_state", "onboarding_case", ["state"], schema=SCHEMA
    )

    # ── person_profile ────────────────────────────────────────────────────────
    # Every attribute is nullable: a case is created in DRAFT and the profile is
    # filled in afterwards.
    op.create_table(
        "person_profile",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=2), nullable=True),
        sa.Column("residence_country", sa.String(length=2), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            [f"{SCHEMA}.onboarding_case.id"],
            name="person_profile_case_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="person_profile_pkey"),
        schema=SCHEMA,
    )
    # Unique, which is what enforces the 1:1 with onboarding_case.
    op.create_index(
        "ix_person_profile_case_id",
        "person_profile",
        ["case_id"],
        unique=True,
        schema=SCHEMA,
    )

    # ── kyc_case ──────────────────────────────────────────────────────────────
    op.create_table(
        "kyc_case",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        # e.g. ["IDENTITY", "DOCUMENT", "LIVENESS"].
        sa.Column(
            "required_checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            [f"{SCHEMA}.onboarding_case.id"],
            name="kyc_case_case_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="kyc_case_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_kyc_case_case_id", "kyc_case", ["case_id"], unique=True, schema=SCHEMA
    )

    # ── case_state_transition ─────────────────────────────────────────────────
    op.create_table(
        "case_state_transition",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        # NULL on the genesis transition into DRAFT.
        sa.Column("previous_state", onboarding_case_state_enum, nullable=True),
        sa.Column("next_state", onboarding_case_state_enum, nullable=False),
        sa.Column("source", onboarding_transition_source_enum, nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        # audit.actor_type_enum — referenced, not created. See module docstring.
        sa.Column("actor_type", actor_type_enum, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE: the state machine trail outlives any attempt to
        # remove the case it describes. person_profile and kyc_case cascade
        # because they are case detail; this is the audit record.
        sa.ForeignKeyConstraint(
            ["case_id"],
            [f"{SCHEMA}.onboarding_case.id"],
            name="case_state_transition_case_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="case_state_transition_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_case_state_transition_case_id",
        "case_state_transition",
        ["case_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_case_state_transition_correlation_id",
        "case_state_transition",
        ["correlation_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_case_state_transition_case_created",
        "case_state_transition",
        ["case_id", "created_at"],
        schema=SCHEMA,
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # A customer's verification history is never rewritten, only added to; the
    # state machine trail likewise. prevent_mutation() is owned by the shared
    # root migration and lives in public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER onboarding_verifications_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.onboarding_verifications
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER case_state_transition_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.case_state_transition
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    # CASCADE reaches all eight tables, their keys, the eleven indexes, both
    # triggers and the six owned enum types in one statement. It does NOT drop
    # audit.actor_type_enum, which lives in another schema and is not owned here.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
