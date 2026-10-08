"""Parent and child companies

``exporter_profile.parent_company_id`` names a company's parent and
``group_relationship`` says how they are related (SUBSIDIARY, BRANCH_OFFICE,
GROUP_COMPANY, JOINT_VENTURE). The two are set together or not at all, and a company is
never its own parent.

``trg_exporter_profile_no_group_cycle`` refuses a link that would make a company its
own ancestor, walking up from the new parent — the service checks the same first, so
the trigger is the guard against a write that bypasses it, or two links racing.

Revision ID: onboarding_0051_company_groups
Revises: auth_0009_collector_permission
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0051_company_groups"
down_revision: str | None = "auth_0009_collector_permission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_profile"
RELATIONSHIPS = ("SUBSIDIARY", "BRANCH_OFFICE", "GROUP_COMPANY", "JOINT_VENTURE")

_CYCLE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_company_group_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF NEW.parent_company_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        WITH RECURSIVE ancestors(id, depth) AS (
            SELECT NEW.parent_company_id, 1
            UNION ALL
            SELECT p.parent_company_id, a.depth + 1
            FROM {SCHEMA}.{TABLE} p
            JOIN ancestors a ON p.customer_id = a.id
            WHERE p.parent_company_id IS NOT NULL AND a.depth < 100
        )
        SELECT 1 FROM ancestors WHERE id = NEW.customer_id
    ) THEN
        RAISE EXCEPTION
            'company % cannot sit under %: it would become its own parent',
            NEW.customer_id, NEW.parent_company_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$;
"""


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("parent_company_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE, sa.Column("group_relationship", sa.String(length=16), nullable=True), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_exporter_profile_parent_company",
        TABLE,
        TABLE,
        ["parent_company_id"],
        ["customer_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_exporter_profile_parent_company", TABLE, ["parent_company_id"], schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_exporter_profile_group_relationship",
        TABLE,
        "(parent_company_id IS NULL AND group_relationship IS NULL) OR "
        "(parent_company_id IS NOT NULL AND group_relationship IN ("
        + ", ".join(f"'{value}'" for value in RELATIONSHIPS)
        + "))",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_not_own_parent",
        TABLE,
        "parent_company_id IS NULL OR parent_company_id <> customer_id",
        schema=SCHEMA,
    )
    op.execute(_CYCLE_FUNCTION)
    op.execute(
        f"""
        CREATE TRIGGER trg_exporter_profile_no_group_cycle
        BEFORE INSERT OR UPDATE OF parent_company_id ON {SCHEMA}.{TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_company_group_cycle();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_exporter_profile_no_group_cycle ON {SCHEMA}.{TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_company_group_cycle();")
    op.drop_constraint("ck_exporter_profile_not_own_parent", TABLE, schema=SCHEMA)
    op.drop_constraint("ck_exporter_profile_group_relationship", TABLE, schema=SCHEMA)
    op.drop_index("ix_exporter_profile_parent_company", TABLE, schema=SCHEMA)
    op.drop_constraint("fk_exporter_profile_parent_company", TABLE, schema=SCHEMA)
    op.drop_column(TABLE, "group_relationship", schema=SCHEMA)
    op.drop_column(TABLE, "parent_company_id", schema=SCHEMA)
