"""A seller's deals have different references.

Revision ID: onboarding_0059_deal_reference
Revises: onboarding_0058_buyer_freeze

Why
---
A deal's reference ("Rotterdam shipment, March") is how people tell a company's deals
apart: on the company's Deals tab, in the deal list, in a handover. Nothing stopped two
deals of one seller sharing one (``database.md`` trap 13 listed it as a gap). Decided 14
October 2026: unique **per seller** — another seller may use the same words.

``uq_deal_company_reference`` is ``UNIQUE (company_id, reference)``, compared exactly, as
stored (``open_deal`` trims it). ``DealService.open_deal`` checks first and answers 409
``DEAL_REFERENCE_TAKEN``; the constraint covers a race.

Data
----
None. The migration **refuses** while any seller has two deals with one reference, and
prints them: which deal keeps the reference is a person's decision, not this revision's.

Rollback
--------
The downgrade drops the constraint.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0059_deal_reference"
down_revision: str | None = "onboarding_0058_buyer_freeze"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

_DUPLICATES = f"""
    SELECT company_id, reference, count(*) AS deals
      FROM {SCHEMA}.deal
     GROUP BY company_id, reference
    HAVING count(*) > 1
     ORDER BY company_id, reference
"""


def upgrade() -> None:
    duplicates = op.get_bind().execute(sa.text(_DUPLICATES)).all()
    if duplicates:
        listing = "; ".join(
            f"company {company_id}: {reference!r} x{deals}"
            for company_id, reference, deals in duplicates[:20]
        )
        raise RuntimeError(
            f"{len(duplicates)} seller(s) have two or more deals with one reference, so "
            "uq_deal_company_reference cannot be added. Rename all but one of each, then "
            f"upgrade again. Nothing was changed. {listing}"
        )
    op.create_unique_constraint(
        "uq_deal_company_reference", "deal", ["company_id", "reference"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_constraint("uq_deal_company_reference", "deal", schema=SCHEMA)
