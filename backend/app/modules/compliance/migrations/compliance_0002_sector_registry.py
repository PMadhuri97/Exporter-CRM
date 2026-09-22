from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
#: Kept to 31 characters: alembic_version.version_num is VARCHAR(32), and a
#: longer id fails the migration at the point it records success — after the
#: DDL has run.
revision: str = "compliance_0002_sector_registry"
down_revision: str | None = "rails_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "compliance"

#: Reused from the baseline rather than recreated: dropping the tables leaves
#: the type in place, and the four tiers are unchanged.
sector_risk_tier_enum = postgresql.ENUM(
    "standard", "elevated", "high", "critical",
    name="sector_risk_tier_enum", schema=SCHEMA, create_type=False,
)

jurisdiction_type_enum = postgresql.ENUM(
    "corridor", "country", "framework",
    name="jurisdiction_type_enum", schema=SCHEMA, create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # Child first: the FK to sector_code_registry is ON DELETE RESTRICT.
    op.drop_table("sector_risk_classification", schema=SCHEMA)
    op.drop_table("sector_code_registry", schema=SCHEMA)

    op.execute(f"CREATE TYPE {SCHEMA}.jurisdiction_type_enum AS ENUM "
               "('corridor', 'country', 'framework')")

    # ── sector_code_registry ──────────────────────────────────────────────────
    op.create_table(
        "sector_code_registry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="sector_code_registry_pkey"),
        # Both child tables reference this column, which Postgres permits only
        # against a uniquely-constrained column.
        sa.UniqueConstraint("sector_code", name="uq_sector_code_registry_sector_code"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_code_registry_period",
        ),
        sa.CheckConstraint(
            "sector_code = upper(sector_code)",
            name="ck_sector_code_registry_sector_code_upper",
        ),
        schema=SCHEMA,
    )

    # ── sector_code_external_mapping ──────────────────────────────────────────
    op.create_table(
        "sector_code_external_mapping",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("external_standard", sa.String(length=20), nullable=False),
        sa.Column("external_standard_version", sa.String(length=30), nullable=False),
        sa.Column("external_code", sa.String(length=20), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sector_code"],
            [f"{SCHEMA}.sector_code_registry.sector_code"],
            name="fk_sector_code_external_mapping_sector_code",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="sector_code_external_mapping_pkey"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_code_external_mapping_period",
        ),
        sa.CheckConstraint(
            "external_standard = upper(external_standard)",
            name="ck_sector_code_external_mapping_standard_upper",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sector_code_external_mapping_lookup",
        "sector_code_external_mapping",
        ["sector_code", "external_standard"],
        schema=SCHEMA,
    )

    # ── sector_risk_classification ────────────────────────────────────────────
    op.create_table(
        "sector_risk_classification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("jurisdiction_type", jurisdiction_type_enum, nullable=False),
        sa.Column("jurisdiction_value", sa.String(length=50), nullable=False),
        sa.Column("risk_tier", sector_risk_tier_enum, nullable=False),
        sa.Column("classification_label", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sector_code"],
            [f"{SCHEMA}.sector_code_registry.sector_code"],
            name="fk_sector_risk_classification_sector_code",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="sector_risk_classification_pkey"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_risk_classification_period",
        ),
        sa.CheckConstraint(
            "jurisdiction_value = upper(jurisdiction_value)",
            name="ck_sector_risk_classification_jurisdiction_upper",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sector_risk_classification_lookup",
        "sector_risk_classification",
        ["sector_code", "jurisdiction_type", "jurisdiction_value"],
        schema=SCHEMA,
    )

    # ── Exclusion constraints ─────────────────────────────────────────────────
    # Written as SQL rather than through SQLAlchemy so the reviewable text is the
    # constraint itself. '[)' matches is_effective_at's half-open logic: a row
    # ending on the day another starts does not overlap it.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.sector_code_external_mapping
            ADD CONSTRAINT ex_sector_code_external_mapping_period
            EXCLUDE USING gist (
                sector_code WITH =,
                external_standard WITH =,
                external_standard_version WITH =,
                daterange(effective_from, effective_to, '[)') WITH &&
            );
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.sector_risk_classification
            ADD CONSTRAINT ex_sector_risk_classification_period
            EXCLUDE USING gist (
                sector_code WITH =,
                jurisdiction_type WITH =,
                jurisdiction_value WITH =,
                daterange(effective_from, effective_to, '[)') WITH &&
            );
        """
    )

    # ── effective_from immutability ───────────────────────────────────────────
    # Narrower than public.prevent_mutation(), which blocks every UPDATE: closing
    # a sector by setting effective_to is legitimate, moving the date it started
    # is not — it silently rewrites which historical payments were in scope.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_sector_code_registry_immutable_fields()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.effective_from IS DISTINCT FROM OLD.effective_from THEN
                RAISE EXCEPTION 'sector_code_registry.effective_from is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            IF NEW.sector_code IS DISTINCT FROM OLD.sector_code THEN
                RAISE EXCEPTION 'sector_code_registry.sector_code is immutable'
                    USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER sector_code_registry_immutable_fields
        BEFORE UPDATE ON {SCHEMA}.sector_code_registry
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_sector_code_registry_immutable_fields();
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS sector_code_registry_immutable_fields "
        f"ON {SCHEMA}.sector_code_registry"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.assert_sector_code_registry_immutable_fields()"
    )

    op.drop_table("sector_risk_classification", schema=SCHEMA)
    op.drop_table("sector_code_external_mapping", schema=SCHEMA)
    op.drop_table("sector_code_registry", schema=SCHEMA)

    op.execute(f"DROP TYPE {SCHEMA}.jurisdiction_type_enum")

    # Restore the baseline shape. btree_gist is left installed: it is a database
    # object, not a schema one, and dropping it could break anything added since.
    op.create_table(
        "sector_code_registry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("isic_code", sa.String(length=10), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="sector_code_registry_pkey"),
        sa.UniqueConstraint("sector_code", name="uq_sector_code_registry_sector_code"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_code_registry_period",
        ),
        sa.CheckConstraint(
            "sector_code = upper(sector_code)",
            name="ck_sector_code_registry_sector_code_upper",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "sector_risk_classification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sector_code", sa.String(length=50), nullable=False),
        sa.Column("jurisdiction", sa.String(length=50), nullable=False),
        sa.Column("risk_tier", sector_risk_tier_enum, nullable=False),
        sa.Column("classification_label", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sector_code"],
            [f"{SCHEMA}.sector_code_registry.sector_code"],
            name="fk_sector_risk_classification_sector_code",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="sector_risk_classification_pkey"),
        sa.UniqueConstraint(
            "sector_code",
            "jurisdiction",
            "effective_from",
            name="uq_sector_risk_classification",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_sector_risk_classification_period",
        ),
        sa.CheckConstraint(
            "jurisdiction = upper(jurisdiction)",
            name="ck_sector_risk_classification_jurisdiction_upper",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sector_risk_classification_sector_code_jurisdiction",
        "sector_risk_classification",
        ["sector_code", "jurisdiction"],
        schema=SCHEMA,
    )
