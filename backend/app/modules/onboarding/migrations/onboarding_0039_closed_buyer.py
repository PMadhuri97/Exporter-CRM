"""A closed deal's buyer company may be **filled in** once.

Revision ID: onboarding_0039_closed_buyer
Revises: onboarding_0038_buyer_map

Why
---
Migration 0036 added ``buyer_company_id`` to ``prevent_terminal_deal_change()``, so
a closed deal's buyer company could not change. That is right, and it was one
condition too strong: it refused **any** difference, including ``NULL`` → a value,
which is the write the buyer migration has to make.

§17.2 requires every deal with a ``deal_buyer`` row to end up with a
``buyer_company_id``, terminal deals included — a deal handed over last year still
has a buyer, and leaving it unlinked would make its buyer's trade history and
compliance results unreachable from the deal that produced them. 0029 had already
set the precedent for exactly this situation on ``handover_snapshot``: *"the trigger
lets it go from ``NULL`` to a value on a terminal deal, so a deal handed over before
snapshots existed can be filled in by a migration, and refuses every change after
that."* ``buyer_company_id`` wants the same rule and did not get it.

Found by writing 2.6's tests, which is the point of writing them: the migration could
not link a withdrawn deal, and no amount of reading the trigger would have been as
convincing as a test that failed.

What changes
------------
In ``prevent_terminal_deal_change()``, ``buyer_company_id`` moves out of the "any
difference" list and into its own clause: refused only when the **old** value was not
``NULL``. ``trg_deal_buyer_company_set_once`` is unchanged and still refuses a second
*different* company on an open deal, so the column remains set-once everywhere — this
only stops the terminal freeze from being stricter than set-once for no reason.

Everything else the function carries is restated, because ``CREATE OR REPLACE
FUNCTION`` keeps nothing: 0022's columns, 0029's snapshot clause, 0036's
``seller_gst_registration_id``.

Rollback
--------
The downgrade restores 0036's body, in which a closed deal's ``buyer_company_id``
cannot be written at all. Do not downgrade with a buyer migration pending — it would
leave terminal deals permanently unlinkable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0039_closed_buyer"
down_revision: str | None = "onboarding_0038_buyer_map"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def _freeze_function(*, buyer_company_set_once: bool) -> str:
    """The whole function. ``buyer_company_set_once`` picks this migration's rule
    (``NULL`` → a value allowed once) over 0036's (no write at all)."""
    if buyer_company_set_once:
        buyer_in_list = ""
        buyer_clause = """
    -- The buyer company may be **filled in** on a closed deal and never changed
    -- (§17.2): a deal handed over before the buyer migration still has a buyer, and
    -- the migration is what links it. The same shape as the snapshot rule below.
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND OLD.buyer_company_id IS NOT NULL
       AND NEW.buyer_company_id IS DISTINCT FROM OLD.buyer_company_id
    THEN
        RAISE EXCEPTION
            'deal %: its buyer company is what the lending team was given and does not change',
            OLD.id;
    END IF;
"""
    else:
        buyer_in_list = (
            "            OR NEW.buyer_company_id IS DISTINCT FROM OLD.buyer_company_id\n"
        )
        buyer_clause = ""

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
{buyer_in_list}            OR NEW.seller_gst_registration_id IS DISTINCT FROM OLD.seller_gst_registration_id
            OR NEW.reference IS DISTINCT FROM OLD.reference)
    THEN
        RAISE EXCEPTION
            'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
    END IF;
{buyer_clause}
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
    op.execute(_freeze_function(buyer_company_set_once=True))


def downgrade() -> None:
    op.execute(_freeze_function(buyer_company_set_once=False))
