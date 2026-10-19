"""Indexes for sorting the Companies list

The list is sorted on the server and paged (``domain/list_sort.py``): by default by when
the company was added, as before, or, when chosen, by when the company record last
changed or by name. Without an index each page of a large list would sort every company
to return fifty; with these, a page reads only the rows it returns.

* ``ix_exporter_profile_updated_at`` — ``updated_at DESC, customer_id DESC``, the
  "Last updated" order exactly;
* ``ix_exporter_profile_name_lower`` — ``lower(name)``, the name order (case ignored).

Sorting by stage needs none: there are three stages, and each is already indexed
(``ix_exporter_profile_journey``).

Revision ID: onboarding_0064_company_sort
Revises: onboarding_0063_change_reason
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0064_company_sort"
down_revision: str | None = "onboarding_0063_change_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_profile"


def upgrade() -> None:
    op.create_index(
        "ix_exporter_profile_updated_at",
        TABLE,
        [sa.text("updated_at DESC"), sa.text("customer_id DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_profile_name_lower", TABLE, [sa.text("lower(name)")], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_exporter_profile_name_lower", TABLE, schema=SCHEMA)
    op.drop_index("ix_exporter_profile_updated_at", TABLE, schema=SCHEMA)
