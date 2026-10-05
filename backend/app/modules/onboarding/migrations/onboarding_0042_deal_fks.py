"""An invoice's deal and a buyer company's deal are real deals.

Revision ID: onboarding_0042_deal_fks
Revises: onboarding_0041_map_rule_link

Why
---
``trade_invoice.deal_id`` (0037) and ``exporter_profile.created_via_deal_id`` (0032)
were left as bare uuids, on the reasoning that losing an invoice or a company because
its deal was cleaned up would be worse than losing the link. Nothing deletes a deal —
``WITHDRAWN`` is how one ends — and a bare uuid let ``POST
/trade-relationships/{id}/invoices`` write any value at all: a random one was accepted
and, ``deal_id`` being frozen once set, kept for good. So both become foreign keys
**``ON DELETE RESTRICT``**, the convention every other link to a deal follows
(``fk_crm_document_deal_id``): a deal that something points at cannot vanish, and
nothing is ever lost.

Data
----
Each constraint is added ``NOT VALID`` and then validated **only if no existing row
violates it**. ``NOT VALID`` already enforces it on every row written or changed from
here on; validation adds the guarantee for rows written before. A violating row cannot
always be corrected — ``trade_invoice.deal_id`` is frozen once set — so rather than
failing the deploy on it, the migration prints how many rows are left unvalidated and
the query that lists them, and leaves that constraint ``NOT VALID``. Once those rows
are dealt with, ``ALTER TABLE … VALIDATE CONSTRAINT`` finishes the job.

Development databases built by the test suite before this migration carry invented
deal ids and will report them; copies of real data did not (checked on the scratch
copy before writing this).

Rollback
--------
The downgrade drops both constraints. Nothing is lost: it changes no row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0042_deal_fks"
down_revision: str | None = "onboarding_0041_map_rule_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: (constraint, table, column) — each to `deal.id`.
FOREIGN_KEYS: tuple[tuple[str, str, str], ...] = (
    ("fk_trade_invoice_deal_id", "trade_invoice", "deal_id"),
    ("fk_exporter_profile_created_via_deal_id", "exporter_profile", "created_via_deal_id"),
)


def _orphans_sql(table: str, column: str) -> str:
    return (
        f"SELECT count(*) FROM {SCHEMA}.{table} t WHERE t.{column} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.deal d WHERE d.id = t.{column})"
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, table, column in FOREIGN_KEYS:
        op.execute(
            f"ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES {SCHEMA}.deal (id) "
            "ON DELETE RESTRICT NOT VALID"
        )
        orphans = int(bind.execute(sa.text(_orphans_sql(table, column))).scalar() or 0)
        if orphans == 0:
            op.execute(f"ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}")
            continue
        print(
            f"onboarding_0042: {orphans} {table} row(s) name a deal that does not exist, "
            f"so {name} is left NOT VALID (it is enforced on every new or changed row). "
            f"List them with: {_orphans_sql(table, column).replace('count(*)', 't.*')}; "
            f"then ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}."
        )


def downgrade() -> None:
    for name, table, _column in reversed(FOREIGN_KEYS):
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT IF EXISTS {name}")
