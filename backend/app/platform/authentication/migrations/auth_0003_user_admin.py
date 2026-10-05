"""Add the columns administrator-facing user management needs

User management (an admin-managed user list, self-service profile
and password changes) needs four facts about an account that the `auth.users`
row cannot currently express:

* `is_verified` — whether an administrator created the account, as opposed to
  it arriving through self-service sign-up. There is no email-confirmation
  round-trip yet, so this records provenance only; it must not be read as
  proof that the address belongs to the person.
* `last_login_at` — stamped by `POST /auth/login`. An administrator deciding
  whether an account is still in use needs "never signed in" to be a visible
  state, which is why it is nullable rather than defaulted to now().
* `created_by` — the administrator who created the account. Self-referential
  FK with ON DELETE SET NULL: removing an administrator must never cascade
  into removing the accounts they created.
* `deactivated_at` — when `is_active` last went false, cleared again on
  reactivation. Deliberately a current-state column, not a log; who
  deactivated whom belongs in the shared history log, not here.

All four are nullable or defaulted, so existing rows upgrade without a
backfill and the downgrade is a clean drop.

Revision ID: auth_0003_user_admin
Revises: onboarding_0015_bg_check
Create Date: 2026-09-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "auth_0003_user_admin"
# Re-parented when `main` was merged in. It was written against
# `onboarding_0012_risk_critical`, which `onboarding_0013_shared_history` has since
# taken as its parent on `main`; leaving it there would give that revision two
# children and Alembic two heads. Nothing in this migration depends on the
# onboarding schema — the parent only fixes where it sits in the order.
down_revision: str | None = "onboarding_0015_bg_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "users",
        # `auth.users.id` is a native Postgres UUID; the FK column must match.
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "users",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_users_created_by_users",
        source_schema=SCHEMA,
        source_table="users",
        referent_schema=SCHEMA,
        referent_table="users",
        local_cols=["created_by"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    # An administrator's default list view is "active accounts, newest first",
    # and the role filter is the next thing they reach for.
    op.create_index(
        "ix_users_is_active_role",
        "users",
        ["is_active", "role"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_users_is_active_role", table_name="users", schema=SCHEMA)
    op.drop_constraint(
        "fk_users_created_by_users", "users", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column("users", "deactivated_at", schema=SCHEMA)
    op.drop_column("users", "created_by", schema=SCHEMA)
    op.drop_column("users", "last_login_at", schema=SCHEMA)
    op.drop_column("users", "is_verified", schema=SCHEMA)
