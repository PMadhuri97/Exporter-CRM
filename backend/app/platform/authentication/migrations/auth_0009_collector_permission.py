"""Permission to name a company's collections owner

``exporters:assign_collector`` goes to COMPLIANCE, and to every role that may already
assign relationship managers (``exporters:assign_rm`` — the Sales lead among them):
whoever arranges who sells to a company also arranges who collects from it. Not to the
administrator, which reads the business and does not run it.

Additions only. Transcribed rather than imported from the catalogue, for the reason
``auth_0004_rbac`` gives.

Revision ID: auth_0009_collector_permission
Revises: onboarding_0050_collector
Create Date: 2026-10-09
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0009_collector_permission"
down_revision: str | None = "onboarding_0050_collector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"
GRANT = ("exporters", "assign_collector")


def upgrade() -> None:
    conn = op.get_bind()
    roles = conn.execute(
        sa.text(
            f"SELECT r.id FROM {SCHEMA}.role r WHERE r.builtin_role = 'COMPLIANCE' "
            f"OR r.slug = 'compliance-lead' OR EXISTS ("
            f"SELECT 1 FROM {SCHEMA}.role_permission rp WHERE rp.role_id = r.id "
            "AND rp.module = 'exporters' AND rp.action = 'assign_rm')"
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
