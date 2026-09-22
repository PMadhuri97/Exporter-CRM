"""settlement_ro_grants"""
import re
from collections.abc import Sequence

from alembic import op

from app.platform.configuration.config import settings

# revision identifiers, used by Alembic.
revision: str = '6201c6deb330'
down_revision: str | None = '5a3b7c9d1e2f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "settlement"
_VALID_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _role_name() -> str:
    role = settings.LEDGER_RO_DB_USER
    if not _VALID_ROLE_NAME.match(role or ""):
        raise RuntimeError(
            f"LEDGER_RO_DB_USER={role!r} is not a valid PostgreSQL identifier."
        )
    return role


def upgrade() -> None:
    role = _role_name()

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

            EXECUTE format('GRANT USAGE ON SCHEMA {SCHEMA} TO %I', '{role}');

            EXECUTE format(
                'GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO %I', '{role}');

            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} '
                'GRANT SELECT ON TABLES TO %I', '{role}');
        END
        $$;
        """
    )


def downgrade() -> None:
    role = _role_name()

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} '
                    'REVOKE SELECT ON TABLES FROM %I', '{role}');
                EXECUTE format(
                    'REVOKE SELECT ON ALL TABLES IN SCHEMA {SCHEMA} FROM %I', '{role}');
                EXECUTE format('REVOKE USAGE ON SCHEMA {SCHEMA} FROM %I', '{role}');
            END IF;
        END
        $$;
        """
    )
