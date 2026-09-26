"""Retire the ten-status lifecycle from the company record (L2-04).

Revision ID: onboarding_0020_retire_lifecycle
Revises: onboarding_0017_qualification

The company's live journey is ``exporter_profile.journey`` — ``LEAD`` ->
``PROSPECT`` -> ``CUSTOMER`` (0017) — with the qualification gauge beside it
and the ``PAUSED``/``ENDED`` marker (0014). The old mixed ten-status
``lifecycle_status`` column, which folded conversation, verification,
compliance and lending into one line (architecture §1, §5.6), is dropped here,
with its enum type.

**No history is lost.** Every move the old column ever made is a row in
``exporter_lifecycle_history`` (dimension ``journey``, event types
``lifecycle_initial``/``lifecycle_transition``, the old values as strings), and
this migration does not touch that table.

Numbered 0020: the migration register reserves 0015, 0016, 0018 and 0019 for
Developers 3 and 4, and has no number for L2-04. Whichever of those lands
after this re-parents onto the head (register §2). Developer 1 to add the row.

Downgrade restores the column, **lossily**: it can only be derived from the
journey (``LEAD`` -> ``LEAD``, ``PROSPECT`` -> ``CONTACTED``, ``CUSTOMER`` ->
``ACTIVE``), not the status each company actually had.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0020_retire_lifecycle"
down_revision: str | None = "onboarding_0017_qualification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
_OLD_STATUSES = (
    "LEAD", "CONTACTED", "DATA_COLLECTION", "VERIFICATION_IN_PROGRESS", "COMPLIANCE_REVIEW",
    "ONBOARDED", "FINANCING_ELIGIBLE", "ACTIVE", "SUSPENDED", "OFFBOARDED",
)
lifecycle_enum = postgresql.ENUM(
    *_OLD_STATUSES, name="exporter_lifecycle_status_enum", schema=SCHEMA, create_type=False
)


def upgrade() -> None:
    op.drop_column("exporter_profile", "lifecycle_status", schema=SCHEMA)
    lifecycle_enum.drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    lifecycle_enum.create(op.get_bind(), checkfirst=False)
    op.add_column(
        "exporter_profile",
        sa.Column("lifecycle_status", lifecycle_enum, nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {SCHEMA}.exporter_profile
        SET lifecycle_status = (CASE journey
            WHEN 'LEAD' THEN 'LEAD'
            WHEN 'PROSPECT' THEN 'CONTACTED'
            ELSE 'ACTIVE'
        END)::{SCHEMA}.exporter_lifecycle_status_enum
        """
    )
    op.alter_column("exporter_profile", "lifecycle_status", nullable=False, schema=SCHEMA)
