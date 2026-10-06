"""The buyer migration's mapping table.

Revision ID: onboarding_0038_buyer_map
Revises: onboarding_0037_trade_history

Why
---
``deal_buyer_company_map`` records which company each legacy ``deal_buyer`` row
turned out to be, **and how that was decided**. The second half is the point:
``deal.buyer_company_id`` already says which company a deal's buyer is, but not
whether a machine matched it on a PAN or a person agreed that two similarly-named
rows were one company. Those are different claims, and the one people will question
six months from now is the second.

It is also what makes the migration re-runnable. ``deal_buyer_id`` is the primary
key, so a second run finds the mapping already there and creates nothing — §17.2's
idempotency requirement, enforced by the schema rather than by the command
remembering.

This migration adds **only the table**. It moves no data: the migration itself is a
command (``python -m app.modules.onboarding.migrate_deal_buyers``), because it needs
a dry-run report and a human confirmation of name-only duplicates
between reading and writing — which an Alembic revision cannot have.

Append-only
-----------
``trg_deal_buyer_company_map_append_only`` refuses ``UPDATE`` and ``DELETE`` through
``public.prevent_mutation()``, the function this schema's other append-only tables
use. A mapping that turns out to be wrong is corrected by rolling the run back
(§17.2) and running again, not by editing the record of what the last run decided.

Rollback
--------
The downgrade drops the table and the enum. Doing so loses the record of how every
mapping was decided while leaving ``deal.buyer_company_id`` populated — so if a run
has been applied, roll **that** back first (§17.2's logical rollback), or the deals
will point at companies with nothing explaining why.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0038_buyer_map"
down_revision: str | None = "onboarding_0037_trade_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

_MATCH_RULE = postgresql.ENUM(
    "PAN",
    "REGISTRATION_NUMBER",
    "NEW",
    "NAME_CONFIRMED",
    name="buyer_match_rule_enum",
    schema=SCHEMA,
    # Created explicitly below; `create_table` must not try again (0037's lesson).
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    _MATCH_RULE.create(bind, checkfirst=False)

    op.create_table(
        "deal_buyer_company_map",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # The primary key is the deal buyer, not `id`: one mapping per legacy row
        # forever, which is what makes a re-run a no-op.
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
        "ix_deal_buyer_company_map_run",
        "deal_buyer_company_map",
        ["run_id"],
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_deal_buyer_company_map_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.deal_buyer_company_map
        FOR EACH ROW
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_deal_buyer_company_map_append_only "
        f"ON {SCHEMA}.deal_buyer_company_map;"
    )
    op.drop_table("deal_buyer_company_map", schema=SCHEMA)
    _MATCH_RULE.drop(op.get_bind(), checkfirst=False)
