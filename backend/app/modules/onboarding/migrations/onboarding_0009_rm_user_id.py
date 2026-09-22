"""Add `relationship_manager_user_id` to `exporter_profile`

EXP-F2's frontend role model (`docs/exporter-crm-frontend-tickets.md`) needs
to answer "is the logged-in user this exporter's relationship_manager" to
decide whether an `OPERATIONS`-role user may reveal masked PAN/GSTIN/IEC on
this record — `relationship_manager` alone (a free display string, EXP-1's
deliberate design) can't answer that reliably, per that doc's own flagged
gap.

**No foreign key to `auth.users`, on purpose** — matching this codebase's
established convention for actor/user-reference columns
(`app/modules/cases/application/actor_validation.py`'s docstring: `assigned_to`
and `actor_id` are "plain strings with no foreign key to `auth.users`" by
deliberate choice, validated at the application layer instead via
`require_active_user`, not by a DB constraint; `auth` is documented in its
own baseline migration as "THIS IS THE ONLY MODULE WITH NO EXTERNAL
DEPENDENCY OF ANY KIND"). This column follows the same shape: a bare,
nullable `UUID`, no `ForeignKeyConstraint`.

**Application-layer validation is a deliberate, documented gap, not an
oversight** — nothing yet sets this column (no ticket has built a UI action
that would), so there is nothing to validate against `auth.users` yet.
Whichever ticket first writes to it (a future "assign relationship manager"
action) should add an active-user check mirroring
`cases.application.actor_validation.require_active_user`'s pattern — this
module cannot import that function directly (it lives in `cases`'
`application/`, not a public facade), so it needs its own local equivalent,
not a cross-module import.

Revision ID: onboarding_0009_rm_user_id
Revises: auth_0002_developer_role
Create Date: 2026-09-21

Revision id kept to 26 characters, not the full descriptive name — found the
hard way, by actually running this migration: `alembic_version.version_num`
is `varchar(32)` (Alembic's own default column width, never widened in this
codebase's baseline), and every existing revision id in this repo is quietly
≤32 chars already (e.g. `onboarding_0008_activity_due_idx` is exactly 32).
`onboarding_0009_relationship_manager_user` (41 chars) failed the `UPDATE
alembic_version SET version_num=...` step with `StringDataRightTruncation`
— *after* this migration's own DDL had already run, mid-upgrade-run, which
matters here: this repo's `migrations/env.py` wraps a whole `alembic upgrade
head` invocation in one transaction (see `cases_0002_intake_type.py`'s own
docstring), so that failure rolled back not just this migration but also the
prior `auth_0002_developer_role` step in the same run — except the `ALTER
TYPE ... ADD VALUE` in that migration's `autocommit_block()`, which is not
transactional and stayed committed regardless. Net effect: 'DEVELOPER' really
was added to `user_role_enum` (confirmed via
`SELECT unnest(enum_range(NULL::auth.user_role_enum))`), but
`alembic_version` still showed `onboarding_0008_activity_due_idx` until a
second `alembic upgrade head` run (safe: `ADD VALUE IF NOT EXISTS` is
idempotent) caught it back up. Keep every future revision id in this repo
≤32 characters — this is not a one-off, it's the column's real width.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0009_rm_user_id"
down_revision: str | None = "auth_0002_developer_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    op.add_column(
        "exporter_profile",
        sa.Column(
            "relationship_manager_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("exporter_profile", "relationship_manager_user_id", schema=SCHEMA)
