"""platform bootstrap — shared immutability function

The single object that is genuinely cross-cutting and belongs to no module:
``public.prevent_mutation()``. Twelve triggers across eight schemas execute
it — payments, audit, compliance, messaging, reconciliation, onboarding,
ledger and settlement — so it must exist before any of them are created.
This revision stays first in the chain for that reason, alongside the other
migrations with no single module owner (``b7e4c9a15d20``)
that also live in this directory.

It lives in ``public`` deliberately. It is not a module object, it owns no
data, and every consuming trigger references it schema-qualified as
``public.prevent_mutation()`` so the reference cannot be broken by a
search_path change.

Note for anyone tempted to make DELETE work: this function blocks DELETE as
well as UPDATE, which is why a migration that needs to clear an append-only
table must use TRUNCATE — row-level triggers do not fire on truncate.

Replaces ``41735b67723b_initial_schema``, deleted by the AL-550 squash: that
revision originally created 16 tables, 21 enums and four immutability
triggers spanning seven modules, all of which are now owned by their
module's own baseline migration inside a dedicated PostgreSQL schema. This
migration carries forward only the one object squashing could not assign to
a module, under a fresh revision id so the old root migration is fully gone
from the chain.

Revision ID: a0b1c2d3e4f5
Revises:
Create Date: 2026-08-07

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a0b1c2d3e4f5'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Shared function — raises on any UPDATE or DELETE attempt. TG_TABLE_NAME
    # keeps the message specific to whichever table's trigger fired.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.prevent_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is immutable: UPDATE and DELETE are forbidden',
                TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Every dependent trigger is dropped by its own module's downgrade, which
    # runs first on a linear chain.
    op.execute("DROP FUNCTION IF EXISTS public.prevent_mutation()")
