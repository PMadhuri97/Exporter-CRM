"""The built-in ADMIN role is granted the three assignment permissions

The catalogue gained `exporters:assign_rm`, `compliance:assign` and
`compliance:approve_high_risk`. Every route that consults them checks "ADMIN role or the
permission", so administrators can act without these rows; they are seeded anyway so the
Roles screen shows ADMIN holding them, as `auth_0004_rbac` seeded ADMIN with everything
that existed then.

No other role is granted them. They are meant for custom lead roles and named senior
users, which an administrator grants in role management.

Transcribed rather than imported from the catalogue, for the reason `auth_0004_rbac`
gives. `ON CONFLICT DO NOTHING` leaves a grant an administrator already made alone.

Revision ID: auth_0006_assignment_perms
Revises: onboarding_0044_assignment
Create Date: 2026-10-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0006_assignment_perms"
down_revision: str | None = "onboarding_0044_assignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"

_GRANTS = (
    ("exporters", "assign_rm"),
    ("compliance", "assign"),
    ("compliance", "approve_high_risk"),
)


def upgrade() -> None:
    for module, action in _GRANTS:
        op.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.role_permission (id, role_id, module, action) "
                f"SELECT gen_random_uuid(), id, :module, :action FROM {SCHEMA}.role "
                "WHERE builtin_role = 'ADMIN' "
                "ON CONFLICT ON CONSTRAINT uq_role_permission_role_module_action DO NOTHING"
            ).bindparams(module=module, action=action)
        )


def downgrade() -> None:
    for module, action in _GRANTS:
        op.execute(
            sa.text(
                f"DELETE FROM {SCHEMA}.role_permission "
                "WHERE module = :module AND action = :action"
            ).bindparams(module=module, action=action)
        )
