"""compliance_0002_std_versions

Revision ID: compliance_0002_std_versions
Revises: compliance_0002_sector_registry
Create Date: 2026-08-11 12:00:00.000000

Makes the purpose-code registry (created by ``compliance_0001_baseline``)
versioned in two senses.

**Standard revisions.** ``external_standard_version`` records which published
revision of a regulator's code set a mapping was read from. A payment filed under
one circular has to stay attributable to it after the regulator issues the next,
so the citation is stored beside the code rather than inferred later. Its column
position matches the epic's field table — immediately after ``external_standard``
— which is why the column is added by rebuilding the table rather than by a plain
``ADD COLUMN``: Postgres has no ``ADD COLUMN ... AFTER``, and a bare add always
appends at the physical end regardless of where the ORM model declares it.

**Validity periods, enforced by the database.** The unique constraints this
replaces could only say "one row per key, ever". Reference data needs "one row
per key, per date": a code is retired and reinstated, a mapping is superseded by
the next circular. Exclusion constraints over ``daterange(effective_from,
effective_to, '[)')`` express exactly that, and make the point-in-time lookup in
validate_purpose_code provably unambiguous rather than unambiguous by convention.

The mapping table's foreign key is replaced by triggers. A FK requires a UNIQUE
constraint on the referenced column, and UNIQUE (canonical_code) is precisely what
the canonical exclusion constraint has to give up — with it, a code could never be
retired and reinstated, because the second row would collide on the code alone
regardless of dates. The triggers reproduce ON DELETE RESTRICT against the code
*value*, which is what a per-code reference actually means here, and raise the
same SQLSTATE the foreign key did.

Everything here lives in the ``compliance`` schema established by the baseline;
every identifier below is schema-qualified accordingly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "compliance_0002_std_versions"
down_revision: str | None = "compliance_0002_sector_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "compliance"
TABLE = "purpose_code_corridor_mapping"

#: What the existing Walk-phase rows were read from. Applied as a backfill so the
#: column can be NOT NULL immediately; the GitOps seed files carry the same value,
#: so the next boot rewrites these rows with identical content.
WALK_PHASE_STANDARD_VERSION = "RBI Purpose Code Master Circular 2024"


def upgrade() -> None:
    # GiST cannot index the equality half of these constraints on scalar types
    # without btree_gist; the ADD CONSTRAINT would fail with "data type character
    # varying has no default operator class for access method gist".
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # ── Rebuild purpose_code_corridor_mapping with the new column in position ──
    # Postgres cannot insert a column between two existing ones, so the table is
    # rebuilt: renamed aside, recreated with the epic's declared field order, data
    # copied across, old one dropped. This also sheds the FK and UNIQUE
    # constraints the baseline gave the table — cheaper than dropping them by name
    # afterward, since the rebuild has to touch the whole table regardless.
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} RENAME TO {TABLE}_pre_versioning")
    # RENAME TABLE does not rename the table's implicit indexes, and a primary
    # key's backing index is a schema-scoped relation name, not a per-table one —
    # left alone, it would collide with the new table's own {TABLE}_pkey below.
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE}_pre_versioning "
        f"RENAME CONSTRAINT {TABLE}_pkey TO {TABLE}_pre_versioning_pkey"
    )

    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_code", sa.String(length=50), nullable=False),
        sa.Column("corridor_id", sa.String(length=50), nullable=False),
        sa.Column("external_standard", sa.String(length=50), nullable=False),
        sa.Column("external_standard_version", sa.String(length=100), nullable=False),
        sa.Column("external_code", sa.String(length=50), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"{TABLE}_pkey"),
        schema=SCHEMA,
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.{TABLE}
                (id, canonical_code, corridor_id, external_standard,
                 external_standard_version, external_code, effective_from, effective_to)
            SELECT id, canonical_code, corridor_id, external_standard,
                   :version, external_code, effective_from, effective_to
            FROM {SCHEMA}.{TABLE}_pre_versioning
            """
        ).bindparams(version=WALK_PHASE_STANDARD_VERSION)
    )

    op.execute(f"DROP TABLE {SCHEMA}.{TABLE}_pre_versioning")

    # ── Exclusion constraints replace both UNIQUE constraints ─────────────────
    op.drop_constraint(
        "uq_purpose_code_canonical_code",
        "purpose_code_canonical",
        schema=SCHEMA,
        type_="unique",
    )

    # At most one definition of a canonical code may be valid on any given date.
    # A NULL effective_to is open-ended: daterange(x, NULL) runs to infinity, so an
    # open row conflicts with everything after its start.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.purpose_code_canonical
        ADD CONSTRAINT ex_purpose_code_canonical_validity
        EXCLUDE USING gist (
            canonical_code WITH =,
            daterange(effective_from, effective_to, '[)') WITH &&
        )
        """
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.{TABLE}
        ADD CONSTRAINT ex_purpose_code_mapping_validity
        EXCLUDE USING gist (
            canonical_code WITH =,
            corridor_id WITH =,
            external_standard WITH =,
            external_standard_version WITH =,
            daterange(effective_from, effective_to, '[)') WITH &&
        )
        """
    )

    # Resolution reads by (canonical_code, corridor_id). The dropped FK used to
    # justify a btree on canonical_code; the exclusion constraint's GiST index is
    # a poor substitute for plain equality, so the index is created explicitly.
    op.create_index(
        "ix_purpose_code_mapping_canonical_corridor",
        TABLE,
        ["canonical_code", "corridor_id"],
        schema=SCHEMA,
    )

    # ── Referential integrity, by trigger ─────────────────────────────────────
    # ERRCODE 23503 is foreign_key_violation: these raise exactly what the real FK
    # raised, so callers and tests cannot tell the difference and nothing had to
    # learn a new error code when the FK was replaced. Both functions live in the
    # compliance schema, alongside the tables they guard.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_purpose_code_canonical_exists()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM {SCHEMA}.purpose_code_canonical
                 WHERE canonical_code = NEW.canonical_code
            ) THEN
                RAISE EXCEPTION
                    'purpose_code_corridor_mapping references canonical_code %, which does not exist',
                    NEW.canonical_code
                    USING ERRCODE = '23503',
                          HINT = 'Add the canonical code to canonical.yaml before mapping a corridor to it.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER purpose_code_mapping_canonical_fk
        BEFORE INSERT OR UPDATE ON {SCHEMA}.{TABLE}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_purpose_code_canonical_exists();
        """
    )

    # RESTRICT against the code, not the row. A canonical code may have several
    # rows over time; removing one only orphans mappings when it was the last row
    # carrying that code, which is why the guard re-checks for siblings.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.restrict_purpose_code_canonical_delete()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM {SCHEMA}.purpose_code_canonical
                 WHERE canonical_code = OLD.canonical_code
                   AND id <> OLD.id
            ) AND EXISTS (
                SELECT 1 FROM {SCHEMA}.{TABLE}
                 WHERE canonical_code = OLD.canonical_code
            ) THEN
                RAISE EXCEPTION
                    'canonical_code % is still referenced by purpose_code_corridor_mapping',
                    OLD.canonical_code
                    USING ERRCODE = '23503',
                          HINT = 'Delete the corridor mappings first; the seed loader relies on this ordering.';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER purpose_code_canonical_delete_restrict
        BEFORE DELETE ON {SCHEMA}.purpose_code_canonical
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.restrict_purpose_code_canonical_delete();
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS purpose_code_canonical_delete_restrict "
        f"ON {SCHEMA}.purpose_code_canonical"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.restrict_purpose_code_canonical_delete()")
    op.execute(
        f"DROP TRIGGER IF EXISTS purpose_code_mapping_canonical_fk ON {SCHEMA}.{TABLE}"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.assert_purpose_code_canonical_exists()")

    op.drop_index(
        "ix_purpose_code_mapping_canonical_corridor",
        table_name=TABLE,
        schema=SCHEMA,
    )
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT ex_purpose_code_mapping_validity")
    op.execute(
        f"ALTER TABLE {SCHEMA}.purpose_code_canonical DROP CONSTRAINT ex_purpose_code_canonical_validity"
    )
    op.create_unique_constraint(
        "uq_purpose_code_canonical_code",
        "purpose_code_canonical",
        ["canonical_code"],
        schema=SCHEMA,
    )

    # Rebuild the table back to the baseline's column order and shape, dropping
    # external_standard_version rather than merely un-NOT-NULLing it — a plain
    # ADD COLUMN in the upgrade means there is no "original position" to restore
    # it to, so the column has to go entirely for the table to match baseline
    # again. A downgrade that leaves a code the baseline never declared is not a
    # true downgrade.
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} RENAME TO {TABLE}_post_versioning")
    # Same index-name collision as upgrade(): the renamed-aside table still owns
    # the schema-scoped {TABLE}_pkey index name until this is renamed out of the way.
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE}_post_versioning "
        f"RENAME CONSTRAINT {TABLE}_pkey TO {TABLE}_post_versioning_pkey"
    )

    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_code", sa.String(length=50), nullable=False),
        sa.Column("corridor_id", sa.String(length=50), nullable=False),
        sa.Column("external_standard", sa.String(length=50), nullable=False),
        sa.Column("external_code", sa.String(length=50), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_code"],
            [f"{SCHEMA}.purpose_code_canonical.canonical_code"],
            name=f"{TABLE}_canonical_code_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=f"{TABLE}_pkey"),
        # Restoring this can fail where the exclusion constraint was doing real
        # work — a code superseded under a second external_standard_version has
        # two rows this UNIQUE cannot hold. That is not something a downgrade
        # should paper over by deleting rows, so it is left to fail loudly.
        sa.UniqueConstraint(
            "corridor_id", "external_standard", "external_code", name="uq_purpose_code_mapping"
        ),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        INSERT INTO {SCHEMA}.{TABLE}
            (id, canonical_code, corridor_id, external_standard, external_code,
             effective_from, effective_to)
        SELECT id, canonical_code, corridor_id, external_standard, external_code,
               effective_from, effective_to
        FROM {SCHEMA}.{TABLE}_post_versioning
        """
    )

    op.execute(f"DROP TABLE {SCHEMA}.{TABLE}_post_versioning")
    # btree_gist is left installed: it is a database-wide extension and another
    # migration may since have come to depend on it.
