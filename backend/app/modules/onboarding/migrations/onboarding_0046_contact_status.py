"""A contact's status and when it was last verified

A company keeps its contacts after people leave, so a contact has a status — ``ACTIVE``
(the default, and every existing contact), ``INACTIVE`` or ``LEFT_COMPANY`` — with when
and why it last changed, and a "last verified" date with who verified it.

* Leaving ``ACTIVE`` needs a reason (the service checks it; the database keeps the
  reason beside the status).
* Only an ``ACTIVE`` contact may be the primary contact
  (``ck_exporter_contact_primary_is_active``): deactivating the primary clears the flag.

Revision ID: onboarding_0046_contact_status
Revises: onboarding_0045_doc_previews
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0046_contact_status"
down_revision: str | None = "onboarding_0045_doc_previews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_contact"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("status_changed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(TABLE, sa.Column("status_reason", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        TABLE,
        sa.Column("last_verified_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE, sa.Column("last_verified_by", sa.String(length=255), nullable=True), schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_exporter_contact_status",
        TABLE,
        "status IN ('ACTIVE', 'INACTIVE', 'LEFT_COMPANY')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_contact_primary_is_active",
        TABLE,
        "status = 'ACTIVE' OR is_primary_contact = false",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint("ck_exporter_contact_primary_is_active", TABLE, schema=SCHEMA)
    op.drop_constraint("ck_exporter_contact_status", TABLE, schema=SCHEMA)
    for column in (
        "last_verified_by",
        "last_verified_at",
        "status_reason",
        "status_changed_at",
        "status",
    ):
        op.drop_column(TABLE, column, schema=SCHEMA)
