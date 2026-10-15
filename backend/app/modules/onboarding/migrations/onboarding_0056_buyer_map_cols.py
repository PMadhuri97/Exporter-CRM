"""The buyer migration writes its answer onto ``deal_buyer``, not a separate table.

Revision ID: onboarding_0056_buyer_map_cols
Revises: onboarding_0055_config_freeze

Why
---
``deal_buyer_company_map`` (0038) held one row per ``deal_buyer``: its primary key was
``deal_buyer_id``, so the relationship was one-to-one and the table was five columns of
``deal_buyer`` kept somewhere else. Nothing but the ``migrate_deal_buyers`` command ever
read or wrote it. The five columns now live on the buyer's own row:

* ``mapped_company_id`` — the company the row turned out to be (FK, ``RESTRICT``);
* ``match_rule`` — how that was decided (``buyer_match_rule_enum``, kept);
* ``matched_by``, ``matched_at`` — who ran it, and when;
* ``mapping_run_id`` — the run, for "what did run X do".

The map's guarantees carry over:

* **One mapping per buyer**: the columns are on the buyer's own row.
* **A mapping is never changed**: ``trg_deal_buyer_mapping_set_once`` uses
  ``prevent_field_mutation_when_set``, which allows ``NULL`` → a value once and nothing
  after.
* **Written whole**: ``ck_deal_buyer_mapping_complete`` requires the company, rule, time
  and run together. ``matched_by`` stays optional, as it was on the map.
* **"What did run X do"**: ``ix_deal_buyer_mapping_run``. The merge, read by company:
  ``ix_deal_buyer_mapped_company``.

Data
----
Any map rows are copied onto their buyers before the table is dropped. The map's primary
key guarantees one row per buyer, and ``deal_buyer`` has no update trigger until this
revision adds one, so the copy is exact. Where the buyer migration has not run, the map
is empty and nothing moves.

Rollback
--------
The downgrade recreates the map as 0038 and 0041 left it, with its append-only trigger,
copies every mapped buyer back into it, then removes the columns. Lossless, because the
relationship is one-to-one; the map's own ``id`` is regenerated, and nothing references
it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0056_buyer_map_cols"
down_revision: str | None = "onboarding_0055_config_freeze"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The columns a mapping writes, in the order the set-once trigger lists them.
MAPPING_COLUMNS = ("mapped_company_id", "match_rule", "matched_by", "matched_at", "mapping_run_id")

_MATCH_RULE = postgresql.ENUM(
    name="buyer_match_rule_enum",
    schema=SCHEMA,
    # The type already exists (0038, 0041) and stays.
    create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "deal_buyer",
        sa.Column("mapped_company_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column("deal_buyer", sa.Column("match_rule", _MATCH_RULE, nullable=True), schema=SCHEMA)
    op.add_column(
        "deal_buyer", sa.Column("matched_by", sa.String(255), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "deal_buyer",
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "deal_buyer", sa.Column("mapping_run_id", sa.String(255), nullable=True), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_deal_buyer_mapped_company",
        "deal_buyer",
        "exporter_profile",
        ["mapped_company_id"],
        ["customer_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    # Whatever a run already decided moves first, while nothing guards the columns.
    op.execute(
        f"""
        UPDATE {SCHEMA}.deal_buyer b
           SET mapped_company_id = m.company_id,
               match_rule = m.match_rule,
               matched_by = m.matched_by,
               matched_at = m.matched_at,
               mapping_run_id = m.run_id
          FROM {SCHEMA}.deal_buyer_company_map m
         WHERE m.deal_buyer_id = b.id
        """
    )

    op.create_check_constraint(
        "ck_deal_buyer_mapping_complete",
        "deal_buyer",
        "(mapped_company_id IS NULL) = (match_rule IS NULL) "
        "AND (mapped_company_id IS NULL) = (matched_at IS NULL) "
        "AND (mapped_company_id IS NULL) = (mapping_run_id IS NULL)",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deal_buyer_mapped_company", "deal_buyer", ["mapped_company_id"], schema=SCHEMA
    )
    op.create_index("ix_deal_buyer_mapping_run", "deal_buyer", ["mapping_run_id"], schema=SCHEMA)
    arguments = ", ".join(f"'{column}'" for column in MAPPING_COLUMNS)
    op.execute(
        f"""
        CREATE TRIGGER trg_deal_buyer_mapping_set_once
        BEFORE UPDATE ON {SCHEMA}.deal_buyer
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set({arguments});
        """
    )

    # The append-only trigger refuses row deletes, not the table: it goes with it.
    op.drop_table("deal_buyer_company_map", schema=SCHEMA)


def downgrade() -> None:
    op.create_table(
        "deal_buyer_company_map",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("deal_buyer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_rule", _MATCH_RULE, nullable=False),
        sa.Column("matched_by", sa.String(255), nullable=True),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("run_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["deal_buyer_id"],
            [f"{SCHEMA}.deal_buyer.id"],
            name="fk_deal_buyer_company_map_deal_buyer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_deal_buyer_company_map_company",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deal_buyer_company_map_company",
        "deal_buyer_company_map",
        ["company_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deal_buyer_company_map_run", "deal_buyer_company_map", ["run_id"], schema=SCHEMA
    )
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.deal_buyer_company_map
               (deal_buyer_id, company_id, match_rule, matched_by, matched_at, run_id, created_at)
        SELECT id, mapped_company_id, match_rule, matched_by, matched_at, mapping_run_id, matched_at
          FROM {SCHEMA}.deal_buyer
         WHERE mapped_company_id IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_deal_buyer_company_map_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.deal_buyer_company_map
        FOR EACH ROW
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )

    op.execute(f"DROP TRIGGER IF EXISTS trg_deal_buyer_mapping_set_once ON {SCHEMA}.deal_buyer")
    op.drop_index("ix_deal_buyer_mapping_run", table_name="deal_buyer", schema=SCHEMA)
    op.drop_index("ix_deal_buyer_mapped_company", table_name="deal_buyer", schema=SCHEMA)
    op.drop_constraint("ck_deal_buyer_mapping_complete", "deal_buyer", schema=SCHEMA)
    op.drop_constraint("fk_deal_buyer_mapped_company", "deal_buyer", schema=SCHEMA)
    for column in reversed(MAPPING_COLUMNS):
        op.drop_column("deal_buyer", column, schema=SCHEMA)
