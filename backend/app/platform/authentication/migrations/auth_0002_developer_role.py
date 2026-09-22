"""Add DEVELOPER to user_role_enum

Frontend PII-masking design (`docs/exporter-crm-frontend-tickets.md`) needs a
role distinct from `API_USER` for internal technical staff who must never be
able to reveal masked PAN/GSTIN/identifier fields, under any circumstance —
unlike `OPERATIONS` (which can reveal on exporters it owns) or
`COMPLIANCE`/`ADMIN` (which always can). `API_USER` stays reserved for
external/system API callers (relevant once Epic 4.4's paused customer API
resumes) — conflating "external caller" and "internal engineer with system
access" under one role name would cause its own problems once that surface
exists.

This migration only adds the enum value, following the established
autocommit-block pattern
(`app/modules/cases/migrations/cases_0002_intake_type.py`) since Postgres
refuses to let a freshly `ALTER TYPE ... ADD VALUE`'d label be referenced
until that ADD VALUE has committed. Nothing here uses the new value yet — no
default is assigned, no existing row is touched.

Revision ID: auth_0002_developer_role
Revises: onboarding_0008_activity_due_idx
Create Date: 2026-09-21
"""
from collections.abc import Sequence

from alembic import op

revision: str = "auth_0002_developer_role"
down_revision: str | None = "onboarding_0008_activity_due_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {SCHEMA}.user_role_enum ADD VALUE IF NOT EXISTS 'DEVELOPER'"
        )


def downgrade() -> None:
    # Postgres has no supported way to remove a value from an existing enum
    # type without recreating it — the same non-goal every other enum-value-add
    # migration in this codebase already accepts.
    pass
