"""A company's collections owner

``exporter_profile.collections_owner_user_id``: the person who chases the company's
payments — usually finance staff. Any active staff user may be named; there is no
foreign key to ``auth.users``, by the codebase's actor-id convention (migration 0009),
the same as the relationship manager. Indexed for the "My collections" list and the
bulk reassignment.

Revision ID: onboarding_0050_collector
Revises: onboarding_0049_payment_terms
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0050_collector"
down_revision: str | None = "onboarding_0049_payment_terms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    op.add_column(
        "exporter_profile",
        sa.Column("collections_owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_profile_collections_owner",
        "exporter_profile",
        ["collections_owner_user_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_exporter_profile_collections_owner", "exporter_profile", schema=SCHEMA)
    op.drop_column("exporter_profile", "collections_owner_user_id", schema=SCHEMA)
