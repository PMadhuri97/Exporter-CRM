"""``deal_buyer`` is frozen: no new legacy buyer, and none is edited.

Revision ID: onboarding_0058_buyer_freeze
Revises: onboarding_0057_people

Why
---
A deal names its buyer as a **company** (``deal.buyer_company_id``): chosen from the
directory or created on the spot. The typed-in buyer, ``deal_buyer``, is what deals
written before that carry. The CRM no longer writes one — the old buyer form and
``DealService.set_buyer`` are gone — and the database now says so too:

* an ``INSERT`` is refused;
* an ``UPDATE`` is refused if it changes any of the row's own columns (``deal_id``,
  ``name``, ``country``, ``registration_number``, ``tax_id``, ``contact_email``,
  ``contact_phone``, ``id``, ``created_at``).

The buyer migration's five mapping columns (0056) stay writable, still once each
(``trg_deal_buyer_mapping_set_once``), so ``migrate_deal_buyers`` can map rows after the
freeze; so does ``updated_at``. ``DELETE`` is unchanged: the row goes with its deal
(``ON DELETE CASCADE``), and a deal is never deleted.

The function, ``onboarding.prevent_deal_buyer_change()``, is this table's own: its
message says what to do instead.

Data
----
None.

Rollback
--------
The downgrade drops the trigger and the function.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0058_buyer_freeze"
down_revision: str | None = "onboarding_0057_people"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The row's own columns: frozen. The mapping columns and `updated_at` are not listed.
FROZEN = (
    "id",
    "deal_id",
    "name",
    "country",
    "registration_number",
    "tax_id",
    "contact_email",
    "contact_phone",
    "created_at",
)


def upgrade() -> None:
    new = ", ".join(f"NEW.{column}" for column in FROZEN)
    old = ", ".join(f"OLD.{column}" for column in FROZEN)
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.prevent_deal_buyer_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RAISE EXCEPTION 'deal_buyer is frozen: a deal names its buyer as a company '
                    '(deal.buyer_company_id), and no new legacy buyer is recorded';
            END IF;
            IF ROW({new}) IS DISTINCT FROM ROW({old}) THEN
                RAISE EXCEPTION 'deal_buyer is frozen: a legacy buyer is not edited; only '
                    'the buyer migration''s mapping columns may be filled';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_deal_buyer_frozen
        BEFORE INSERT OR UPDATE ON {SCHEMA}.deal_buyer
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_deal_buyer_change();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_deal_buyer_frozen ON {SCHEMA}.deal_buyer")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_deal_buyer_change()")
