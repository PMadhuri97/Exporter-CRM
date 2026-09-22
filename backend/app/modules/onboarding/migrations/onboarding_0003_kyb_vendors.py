"""S1T4 KYB vendor registry

Creates ``onboarding.kyb_vendor_registration`` — the registry of KYB vendor
adapters the onboarding orchestration engine routes on. Mirrors
``rails.rail_registration`` (a ``capability_declaration`` JSONB blob plus the
columns the registry actually queries and monitors on).

Revision ID: onboarding_0003_kyb_vendors
Revises: settlement_0002_signal_outbox
Create Date: 2026-09-10

Re-parented onto settlement_0002_signal_outbox (was customers_0003_entitlements):
this revision existed only on feature/AL-524 and had not reached develop, so per
README.md's "Database & Migrations" section the fix for the resulting multi-head
graph — after rails_0003_rail_event_id / settlement_0002_signal_outbox landed on
develop and were merged into this branch — is re-parenting, not a merge revision
(a merge revision is for when *both* sides are already on develop).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0003_kyb_vendors"
down_revision: str | None = "settlement_0002_signal_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

# ── Enums ─────────────────────────────────────────────────────────────────────
# Labels are the uppercase Python member names (name == value for both enums in
# app.shared.enums.kyb), matching the onboarding schema's create_type=False +
# explicit .create() convention (see onboarding_0002_orchestration_schema).

kyb_vendor_processing_mode_enum = postgresql.ENUM(
    "SYNCHRONOUS", "ASYNCHRONOUS",
    name="kyb_vendor_processing_mode_enum", schema=SCHEMA, create_type=False,
)

kyb_vendor_health_status_enum = postgresql.ENUM(
    "HEALTHY", "DEGRADED", "DOWN",
    name="kyb_vendor_health_status_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (
    kyb_vendor_processing_mode_enum,
    kyb_vendor_health_status_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    for e in _ENUMS:
        e.create(bind)

    op.create_table(
        "kyb_vendor_registration",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("vendor_id", sa.String(length=100), nullable=False),
        sa.Column("vendor_name", sa.String(length=255), nullable=False),
        sa.Column("supported_countries", postgresql.JSONB(), nullable=False),
        sa.Column("supported_entity_types", postgresql.JSONB(), nullable=False),
        sa.Column("processing_mode", kyb_vendor_processing_mode_enum, nullable=False),
        sa.Column(
            "health_status", kyb_vendor_health_status_enum,
            server_default="HEALTHY", nullable=False,
        ),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capability_declaration", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_kyb_vendor_registration"),
        sa.UniqueConstraint("vendor_id", name="uq_kyb_vendor_registration_vendor_id"),
        sa.CheckConstraint(
            "octet_length(capability_declaration::text) <= 65536",
            name="ck_kyb_vendor_registration_cap_decl_size",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_kyb_vendor_registration_health_status",
        "kyb_vendor_registration",
        ["health_status"],
        schema=SCHEMA,
    )

    # vendor identity is immutable once set — reuses the onboarding-schema
    # function created by onboarding_0002_orchestration_schema, matching the
    # trigger that guards kyb_vendor_result.
    op.execute(f"""
    CREATE TRIGGER trg_kyb_vendor_registration_field_immutability
    BEFORE UPDATE ON {SCHEMA}.kyb_vendor_registration
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('vendor_id');
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_kyb_vendor_registration_field_immutability "
        f"ON {SCHEMA}.kyb_vendor_registration;"
    )
    op.drop_index(
        "ix_kyb_vendor_registration_health_status",
        table_name="kyb_vendor_registration",
        schema=SCHEMA,
    )
    op.drop_table("kyb_vendor_registration", schema=SCHEMA)

    for e in _ENUMS:
        e.drop(op.get_bind())
