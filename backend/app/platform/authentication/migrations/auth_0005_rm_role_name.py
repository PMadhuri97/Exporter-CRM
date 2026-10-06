"""The built-in OPERATIONS role is shown as "RM (Relationship Manager)"

`auth_0004_rbac` seeded the built-in roles' display names into `auth.role`, and
that row — not `catalog.py`'s `BUILTIN_ROLE_METADATA`, which nothing reads at
runtime — is what the product shows: the Roles tab, the user form's role picker,
and "Signed in as …" on Settings. So the rename has to reach
the row.

Only the display name and description change. The slug stays `operations` and the
`builtin_role` stays `OPERATIONS`: both are written into rows already recorded and
into every route-authorisation table. The old description also promised an
ownership exception ("masked unless you own the record") that decision 12 removed.

An administrator may already have renamed the role — built-in roles are editable
by decision — so each column changes only where it still holds the seeded value.

Revision ID: auth_0005_rm_role_name
Revises: onboarding_0031_domestic_first
Create Date: 2026-10-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0005_rm_role_name"
down_revision: str | None = "onboarding_0031_domestic_first"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"

_OLD_NAME = "Operations"
_NEW_NAME = "RM (Relationship Manager)"
_OLD_DESCRIPTION = "Day-to-day CRM work. Tax identifiers are masked unless you own the record."
_NEW_DESCRIPTION = (
    "Day-to-day CRM work: companies, contacts, activities and deals. "
    "Tax identifiers are always masked."
)


def _swap(column: str, old: str, new: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.role SET {column} = :new, updated_at = now() "
            f"WHERE builtin_role = 'OPERATIONS' AND {column} = :old"
        ).bindparams(sa.bindparam("old", value=old), sa.bindparam("new", value=new))
    )


def upgrade() -> None:
    _swap("name", _OLD_NAME, _NEW_NAME)
    _swap("description", _OLD_DESCRIPTION, _NEW_DESCRIPTION)


def downgrade() -> None:
    _swap("name", _NEW_NAME, _OLD_NAME)
    _swap("description", _NEW_DESCRIPTION, _OLD_DESCRIPTION)
