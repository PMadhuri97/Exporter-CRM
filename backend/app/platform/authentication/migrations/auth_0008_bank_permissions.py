"""Permissions for a company's bank accounts

* ``exporters:manage_bank_accounts`` — propose a new account or a change (OPERATIONS,
  COMPLIANCE).
* ``exporters:approve_bank_accounts`` — approve or reject a proposal, and verify an
  account (COMPLIANCE).
* ``exporters:view_bank_details`` — reveal a full account number or IBAN (COMPLIANCE);
  every reveal is audited.

Additions only. Each built-in role gets its grants whether or not an administrator has
edited it; a custom role gets those of the built-in role its holders are based on, and
the two lead roles those of the role they extend.

Transcribed rather than imported from the catalogue, for the reason ``auth_0004_rbac``
gives.

Revision ID: auth_0008_bank_permissions
Revises: onboarding_0048_bank_accounts
Create Date: 2026-10-09
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0008_bank_permissions"
down_revision: str | None = "onboarding_0048_bank_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"

MANAGE = ("exporters", "manage_bank_accounts")
APPROVE = ("exporters", "approve_bank_accounts")
REVEAL = ("exporters", "view_bank_details")

GRANTS: dict[str, frozenset[tuple[str, str]]] = {
    "OPERATIONS": frozenset({MANAGE}),
    "COMPLIANCE": frozenset({MANAGE, APPROVE, REVEAL}),
}
#: The lead roles auth_0007 created, and the built-in role each extends.
LEAD_ROLE_BASE = {"compliance-lead": "COMPLIANCE", "sales-lead": "OPERATIONS"}


def _add(conn, role_id, grants) -> None:
    for module, action in sorted(grants):
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.role_permission (id, role_id, module, action) "
                "VALUES (:id, :role_id, :module, :action) "
                "ON CONFLICT ON CONSTRAINT uq_role_permission_role_module_action DO NOTHING"
            ),
            {"id": uuid.uuid4(), "role_id": role_id, "module": module, "action": action},
        )


def upgrade() -> None:
    conn = op.get_bind()
    roles = conn.execute(sa.text(f"SELECT id, builtin_role, slug FROM {SCHEMA}.role")).all()
    for role_id, builtin, slug in roles:
        if builtin is not None:
            _add(conn, role_id, GRANTS.get(str(builtin), frozenset()))
            continue
        bases = {LEAD_ROLE_BASE[slug]} if slug in LEAD_ROLE_BASE else {
            str(row[0])
            for row in conn.execute(
                sa.text(f"SELECT DISTINCT role FROM {SCHEMA}.users WHERE role_id = :id"),
                {"id": role_id},
            )
        }
        for base in bases:
            _add(conn, role_id, GRANTS.get(base, frozenset()))


def downgrade() -> None:
    conn = op.get_bind()
    for module, action in (MANAGE, APPROVE, REVEAL):
        conn.execute(
            sa.text(
                f"DELETE FROM {SCHEMA}.role_permission WHERE module = :module AND action = :action"
            ),
            {"module": module, "action": action},
        )
