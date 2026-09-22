"""E9: persist exporter screening checklist and bank-activity findings.

Revision ID: onboarding_0010_screen_review
Revises: onboarding_0009_rm_user_id
Create Date: 2026-09-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0010_screen_review"
down_revision: str | None = "onboarding_0009_rm_user_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    op.create_table(
        "screening_review_item",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="NEEDS_REVIEW"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "item_key", name="uq_screening_review_customer_item"),
        schema=SCHEMA,
    )
    op.create_index("ix_screening_review_customer_id", "screening_review_item", ["customer_id"], schema=SCHEMA)

    op.create_table(
        "bank_activity_finding",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("finding_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="REVIEW"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index("ix_bank_activity_finding_customer_id", "bank_activity_finding", ["customer_id"], schema=SCHEMA)
    op.create_index("ix_bank_activity_finding_customer_status", "bank_activity_finding", ["customer_id", "status"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_bank_activity_finding_customer_status", table_name="bank_activity_finding", schema=SCHEMA)
    op.drop_index("ix_bank_activity_finding_customer_id", table_name="bank_activity_finding", schema=SCHEMA)
    op.drop_table("bank_activity_finding", schema=SCHEMA)
    op.drop_index("ix_screening_review_customer_id", table_name="screening_review_item", schema=SCHEMA)
    op.drop_table("screening_review_item", schema=SCHEMA)
