"""``identity_type`` agrees with what each company holds again.

Revision ID: onboarding_0043_identity_type
Revises: onboarding_0042_deal_fks

Why
---
``identity_type`` says which registration identifies a company: ``IN_PAN`` when it
holds a PAN, ``FOREIGN_REG`` when it holds a registration number and no PAN, ``NULL``
when it holds neither (``decide_identity_type``). Migration 0032 backfilled it and the
create paths set it — but ``update_profile`` never recomputed it, so a company that
gained a PAN by edit (the identity completion flow) kept ``NULL``, and one that lost it kept
``IN_PAN``. The service now recomputes it on every edit of either field; this puts
right every row edited before that.

Data
----
Rows whose ``identity_type`` disagrees with ``pan`` and ``registration_number`` are
set to what those say — the same rule, restated as SQL, as ``decide_identity_type``.
Nothing else changes, and no history row is written: ``identity_type`` is derived, as
it is on create. The number of rows corrected is printed.

Rollback
--------
The downgrade changes nothing. The values replaced were wrong by the rule every write
path applies, so restoring them would restore the defect.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0043_identity_type"
down_revision: str | None = "onboarding_0042_deal_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: `decide_identity_type`, in SQL: a PAN wins, then a registration number, else NULL.
DECIDED = (
    f"CASE WHEN pan IS NOT NULL THEN 'IN_PAN'::{SCHEMA}.company_identity_type_enum "
    f"WHEN registration_number IS NOT NULL "
    f"THEN 'FOREIGN_REG'::{SCHEMA}.company_identity_type_enum END"
)


def upgrade() -> None:
    result = op.get_bind().execute(
        sa.text(
            f"UPDATE {SCHEMA}.exporter_profile SET identity_type = {DECIDED} "
            f"WHERE identity_type IS DISTINCT FROM {DECIDED}"
        )
    )
    print(f"onboarding_0043: identity_type corrected on {result.rowcount} company row(s).")


def downgrade() -> None:
    # Nothing to undo: see the module docstring.
    pass
