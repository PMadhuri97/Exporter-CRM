"""A qualification criterion may be answered automatically

``qualification_criterion.auto_source`` names where an automatic result comes from:
IEC_VERIFICATION, YEARS_ESTABLISHED, INDUSTRY, EXPORT_MARKETS, TRADE_HISTORY or
DEAL_VALUE. Set on a new version, like every other change to a criterion. Existing
versions answer nothing automatically.

Revision ID: onboarding_0053_auto_criteria
Revises: auth_0010_true_match_permission
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0053_auto_criteria"
down_revision: str | None = "auth_0010_true_match_permission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
SOURCES = (
    "IEC_VERIFICATION",
    "YEARS_ESTABLISHED",
    "INDUSTRY",
    "EXPORT_MARKETS",
    "TRADE_HISTORY",
    "DEAL_VALUE",
)


def upgrade() -> None:
    op.add_column(
        "qualification_criterion",
        sa.Column("auto_source", sa.String(length=24), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_qualification_criterion_auto_source",
        "qualification_criterion",
        "auto_source IS NULL OR auto_source IN ("
        + ", ".join(f"'{value}'" for value in SOURCES)
        + ")",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_qualification_criterion_auto_source", "qualification_criterion", schema=SCHEMA
    )
    op.drop_column("qualification_criterion", "auto_source", schema=SCHEMA)
