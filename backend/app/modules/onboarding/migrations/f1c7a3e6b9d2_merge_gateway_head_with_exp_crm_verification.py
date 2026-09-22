"""merge gateway head with EXP-1/EXP-2 exporter CRM + verification heads

Reconciliation for the EXP-1 (exp-1-crm) / EXP-2 (exp-2-verification) build,
each done in its own git worktree from the same starting point (`master` at
`d1e0e88`). Both worktrees independently chained their own migration
(`onboarding_0005_exporter_crm`, `onboarding_0006_verif_result`) onto
`onboarding_0004_screening_fix`, believing it to be the current head — it
was not: `2807a84d72ba` (this repo's own gateway-integration merge point,
see its docstring) already sat downstream of `onboarding_0004_screening_fix`
in `master` before either EXP worktree was created, so `master`'s actual
head at branch time was `2807a84d72ba`, not `onboarding_0004_screening_fix`.

Two distinct forks resulted from merging both worktrees into `master`, and
each was fixed the way this codebase's own history already establishes for
its kind:

1. `onboarding_0005_exporter_crm` vs. `onboarding_0006_verif_result` — both
   unreleased, never applied anywhere but a disposable, per-ticket test
   container. Fixed with a direct, in-place edit of
   `onboarding_0006_verif_result.down_revision` (now
   `onboarding_0005_exporter_crm`) rather than a merge revision — see that
   file's own "Fork note" docstring for the full reasoning.
2. `2807a84d72ba` vs. the now-linear `onboarding_0005_exporter_crm` ->
   `onboarding_0006_verif_result` chain — `2807a84d72ba` was already real,
   on-branch history in `master`. This is the same situation
   `2807a84d72ba` itself was created to resolve (and `e849a8d1c41e_merge_
   al_669_with_develop_heads.py` before it): a plain no-op merge revision,
   not a rewrite of anything. This file is that merge revision.

Revision ID: f1c7a3e6b9d2
Revises: 2807a84d72ba, onboarding_0006_verif_result
Create Date: 2026-09-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c7a3e6b9d2'
down_revision: Union[str, None] = ('2807a84d72ba', 'onboarding_0006_verif_result')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
