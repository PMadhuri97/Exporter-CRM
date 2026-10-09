"""Permission to confirm a sanctions true match as head of compliance

``compliance:approve_true_match`` — used when ``CRM_SANCTIONS_TRUE_MATCH_APPROVAL`` is
``HEAD``: a proposed true match is confirmed only by a holder. Granted to the Compliance
lead role (and any role that already approves high-risk Clears), never to a built-in
role by default.

Revision ID: auth_0010_true_match_permission
Revises: onboarding_0052_sanctions
Create Date: 2026-10-09
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0010_true_match_permission"
down_revision: str | None = "onboarding_0052_sanctions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"
GRANT = ("compliance", "approve_true_match")


def upgrade() -> None:
    conn = op.get_bind()
    roles = conn.execute(
        sa.text(
            f"SELECT r.id FROM {SCHEMA}.role r WHERE r.slug = 'compliance-lead' OR EXISTS ("
            f"SELECT 1 FROM {SCHEMA}.role_permission rp WHERE rp.role_id = r.id "
            "AND rp.module = 'compliance' AND rp.action = 'approve_high_risk')"
        )
    ).all()
    for (role_id,) in roles:
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.role_permission (id, role_id, module, action) "
                "VALUES (:id, :role_id, :module, :action) "
                "ON CONFLICT ON CONSTRAINT uq_role_permission_role_module_action DO NOTHING"
            ),
            {"id": uuid.uuid4(), "role_id": role_id, "module": GRANT[0], "action": GRANT[1]},
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.role_permission WHERE module = :module AND action = :action"
        ),
        {"module": GRANT[0], "action": GRANT[1]},
    )
