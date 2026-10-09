"""A company's addresses, and the address a GST branch trades from

``onboarding.company_address``: many per company, each of a type (REGISTERED, BILLING,
SHIPPING, FACTORY_WAREHOUSE, CORRESPONDENCE), at most one active default per type,
deactivated rather than deleted (``trg_company_address_no_delete``).

``exporter_gstin.address_id`` (optional) names the address a branch trades from. The
foreign key is on ``(address_id, customer_id)``, so a branch can only point at an
address of its own company. The branch's free-text ``address`` stays as it was.

Revision ID: onboarding_0047_addresses
Revises: onboarding_0046_contact_status
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0047_addresses"
down_revision: str | None = "onboarding_0046_contact_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TYPES = ("REGISTERED", "BILLING", "SHIPPING", "FACTORY_WAREHOUSE", "CORRESPONDENCE")

_NO_DELETE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_company_address_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'company_address rows are never deleted; deactivate the address instead'
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "company_address",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address_type", sa.String(length=24), nullable=False),
        sa.Column("line1", sa.String(length=255), nullable=False),
        sa.Column("line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_company_address_customer_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "customer_id", name="uq_company_address_id_customer_id"),
        sa.CheckConstraint(
            "address_type IN (" + ", ".join(f"'{value}'" for value in TYPES) + ")",
            name="ck_company_address_type",
        ),
        sa.CheckConstraint("is_active OR NOT is_default", name="ck_company_address_default_active"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_company_address_customer_id", "company_address", ["customer_id"], schema=SCHEMA
    )
    op.create_index(
        "uq_company_address_default_per_type",
        "company_address",
        ["customer_id", "address_type"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("is_default AND is_active"),
    )
    op.execute(_NO_DELETE_FUNCTION)
    op.execute(
        f"""
        CREATE TRIGGER trg_company_address_no_delete
        BEFORE DELETE ON {SCHEMA}.company_address
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_company_address_delete();
        """
    )

    op.add_column(
        "exporter_gstin",
        sa.Column("address_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_exporter_gstin_address",
        "exporter_gstin",
        "company_address",
        ["address_id", "customer_id"],
        ["id", "customer_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_exporter_gstin_address", "exporter_gstin", schema=SCHEMA)
    op.drop_column("exporter_gstin", "address_id", schema=SCHEMA)
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_company_address_no_delete ON {SCHEMA}.company_address;"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_company_address_delete();")
    op.drop_index("uq_company_address_default_per_type", "company_address", schema=SCHEMA)
    op.drop_index("ix_company_address_customer_id", "company_address", schema=SCHEMA)
    op.drop_table("company_address", schema=SCHEMA)
