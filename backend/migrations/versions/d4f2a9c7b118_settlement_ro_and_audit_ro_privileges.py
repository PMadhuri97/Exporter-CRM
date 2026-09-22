"""settlement_ro and audit_ro roles with default SELECT privileges

Provisions the two read-only roles the idempotency audit query interface needs
in addition to `ledger_ro`, following `b7e4c9a15d20` — the reference
implementation BUILD.md #15 names — statement for statement.

WHY TWO ROLES AND NOT ONE
-------------------------
The audit interface reads three schemas: `ledger` (the registry, its archive and
the ledger transactions it cross-references), `settlement`, and `audit`. One
role holding USAGE on all three would let every query be a single join and would
be one credential whose blast radius is three modules. BUILD.md #15 permits a
module exactly one read-only role and forbids sharing a role between modules, so
the interface holds one connection per schema instead and composes the results
in the application. ADR 0003 records that trade-off.

Neither role is created pre-emptively. `b7e4c9a15d20` declined to provision
sibling roles on the principle that a module gets one when it has a real
read-only consumer; this interface is that consumer for both schemas, which is
what makes creating them here correct rather than speculative.

GRANTOR SEMANTICS
-----------------
`ALTER DEFAULT PRIVILEGES IN SCHEMA x GRANT SELECT ON TABLES TO y` is shorthand
for `FOR ROLE current_user`, recorded per grantor in pg_default_acl. It covers
only tables subsequently created by the role that ran this migration — `aner` in
every environment we operate, which also owns every schema and runs every
migration. A table created by some other role would inherit nothing, and this
revision would need a companion `FOR ROLE <that role>` entry.

Default privileges are not retroactive, so each schema also gets a one-time
`GRANT SELECT ON ALL TABLES` for the tables that already exist. Neither
statement is a table-by-table list: a list has to be edited whenever the module
gains a table and silently fails to cover any table added after it ran.

CREDENTIALS
-----------
Each password is read from settings (`SETTLEMENT_RO_DB_PASSWORD`,
`AUDIT_RO_DB_PASSWORD`) and handed to PostgreSQL through set_config() as a bound
parameter, so it is never interpolated into SQL this module constructs. A
missing password aborts with an actionable message rather than provisioning a
login role with a guessable credential.

Revision ID: d4f2a9c7b118
Revises: 5a3b7c9d1e2f
Create Date: 2026-08-28
"""
import re
from collections.abc import Sequence

from alembic import op

from app.platform.configuration.config import settings

# revision identifiers, used by Alembic.
revision: str = "d4f2a9c7b118"
down_revision: str | None = "5a3b7c9d1e2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A role name is an identifier, and identifiers cannot be bound parameters — it
# has to be interpolated. Anything outside this character class is rejected
# rather than escaped, which keeps the interpolation below trivially safe to read.
_VALID_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

# Transaction-local GUCs carrying each password as a bound parameter. Scoped to
# the current transaction by set_config(..., true), so they are gone the moment
# this migration commits or rolls back.
_ROLES = (
    ("settlement", "SETTLEMENT_RO_DB_USER", "SETTLEMENT_RO_DB_PASSWORD", "s4t3.settlement_ro_password"),
    ("audit", "AUDIT_RO_DB_USER", "AUDIT_RO_DB_PASSWORD", "s4t3.audit_ro_password"),
)


def _role_name(setting: str) -> str:
    """The role named by ``setting``, validated as a bare identifier."""
    role = getattr(settings, setting)
    if not _VALID_ROLE_NAME.match(role or ""):
        raise RuntimeError(
            f"{setting}={role!r} is not a valid PostgreSQL identifier. Expected "
            f"lowercase letters, digits and underscores, not starting with a "
            f"digit (for example: settlement_ro)."
        )
    return role


def _require_password(setting: str, role: str) -> str:
    """The role password, from settings. Never defaulted — see module docstring."""
    password = getattr(settings, setting)
    if not password:
        raise RuntimeError(
            f"{setting} is not set, so the {role} login role cannot be "
            f"provisioned. Export it in the environment, or add it to the "
            f"untracked backend/.env, before running 'alembic upgrade head'. It "
            f"is deliberately not defaulted: a checked-in default would be a "
            f"shared, public credential for a role that can read every table in "
            f"the schema."
        )
    return password


def upgrade() -> None:
    bind = op.get_bind()

    for schema, user_setting, password_setting, guc in _ROLES:
        role = _role_name(user_setting)

        # Bound parameter — the password is not interpolated into SQL text.
        bind.exec_driver_sql(
            f"SELECT set_config('{guc}', %s, true)",
            (_require_password(password_setting, role),),
        )

        # Idempotent: create the role, or bring an existing one's password in
        # line with configuration. Re-running against a database that already
        # has the role is a no-op apart from the password reset.
        op.execute(
            f"""
            DO $$
            DECLARE
                v_password text := current_setting('{guc}');
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

        # current_database() rather than a name parsed out of the connection
        # URL: the same migration then runs unchanged against aner_settlement, a
        # CI database, and a developer's local copy under any name.
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

        # USAGE on one schema and nothing else. This is what makes the role
        # module-isolated: it cannot see into any other module's schema, so the
        # blast radius of the credential is that module by construction.
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role};")

        # Tables that already exist — default privileges below are not
        # retroactive. A wildcard over the schema, not a table-by-table list.
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role};")

        # Tables that do not exist yet.
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {role};"
        )


def downgrade() -> None:
    # Everything is guarded on the role still existing: a downgrade run twice,
    # or against a database where the role was removed out of band, should be a
    # no-op rather than an error.
    #
    # This removes only what upgrade() granted, in reverse order. No table is
    # touched — REVOKE withdraws a privilege, it does not alter, empty or drop
    # the relation it names. DROP OWNED BY is deliberately NOT used: the role
    # owns nothing (it can only read), so it would clean up nothing here while
    # being the one statement in this file capable of destroying data if the
    # role were ever repurposed.
    for schema, user_setting, _password_setting, _guc in reversed(_ROLES):
        role = _role_name(user_setting)
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} '
                        'REVOKE SELECT ON TABLES FROM %I', '{role}');
                    EXECUTE format(
                        'REVOKE SELECT ON ALL TABLES IN SCHEMA {schema} FROM %I', '{role}');
                    EXECUTE format('REVOKE USAGE ON SCHEMA {schema} FROM %I', '{role}');
                    EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM %I',
                                   current_database(), '{role}');
                    EXECUTE format('DROP ROLE %I', '{role}');
                END IF;
            END
            $$;
            """
        )
