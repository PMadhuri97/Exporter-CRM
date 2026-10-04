"""The buyer migration can say "this buyer was already linked to that company" —
**owner: Developer 2** (allocation task 2.6, plan P4-6, ``remaining-work.md`` R-07).

Revision ID: onboarding_0041_map_rule_link
Revises: onboarding_0040_iec_format

Why
---
Since task 2.4 a user can name a deal's buyer **company** on the deal page, and a deal
written before that also carries a legacy ``deal_buyer`` row. Since P4-5 a BUYER
result can carry a ``subject_company_id``. Both links are set once and frozen, so the
buyer migration must map such a row to the company it is already linked to: mapping
it anywhere else would leave the deal, or its results, naming a company the map does
not.

``deal_buyer_company_map.match_rule`` records *why* each row maps where it does, and
none of 0038's four values is true for this case: no identifier matched (``PAN``,
``REGISTRATION_NUMBER``), no company was created (``NEW``), and nobody confirmed a
name in the migration's report (``NAME_CONFIRMED``). The link existed before the
migration ran. ``ALREADY_LINKED`` says exactly that.

Data
----
None. It adds an enum value and changes no row.

Rollback
--------
Postgres cannot drop one value from an enum, so the downgrade rebuilds the type
without it. It **refuses** while any mapping row uses the value: those rows are the
record of what a run decided, and the table is append-only, so the right response is
to restore the ``pg_dump`` taken before that run rather than to lose the reason.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0041_map_rule_link"
down_revision: str | None = "onboarding_0040_iec_format"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
VALUE = "ALREADY_LINKED"
#: 0038's values, the type the downgrade rebuilds.
PREVIOUS_VALUES = ("PAN", "REGISTRATION_NUMBER", "NEW", "NAME_CONFIRMED")


def upgrade() -> None:
    # Allowed inside a transaction since Postgres 12, as long as nothing in the same
    # transaction uses the new value — nothing here does.
    op.execute(f"ALTER TYPE {SCHEMA}.buyer_match_rule_enum ADD VALUE IF NOT EXISTS '{VALUE}'")


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM {SCHEMA}.deal_buyer_company_map
                WHERE match_rule::text = '{VALUE}'
            ) THEN
                RAISE EXCEPTION
                    'deal_buyer_company_map has rows with match_rule {VALUE}: they record '
                    'what a buyer migration run decided, and the table is append-only. '
                    'Restore the pg_dump taken before that run instead of downgrading.';
            END IF;
        END
        $$;
        """
    )
    values = ", ".join(f"'{value}'" for value in PREVIOUS_VALUES)
    op.execute(f"ALTER TYPE {SCHEMA}.buyer_match_rule_enum RENAME TO buyer_match_rule_enum_old")
    op.execute(f"CREATE TYPE {SCHEMA}.buyer_match_rule_enum AS ENUM ({values})")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.deal_buyer_company_map
        ALTER COLUMN match_rule TYPE {SCHEMA}.buyer_match_rule_enum
        USING match_rule::text::{SCHEMA}.buyer_match_rule_enum
        """
    )
    op.execute(f"DROP TYPE {SCHEMA}.buyer_match_rule_enum_old")
