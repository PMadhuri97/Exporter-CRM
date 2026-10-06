"""A deal's invoicing branch must be its seller's.

Revision ID: onboarding_0036_deal_branch
Revises: onboarding_0035_gst_branch

Why
---
Migration 0028 added ``deal.seller_gst_registration_id`` as a plain FK to
``exporter_gstin.id`` and left it ``NULL``, because nothing wrote it. Task 2.8 is
what writes it, and a plain FK is not enough for the rule that matters: it admits
**any** registration, including another company's. A deal invoiced through a branch
belonging to someone else would put a stranger's GSTIN on the invoice, and the
handover guard would be asking about a branch whose flag belongs to a different
company.

What it does
------------
#. Replaces the single-column FK with a **composite** one,
   ``(seller_gst_registration_id, company_id)`` → ``(exporter_gstin.id, customer_id)``,
   against the unique key 0035 added for exactly this. The database now refuses a
   deal pointing at another company's branch; ``DealService`` checks it too, so the
   caller gets a 422 naming the problem rather than an integrity error.

   ``ON DELETE RESTRICT`` is kept and is now doubly moot: ``exporter_gstin`` rows
   cannot be deleted at all since 0035.
#. Adds ``seller_gst_registration_id`` to ``prevent_terminal_deal_change()``, so a
   closed deal's invoicing branch no longer changes. Before handover it may be set
   and **changed** freely ("may be set any time before handover") —
   unlike ``buyer_company_id``, which is set once, because choosing the wrong branch
   has no consequence until the handover reads it, while a buyer company accumulates
   compliance results under it.

Replacing the freeze function, carefully
---------------------------------------
``CREATE OR REPLACE FUNCTION`` rewrites the whole body, so this restates every rule
the function carries: 0022's list, 0029's ``handover_snapshot`` set-once block, and
0034's ``buyer_company_id``. Rebuilding from any one of those alone would silently
drop the others — which is a mistake this project has made once already, in 0034's
first draft, caught by ``test_handover_snapshot.py``'s direct-SQL tests.

Rollback
--------
The downgrade restores 0028's single-column FK and 0034's function body. It removes
a guard; it loses no data. A deal already pointing at another company's branch would
be impossible to create under the composite FK, so there is nothing to clean up —
but note that the downgrade **cannot** detect one if a future migration introduced
it, so check before re-upgrading.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0036_deal_branch"
down_revision: str | None = "onboarding_0035_gst_branch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

_FK = "fk_deal_seller_gst_registration_id"


def _freeze_function(*, freeze_branch: bool) -> str:
    """Every rule ``prevent_terminal_deal_change()`` carries, in one builder.

    0022's columns, 0034's ``buyer_company_id``, this migration's
    ``seller_gst_registration_id``, and 0029's snapshot block — all of it, because
    ``CREATE OR REPLACE`` keeps nothing.
    """
    branch_line = (
        "            OR NEW.seller_gst_registration_id IS DISTINCT FROM OLD.seller_gst_registration_id\n"
        if freeze_branch
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_terminal_deal_change()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND (NEW.stage IS DISTINCT FROM OLD.stage
            OR NEW.handed_over_at IS DISTINCT FROM OLD.handed_over_at
            OR NEW.withdrawal_reason IS DISTINCT FROM OLD.withdrawal_reason
            OR NEW.company_id IS DISTINCT FROM OLD.company_id
            OR NEW.buyer_company_id IS DISTINCT FROM OLD.buyer_company_id
{branch_line}            OR NEW.reference IS DISTINCT FROM OLD.reference)
    THEN
        RAISE EXCEPTION
            'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
    END IF;

    -- 0029's rule, restated because CREATE OR REPLACE rewrites the whole body.
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND OLD.handover_snapshot IS NOT NULL
       AND NEW.handover_snapshot IS DISTINCT FROM OLD.handover_snapshot
    THEN
        RAISE EXCEPTION
            'deal %: its handover snapshot is what the lending team was given and does not change',
            OLD.id;
    END IF;

    RETURN NEW;
END;
$fn$;
"""


def upgrade() -> None:
    op.drop_constraint(_FK, "deal", type_="foreignkey", schema=SCHEMA)
    op.create_foreign_key(
        _FK,
        "deal",
        "exporter_gstin",
        ["seller_gst_registration_id", "company_id"],
        ["id", "customer_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.execute(_freeze_function(freeze_branch=True))


def downgrade() -> None:
    op.execute(_freeze_function(freeze_branch=False))
    op.drop_constraint(_FK, "deal", type_="foreignkey", schema=SCHEMA)
    op.create_foreign_key(
        _FK,
        "deal",
        "exporter_gstin",
        ["seller_gst_registration_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
