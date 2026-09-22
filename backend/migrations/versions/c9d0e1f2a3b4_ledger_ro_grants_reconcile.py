"""reconcile ledger_ro grants onto databases that predate b7e4c9a15d20

WHY THIS REVISION EXISTS
------------------------
AL-551 introduced `b7e4c9a15d20` with `down_revision = settlement_0001_baseline`
— that is, it was inserted *behind* an already-applied head rather than appended
after it. Alembic walks the chain from the recorded version forward, so on a
database that had already reached `9f8e7d6c5b4a` the new revision is treated as
history and never runs. `alembic upgrade head` reports nothing to do.

The role itself survives on such a database because the older, now-deleted
`f3a1b2c3d4e5_create_db_roles` created it, which is what makes the gap easy to
miss: `ledger_ro` exists and can connect, so the grants look present until
something actually reads a ledger table. What is missing is the privilege half —

    GRANT SELECT ON ALL TABLES IN SCHEMA ledger
    ALTER DEFAULT PRIVILEGES IN SCHEMA ledger GRANT SELECT ON TABLES

— so `ledger_ro` cannot read any table, and every table created afterwards
inherits no privilege either.

This revision is appended after the current head so it actually runs.

SCOPE
-----
Grants only. The role and its password are **not** touched: `b7e4c9a15d20` owns
that, and reproducing it here would mean handling the credential a second time
for no benefit. Consequently this revision needs no configured password and is
safe to run in any environment.

Every statement is idempotent — GRANT and ALTER DEFAULT PRIVILEGES both converge
— so on a database where `b7e4c9a15d20` did run normally, this is a no-op.

Revision ID: c9d0e1f2a3b4
Revises: audit_0002_sink_sync_reconcile
Create Date: 2026-08-20

"""
import re
from collections.abc import Sequence

from alembic import op

from app.platform.configuration.config import settings

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "audit_0002_sink_sync_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"

# A role name is an identifier, and identifiers cannot be bound parameters — it
# has to be interpolated. Anything outside this character class is rejected
# rather than escaped, which keeps the interpolation below trivially safe to
# read. Same rule as b7e4c9a15d20, deliberately.
_VALID_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _role_name() -> str:
    """The ledger read-only role, from settings, validated as a bare identifier."""
    role = settings.LEDGER_RO_DB_USER
    if not _VALID_ROLE_NAME.match(role or ""):
        raise RuntimeError(
            f"LEDGER_RO_DB_USER={role!r} is not a valid PostgreSQL identifier. "
            f"Expected lowercase letters, digits and underscores, not starting "
            f"with a digit (for example: ledger_ro)."
        )
    return role


def upgrade() -> None:
    role = _role_name()

    # Guarded on the role existing rather than assuming it. b7e4c9a15d20 is an
    # ancestor and creates it, but on the very databases this revision exists to
    # repair that ancestor never actually ran — so the guarantee it would
    # normally provide is exactly the one that cannot be relied on here. A
    # database with no ledger_ro role has nothing to grant to and is left alone;
    # re-running b7e4c9a15d20 is what creates it.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}'
            ) THEN
                RAISE NOTICE 'role {role} does not exist; skipping grants';
                RETURN;
            END IF;

            EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',
                           current_database(), '{role}');
            EXECUTE format('GRANT USAGE ON SCHEMA {SCHEMA} TO %I', '{role}');

            -- Tables that already exist. Default privileges are not
            -- retroactive, so this wildcard is what covers them.
            EXECUTE format(
                'GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO %I', '{role}');

            -- Tables that do not exist yet.
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} '
                'GRANT SELECT ON TABLES TO %I', '{role}');
        END
        $$;
        """
    )


def downgrade() -> None:
    """Deliberately a no-op.

    These grants are what `b7e4c9a15d20` declares; this revision only ensures
    they are actually present. Revoking them here would leave a normally-migrated
    database inconsistent with the revision that owns them. To remove them,
    downgrade past `b7e4c9a15d20`, whose own downgrade revokes and drops the role.
    """
