"""merge gateway module baseline with onboarding heads (epic4-reference integration)

epic4-reference-specific merge point. It does not exist in the source
monorepo's own history: gateway_0001_baseline comes from a sibling git
worktree/branch (feature/epic4.4-customer-api) that has never been merged
into feature/epic4-onboarding-orchestration — the branch this reference
checkout's other migrations were taken from. Both branches added a migration
directly on top of 0a772fd562e8, so pulling gateway's module code into this
reference repo (see RUNNING.md) left two real, divergent Alembic heads.

This is a plain no-op merge revision — the standard Alembic pattern already
used throughout this codebase's own history for exactly this situation
(see e.g. 0a772fd562e8 itself, or 87608d21fcb5). It does not alter, rewrite,
or reorder any existing migration.

Revision ID: 2807a84d72ba
Revises: gateway_0001_baseline, onboarding_0004_screening_fix
Create Date: 2026-09-19 19:24:06.317786

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2807a84d72ba'
down_revision: Union[str, None] = ('gateway_0001_baseline', 'onboarding_0004_screening_fix')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
