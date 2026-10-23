"""Sessions end after inactivity and after a maximum length.

Revision ID: auth_0011_session_limits
Revises: onboarding_0065_sealed_regno

Why
---
A refresh token lasted seven days and every rotation issued another seven, so a session
left open was never ended: a browser could be walked away from on a Monday and still be
signed in the next. A link opened from an email went straight into the CRM on the
strength of it.

From here a refresh token lives one inactivity timeout (``SESSION_IDLE_TIMEOUT_MINUTES``:
30 minutes in production, 60 elsewhere), and the browser exchanges it only for someone
actually using the page, so a session nobody touches ends on the server, not only in
the browser. However active, a session ends ``SESSION_MAX_HOURS`` after its sign-in,
which is what ``session_started_at`` records and every rotation carries forward.

Existing tokens
---------------
Each row is given its own ``created_at`` as its session start, and every token still
live is cut to 30 minutes from now — the production timeout, the stricter of the two —
so a seven-day token issued before this revision cannot outlast it. Someone active
keeps working; someone away signs in again.

Rollback
--------
Drops the column. Tokens keep the expiry they have; the old code then issues
seven-day tokens again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0011_session_limits"
down_revision: str | None = "onboarding_0065_sealed_regno"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"
TABLE = "refresh_tokens"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.{TABLE} SET session_started_at = created_at"  # noqa: S608
    )
    op.execute(
        f"UPDATE {SCHEMA}.{TABLE} "  # noqa: S608
        "SET expires_at = LEAST(expires_at, now() + interval '30 minutes') "
        "WHERE NOT revoked AND expires_at > now()"
    )
    op.alter_column(
        TABLE,
        "session_started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(TABLE, "session_started_at", schema=SCHEMA)
