"""add_compliance_rule_registry

Revision ID: c7d8e9f0a1b2
Revises: compliance_0002_std_versions
Create Date: 2026-08-04 11:20:00.000000

The table lives in the ``compliance`` schema alongside every other table this
module owns, and reuses ``compliance.sector_risk_tier_enum`` — created by
compliance_0001_baseline — rather than declaring a second tier vocabulary that
could drift from the sector registry's.

Parented on ``compliance_0002_std_versions``, the tip of the compliance chain on
``develop``. This revision previously hung off a ``b2c3d4e5f6a7`` merge revision
created on this branch to join ``compliance_0002_sector_registry`` and
``rails_0001_baseline``, which had both declared ``f3a1b2c3d4e5`` as their
parent. AL-442 re-parented ``compliance_0002_sector_registry`` onto
``rails_0001_baseline`` directly, so that fork no longer exists and the merge
revision had nothing left to join — it survived only as a second branch point,
which is what produced two heads. Attaching to the chain tip instead keeps the
ordering this revision actually needs: it still runs strictly after
``compliance_0002_sector_registry``, which rebuilds the sector tables that own
the tier enum this table reuses.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "compliance_0002_std_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "compliance"


def upgrade() -> None:
    op.execute(
        f"CREATE TYPE {SCHEMA}.compliance_required_action_enum AS ENUM "
        "('edd_required', 'manual_review', 'enhanced_monitoring')"
    )

    op.create_table(
        "compliance_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("corridor_match", sa.String(length=50), nullable=True),
        sa.Column(
            "sector_risk_tier_match",
            postgresql.ENUM(
                "standard",
                "elevated",
                "high",
                "critical",
                name="sector_risk_tier_enum",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("sector_classification_label_match", sa.String(length=50), nullable=True),
        sa.Column("purpose_code_category_match", sa.String(length=50), nullable=True),
        sa.Column("amount_threshold", sa.BigInteger(), nullable=True),
        sa.Column("amount_threshold_currency", sa.String(length=16), nullable=True),
        # ── Obligation ────────────────────────────────────────────────────────
        sa.Column(
            "required_action",
            postgresql.ENUM(
                "edd_required",
                "manual_review",
                "enhanced_monitoring",
                name="compliance_required_action_enum",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("action_reason", sa.String(), nullable=False),
        # ── Effectivity ───────────────────────────────────────────────────────
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", name="uq_compliance_rule_rule_id"),
        sa.CheckConstraint(
            "(amount_threshold IS NULL) = (amount_threshold_currency IS NULL)",
            name="ck_compliance_rule_threshold_paired",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_compliance_rule_period",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("compliance_rule", schema=SCHEMA)
    # Only the type this migration created is dropped. sector_risk_tier_enum
    # belongs to compliance_0001_baseline and sector_risk_classification still
    # depends on it — dropping it here would take that table's column with it.
    op.execute(f"DROP TYPE {SCHEMA}.compliance_required_action_enum")
