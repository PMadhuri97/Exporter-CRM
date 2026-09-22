"""ledger_ro role and default SELECT privileges on schema ledger

Supersedes f3a1b2c3d4e5 (AL-53), which provisioned the same role with a
table-by-table grant list:

    GRANT SELECT ON ledger.ledger_account, ledger.ledger_entry,
                    ledger.ledger_transaction, ledger.account_balance TO ledger_ro;

That list had to be edited every time the ledger module gained a table, and it
silently failed to cover any table added after it ran — a read-only consumer
would get "permission denied" for a table it was entitled to read, at runtime,
with nothing in the migration history to point at. This revision replaces the
list with the statement the ticket specifies:

    ALTER DEFAULT PRIVILEGES IN SCHEMA ledger
    GRANT SELECT ON TABLES TO ledger_ro

so every FUTURE table created in the ledger schema grants SELECT to ledger_ro
automatically, with no migration required.

GRANTOR SEMANTICS — the part that surprises people. Default privileges are
recorded per *grantor*, in pg_default_acl, keyed by (defaclrole, defaclnamespace).
The statement above is shorthand for `ALTER DEFAULT PRIVILEGES FOR ROLE
current_user ...`, so it only affects tables subsequently created BY THE ROLE
THAT RAN THIS MIGRATION (`aner` in every environment we operate). That is
exactly right here — `aner` owns the schema and every migration that will ever
add a ledger table runs as `aner` — but it means a table created by some other
role would NOT inherit the grant. If ledger DDL ever moves to a second role,
this revision needs a companion `FOR ROLE <that role>` entry. The integration
test creates its probe table as the same grantor for this reason; creating it as
anyone else would prove nothing.

Default privileges are also NOT retroactive: they say nothing about tables that
already exist. The four baseline tables are therefore covered by a one-time
`GRANT SELECT ON ALL TABLES IN SCHEMA ledger` — a wildcard over the schema, not
a table-by-table list, so it needs no maintenance either.

The password is never written down. It is read from settings
(LEDGER_RO_DB_PASSWORD -> environment or the untracked backend/.env) and handed
to PostgreSQL through set_config() as a bound parameter, so it is not
interpolated into any SQL string this file constructs and there is no quote
escaping to get wrong. A missing password aborts the migration with an
actionable message rather than provisioning a login role with a guessable
credential.

Scope: ledger_ro only. No other module role is created here — a module gets a
read-only role when it has a real read-only consumer, not pre-emptively.

Revision ID: b7e4c9a15d20
Revises: settlement_0001_baseline
Create Date: 2026-08-11
"""
import re
from collections.abc import Sequence

from alembic import op

from app.platform.configuration.config import settings

# revision identifiers, used by Alembic.
revision: str = "b7e4c9a15d20"
down_revision: str | None = "settlement_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"

# The password travels as a bound parameter into this transaction-local GUC, so
# it never appears in a SQL string assembled by this module. set_config(..., true)
# scopes it to the current transaction; it is gone the moment the migration
# commits or rolls back.
PASSWORD_GUC = "s10t2.ledger_ro_password"

# A role name is an identifier, and identifiers cannot be bound parameters — it
# has to be interpolated. Anything outside this character class is rejected
# rather than escaped, which keeps the interpolation below trivially safe to read.
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


def _require_password() -> str:
    """The role password, from settings. Never defaulted — see module docstring."""
    password = settings.LEDGER_RO_DB_PASSWORD
    if not password:
        raise RuntimeError(
            "LEDGER_RO_DB_PASSWORD is not set, so the ledger_ro login role cannot "
            "be provisioned. Export it in the environment, or add it to the "
            "untracked backend/.env, before running 'alembic upgrade head'. It is "
            "deliberately not defaulted: a checked-in default would be a shared, "
            "public credential for a role that can read the entire ledger."
        )
    return password


def upgrade() -> None:
    role = _role_name()
    bind = op.get_bind()

    # Bound parameter — the password is not interpolated into SQL text.
    bind.exec_driver_sql(
        f"SELECT set_config('{PASSWORD_GUC}', %s, true)", (_require_password(),)
    )

    # Idempotent: create the role, or bring an existing one's password in line
    # with configuration. Re-running this migration against a database that
    # already has the role is a no-op apart from the password reset.
    op.execute(
        f"""
        DO $$
        DECLARE
            v_password text := current_setting('{PASSWORD_GUC}');
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}'
            ) THEN
                EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L',
                               '{role}', v_password);
            ELSE
                EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L',
                               '{role}', v_password);
            END IF;
        END
        $$;
        """
    )

    # current_database() rather than a name parsed out of the connection URL:
    # the same migration then runs unchanged against aner_settlement, a CI
    # database, and a developer's local copy under any name.
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',
                           current_database(), '{role}');
        END
        $$;
        """
    )

    # USAGE on ledger and nothing else. This is what makes the role
    # module-isolated: it cannot see into any other module's schema, so the
    # blast radius of the credential is the ledger module by construction.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role};")

    # Tables that already exist. Default privileges below are not retroactive,
    # so this one-time wildcard covers the baseline tables. Not a table-by-table
    # list — it needs no edit when a table is added.
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {role};")

    # Tables that do not exist yet. Kept as a single unbroken statement so it
    # greps as the thing it is; with SCHEMA="ledger" and role="ledger_ro" it
    # renders to exactly:
    #     ALTER DEFAULT PRIVILEGES IN SCHEMA ledger GRANT SELECT ON TABLES TO ledger_ro
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT ON TABLES TO {role};")


def downgrade() -> None:
    role = _role_name()

    # Everything is guarded on the role still existing: a downgrade run twice,
    # or against a database where the role was removed out of band, should be a
    # no-op rather than an error.
    #
    # This removes only what upgrade() granted, in reverse order. No ledger
    # table is touched — REVOKE withdraws a privilege, it does not alter, empty
    # or drop the relation it names. DROP OWNED BY is deliberately NOT used: the
    # role owns nothing (it can only read), so it would clean up nothing here
    # while being the one statement in this file capable of destroying data if
    # the role were ever repurposed.
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
                EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM %I',
                               current_database(), '{role}');
                EXECUTE format('DROP ROLE %I', '{role}');
            END IF;
        END
        $$;
        """
    )
