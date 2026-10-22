"""Every change to a live rule records why it was made

``change_reason`` on each versioned settings table — ``qualification_criterion``,
``deal_required_document``, ``payment_term`` and ``sanctions_list``: the ticket number
or explanation the administrator gave for the version (``domain/change_reason.py``).

Nullable, because the versions written before this migration — and the ones the
migrations seed — have no reason to give, and inventing one would put words in the
record nobody wrote. The services refuse a new version without one.

Revision ID: onboarding_0063_change_reason
Revises: onboarding_0062_contact_names
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0063_change_reason"
down_revision: str | None = "onboarding_0062_contact_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLES = ("qualification_criterion", "deal_required_document", "payment_term", "sanctions_list")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table, sa.Column("change_reason", sa.String(500), nullable=True), schema=SCHEMA
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "change_reason", schema=SCHEMA)
