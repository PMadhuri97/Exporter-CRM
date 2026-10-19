"""Sign-in lockout, and a session id that lets an access token be revoked

* ``users.failed_login_attempts`` / ``users.locked_until`` — wrong passwords in a row,
  and until when sign-in is refused after too many (``LOGIN_MAX_FAILED_ATTEMPTS``,
  ``LOGIN_LOCKOUT_MINUTES``).
* ``refresh_tokens.session_id`` — one sign-in across every rotation of its refresh
  token. Access tokens carry it as ``sid`` and are refused once the session has no live
  refresh token, so logging out ends them at once. Each existing row becomes its own
  session (``session_id = id``), which is exactly what it was.

Revision ID: auth_0011_login_lockout_sessions
Revises: onboarding_0061_drop_columns
Create Date: 2026-10-19
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "auth_0011_login_lockout_sessions"
down_revision: str | None = "onboarding_0061_drop_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=SCHEMA,
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    op.add_column(
        "refresh_tokens",
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.execute(f"UPDATE {SCHEMA}.refresh_tokens SET session_id = id WHERE session_id IS NULL")
    op.alter_column("refresh_tokens", "session_id", nullable=False, schema=SCHEMA)
    op.create_index(
        "ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens", schema=SCHEMA)
    op.drop_column("refresh_tokens", "session_id", schema=SCHEMA)
    op.drop_column("users", "locked_until", schema=SCHEMA)
    op.drop_column("users", "failed_login_attempts", schema=SCHEMA)
