"""``deal.buyer_company_id`` becomes set-once and freezes with the deal.

Revision ID: onboarding_0034_deal_buyer_co
Revises: onboarding_0033_created_via

Why
---
Migration 0028 added the column, its FK and ``ck_deal_buyer_is_not_the_seller``,
and left it ``NULL`` on every deal because nothing wrote it yet. Task 2.4 is what
writes it, and that makes two rules enforceable that could not be enforced while
the column was dead:

#. **Set once.** Once a deal names its buyer company, that is the company. The
   buyer's sanctions and AML results are recorded against it and read back through
   it (``for_company(buyer_company_id)``, contract §3.0), the handover guard's
   condition 5 asks about *that* company, and the handover snapshot records
   it. Re-pointing the column afterwards would silently reinterpret all of that:
   checks somebody ran on one company would start answering for another, and no
   row would record that it had happened. A deal pointed at the wrong buyer is
   withdrawn and reopened, which leaves a trail.

   ``prevent_field_mutation_when_set`` is the right shape: ``NULL`` → a value is
   allowed once, so the buyer migration can still fill a deal whose buyer
   is only a ``deal_buyer`` row today, and every later change is refused.

#. **Frozen with the deal.** ``prevent_terminal_deal_change()`` already refuses
   changes to a closed deal's ``stage``, ``handed_over_at``,
   ``withdrawal_reason``, ``company_id`` and ``reference``. This migration adds
   ``buyer_company_id``: a handed-over deal's buyer is what the lending team was
   given.

The two guards overlap deliberately, and neither makes the other redundant. The
set-once rule applies to deals that are still open — which is where the mistake
actually gets made — and the terminal freeze also refuses a *first* write to a
closed deal, which set-once would permit.

Replacing the freeze function, carefully
---------------------------------------
``CREATE OR REPLACE FUNCTION`` rewrites the **whole** body, so this migration has
to restate every rule the function already carries, not just its own. There are
two, from two migrations: 0022's "a closed deal no longer changes" list, and
**0029's separate block making ``handover_snapshot`` set-once**. Rebuilding from
0022 alone would quietly drop the snapshot rule and let a handed-over deal's
snapshot be rewritten — a record of what the lending team was given, silently
editable. ``_FREEZE_FUNCTION`` below is 0029's body with ``buyer_company_id``
added to its first condition, and the downgrade restores 0029's body exactly.

(The first version of this migration did drop that block. Migration register §2's
rule — every constraint gets a direct-SQL violation test — is what caught it, in
``test_handover_snapshot.py``. Worth recording, because the next migration to
touch this function faces the same trap.)

Rollback
--------
The downgrade drops the set-once trigger and restores
``prevent_terminal_deal_change()`` to the 0029 body (without
``buyer_company_id``, with the snapshot rule). It removes guards; it loses no
data.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0034_deal_buyer_co"
down_revision: str | None = "onboarding_0033_created_via"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def _freeze_function(*, freeze_buyer_company: bool) -> str:
    """0029's function body, optionally with ``buyer_company_id`` frozen too.

    One builder for both directions, so the upgrade and the downgrade cannot drift
    in the way the module docstring describes.
    """
    buyer_line = (
        "            OR NEW.buyer_company_id IS DISTINCT FROM OLD.buyer_company_id\n"
        if freeze_buyer_company
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
{buyer_line}            OR NEW.reference IS DISTINCT FROM OLD.reference)
    THEN
        RAISE EXCEPTION
            'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
    END IF;

    -- 0029's rule, restated because CREATE OR REPLACE rewrites the whole body.
    -- Set once, then never again: a snapshot may be filled in for a deal handed
    -- over before snapshots existed (0029, and the buyer migration), but what
    -- the lending team was given is never rewritten.
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
    op.execute(_freeze_function(freeze_buyer_company=True))
    op.execute(
        f"""
        CREATE TRIGGER trg_deal_buyer_company_set_once
        BEFORE UPDATE ON {SCHEMA}.deal
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('buyer_company_id');
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_deal_buyer_company_set_once ON {SCHEMA}.deal;"
    )
    op.execute(_freeze_function(freeze_buyer_company=False))
