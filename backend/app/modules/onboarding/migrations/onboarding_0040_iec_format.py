"""The IEC gets the format check every other identifier already has — **owner:
Developer 3** (inherited item, from the former `open-items.md` §2).

Revision ID: onboarding_0040_iec_format
Revises: onboarding_0039_closed_buyer

Why
---
Migration 0014 gave ``pan``, ``gstin``, ``cin`` and ``country`` ``CHECK``
constraints, so a value that skipped the service is still refused. ``iec`` was left
out. The service has always checked it (``normalise_iec``, ``IEC_RE``), which means
the gap is narrow — but it is exactly the gap every other constraint in that
migration exists to close: a bulk import, a script, a fixture or a careless
``UPDATE`` writes straight past the service.

Ten letters or digits, upper-case: the same rule ``IEC_RE`` enforces, restated as
SQL so the two cannot drift. A test asserts the database refuses what the service
refuses.

Data
----
None. Every existing ``iec`` was written through the service, and this migration was
written only after confirming that: ``SELECT count(*) … WHERE iec IS NOT NULL AND iec
!~ '^[A-Z0-9]{10}$'`` returned 0. Were it not 0 this would have to be an
expand→backfill→contract sequence instead, because adding a ``CHECK`` to a table with
violating rows fails outright and would leave the deploy half-done.

If it fails on another database, that is the constraint doing its job: find the rows
with that query, fix or clear them, then run it again.

Rollback
--------
The downgrade drops the constraint. Nothing is lost — it adds no data and changes no
value.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0040_iec_format"
down_revision: str | None = "onboarding_0039_closed_buyer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: ``IEC_RE`` in ``domain/tax_identifiers.py``, as SQL.
IEC_PATTERN = "^[A-Z0-9]{10}$"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_exporter_profile_iec_format",
        "exporter_profile",
        f"iec IS NULL OR iec ~ '{IEC_PATTERN}'",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_exporter_profile_iec_format",
        "exporter_profile",
        type_="check",
        schema=SCHEMA,
    )
