"""settlement_ro and audit_ro can read their own schema and nothing else.

The claim under test is not "the migration ran" but three properties a reviewer
cannot verify by reading SQL: each role can read a table that did not exist when
the migration ran, each role is refused every write, and neither role can see
into a schema other than its own. Only PostgreSQL can answer those, so every
test here runs against it.

WHERE THIS LIVES. `d4f2a9c7b118` provisions both roles in one revision, for one
consumer: the idempotency audit query interface. Splitting its assertions across
the settlement and audit modules would scatter one migration's proof over two
places that neither own it nor read it, so the suite sits with the capability
that does. `ledger_ro`'s equivalent stays with the ledger module because the
ledger module is its consumer.

GRANTOR SEMANTICS — why probe tables are created over DATABASE_SYNC_URL and not
by some other role. Default privileges live in pg_default_acl keyed by
(defaclrole, defaclnamespace): `ALTER DEFAULT PRIVILEGES IN SCHEMA x GRANT
SELECT ON TABLES TO y` is shorthand for `FOR ROLE current_user`, so it governs
only tables subsequently created by the role that ran the migration. Creating a
probe as a different role would produce a table with no inherited grant and a
failure having nothing to do with the migration. The grantor precondition below
asserts this connection IS the recorded grantor before anything else runs.
"""
from __future__ import annotations

import ast
import pathlib
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg2
import pytest
from psycopg2 import errors as pg_errors
from sqlalchemy.engine import make_url

from app.platform.configuration.config import Settings, get_settings

MIGRATION_REVISION = "d4f2a9c7b118"
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[4]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / f"{MIGRATION_REVISION}_settlement_ro_and_audit_ro_privileges.py"
)

INSUFFICIENT_PRIVILEGE = "42501"


@dataclass(frozen=True)
class RoleUnderTest:
    """One read-only role, the schema it may read, and the schemas it may not."""

    schema: str
    user_setting: str
    password_setting: str
    #: A table the module's baseline already owned, so it is covered by the
    #: one-time GRANT SELECT ON ALL TABLES rather than by the default privilege.
    #: The two halves of the migration are proved separately below.
    existing_table: str
    #: Schema-qualified tables the role must NOT reach. `ledger` appears for both
    #: because the audit query interface reads it under ledger_ro; if either role
    #: could reach it too, the one-role-per-module boundary would be decorative.
    forbidden: tuple[tuple[str, str], ...]


ROLES = (
    RoleUnderTest(
        schema="settlement",
        user_setting="SETTLEMENT_RO_DB_USER",
        password_setting="SETTLEMENT_RO_DB_PASSWORD",
        existing_table="settlement",
        forbidden=(("ledger", "idempotency_record"), ("audit", "audit_events")),
    ),
    RoleUnderTest(
        schema="audit",
        user_setting="AUDIT_RO_DB_USER",
        password_setting="AUDIT_RO_DB_PASSWORD",
        existing_table="audit_events",
        forbidden=(("ledger", "idempotency_record"), ("settlement", "settlement")),
    ),
)


def _owner_connect():
    """Connect as the role that ran the migration — the default-privilege grantor."""
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="module")
def owner_conn():
    conn = _owner_connect()
    yield conn
    conn.close()


@pytest.fixture(params=ROLES, ids=lambda r: r.schema)
def role(request) -> RoleUnderTest:
    """Each test below runs once per read-only role."""
    return request.param


@pytest.fixture
def ro_conn(role: RoleUnderTest):
    """A connection as the role under test, over the owner's host and database.

    autocommit, so every statement is its own transaction. Two reasons, both
    learned the hard way: a plain SELECT would otherwise leave an open
    transaction holding ACCESS SHARE on the probe table, and the DROP in that
    fixture's teardown — which needs ACCESS EXCLUSIVE — would block behind it
    until the suite timed out. And a refused statement would poison the
    transaction, so each following assertion would fail with InFailedSqlTransaction
    rather than the privilege error it is actually testing for.
    """
    settings = get_settings()
    url = make_url(settings.DATABASE_SYNC_URL).set(
        username=getattr(settings, role.user_setting),
        password=getattr(settings, role.password_setting),
    )
    conn = psycopg2.connect(
        url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg2://", "postgresql://"
        )
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def probe_table(role: RoleUnderTest, owner_conn) -> Iterator[str]:
    """A table created AFTER the migration, by the grantor, with no explicit GRANT.

    Whatever the read-only role can do with it, it can do because of ALTER
    DEFAULT PRIVILEGES and nothing else. The name is unique per run so a crashed
    previous run cannot collide with this one.
    """
    qualified = f"{role.schema}.probe_{uuid.uuid4().hex[:12]}"
    cur = owner_conn.cursor()
    cur.execute(f"CREATE TABLE {qualified} (id integer PRIMARY KEY, note text)")
    try:
        yield qualified
    finally:
        # A reader holding the table open would make this DROP wait for a lock
        # it can never get, turning a fixture leak into a hung suite. Fail in
        # three seconds with a lock error instead, which names the problem.
        cur.execute("SET lock_timeout = '3s'")
        try:
            cur.execute(f"DROP TABLE IF EXISTS {qualified}")
        finally:
            cur.execute("SET lock_timeout = DEFAULT")


# ── The grantor precondition ──────────────────────────────────────────────────


def test_default_privilege_grantor_is_the_connecting_role(owner_conn, role: RoleUnderTest) -> None:
    """Guards every probe-table test: this connection must be the recorded grantor.

    Pointed at a database with a different owner role, the probe tests would be
    measuring something other than what this migration configured. This fails
    first, and says so.
    """
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT pg_get_userbyid(d.defaclrole)
        FROM pg_default_acl d
        JOIN pg_namespace n ON n.oid = d.defaclnamespace
        WHERE n.nspname = %s AND d.defaclobjtype = 'r'
        """,
        (role.schema,),
    )
    grantors = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT current_user")
    current_user = cur.fetchone()[0]

    assert grantors, (
        f"no default privileges are recorded for schema {role.schema} at all — "
        f"migration {MIGRATION_REVISION} has not been applied to this database"
    )
    assert current_user in grantors, (
        f"this test connects as {current_user!r}, but the default privileges on "
        f"schema {role.schema} were granted by {sorted(grantors)!r}. Tables created "
        f"by {current_user!r} would not inherit them. Point DATABASE_SYNC_URL at the "
        f"role that runs migrations."
    )


# ── The roles exist and carry the privilege ───────────────────────────────────


def test_role_exists_and_can_log_in(owner_conn, role: RoleUnderTest) -> None:
    name = getattr(get_settings(), role.user_setting)
    cur = owner_conn.cursor()
    cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (name,))
    row = cur.fetchone()
    assert row is not None, f"the {name} role was not created by {MIGRATION_REVISION}"
    assert row[0] is True, f"{name} exists but cannot log in, so no consumer can use it"


def test_default_select_privilege_is_recorded(owner_conn, role: RoleUnderTest) -> None:
    """pg_default_acl carries a SELECT-on-tables entry for the role in its schema."""
    name = getattr(get_settings(), role.user_setting)
    cur = owner_conn.cursor()
    cur.execute(
        """
        SELECT unnest(d.defaclacl)::text
        FROM pg_default_acl d
        JOIN pg_namespace n ON n.oid = d.defaclnamespace
        WHERE n.nspname = %s AND d.defaclobjtype = 'r'
        """,
        (role.schema,),
    )
    entries = [r[0] for r in cur.fetchall()]
    granted = [e for e in entries if e.startswith(f"{name}=")]
    assert granted, (
        f"no default privilege recorded for {name} in schema {role.schema}; "
        f"found {entries!r}"
    )
    assert all("r" in e.split("=")[1].split("/")[0] for e in granted), (
        f"{name} has a default privilege in {role.schema} but it excludes SELECT: {granted!r}"
    )


# ── Reading works, on existing tables and on future ones ──────────────────────


def test_role_can_select_from_a_table_its_module_already_owned(
    ro_conn, role: RoleUnderTest
) -> None:
    """The one-time GRANT SELECT ON ALL TABLES half of the migration."""
    cur = ro_conn.cursor()
    cur.execute(f"SELECT 1 FROM {role.schema}.{role.existing_table} LIMIT 1")
    cur.fetchall()


def test_role_can_select_from_a_table_created_after_the_migration(
    ro_conn, probe_table: str
) -> None:
    """The ALTER DEFAULT PRIVILEGES half — nobody granted anything on this table."""
    cur = ro_conn.cursor()
    cur.execute(f"SELECT id, note FROM {probe_table}")
    assert cur.fetchall() == []


# ── Writing is refused, every verb ────────────────────────────────────────────


@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO {t} (id, note) VALUES (1, 'x')",
        "UPDATE {t} SET note = 'x'",
        "DELETE FROM {t}",
    ),
    ids=("insert", "update", "delete"),
)
def test_role_is_refused_every_write(ro_conn, probe_table: str, statement: str) -> None:
    """BUILD.md #10, at the layer that actually enforces it.

    A probe table rather than a live one: the assertion is about the privilege,
    and a refused write against a real financial table proves the same thing
    while risking a great deal more the day the privilege regresses.
    """
    cur = ro_conn.cursor()
    with pytest.raises(pg_errors.InsufficientPrivilege) as exc:
        cur.execute(statement.format(t=probe_table))
    assert exc.value.pgcode == INSUFFICIENT_PRIVILEGE


def test_role_cannot_create_a_table_in_its_own_schema(ro_conn, role: RoleUnderTest) -> None:
    """USAGE is not CREATE. A role that may read a schema must not extend it."""
    cur = ro_conn.cursor()
    with pytest.raises(pg_errors.InsufficientPrivilege) as exc:
        cur.execute(f"CREATE TABLE {role.schema}.should_not_exist (id integer)")
    assert exc.value.pgcode == INSUFFICIENT_PRIVILEGE


# ── Module isolation ──────────────────────────────────────────────────────────


def test_role_cannot_read_another_modules_schema(ro_conn, role: RoleUnderTest) -> None:
    """The point of one role per module: neither can see the other's tables.

    A role that could read every schema would make the split cosmetic — the
    interface would still hold three connections while any one of them could
    have answered every query.
    """
    cur = ro_conn.cursor()
    for other_schema, other_table in role.forbidden:
        with pytest.raises(pg_errors.InsufficientPrivilege) as exc:
            cur.execute(f"SELECT 1 FROM {other_schema}.{other_table} LIMIT 1")
        assert exc.value.pgcode == INSUFFICIENT_PRIVILEGE, (
            f"{role.schema}_ro reached {other_schema}.{other_table}"
        )


# ── The credential is not in the repository ───────────────────────────────────


def test_password_has_no_checked_in_default(role: RoleUnderTest) -> None:
    """A default is a shared, public credential for a role that can read a schema."""
    default = Settings.model_fields[role.password_setting].default
    assert default is None, (
        f"{role.password_setting} has a checked-in default ({default!r}). Every "
        f"environment that does not override it runs with the same password, and "
        f"that password is in the repository."
    )


@pytest.fixture(scope="module")
def migration_code() -> str:
    """The migration with its module docstring removed.

    Statements are executed, prose is not. The docstring names the settings the
    passwords come from, which is the explanation rather than a credential —
    scanning the raw file would flag it as one.
    """
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(source), clean=False)
    assert docstring, f"{MIGRATION_REVISION} lost its module docstring"
    return source.replace(docstring, "", 1)


def test_migration_reads_every_password_from_settings(migration_code: str) -> None:
    for role in ROLES:
        assert f'"{role.password_setting}"' in migration_code, (
            f"{MIGRATION_REVISION} no longer names {role.password_setting}; a password "
            f"must come from settings, never from a literal"
        )


def test_migration_passes_passwords_as_bound_parameters(migration_code: str) -> None:
    """The password reaches PostgreSQL through set_config(), never as SQL text."""
    assert "set_config" in migration_code, (
        f"{MIGRATION_REVISION} no longer routes its passwords through set_config(), so "
        f"they are being interpolated into SQL somewhere"
    )
    literal = re.search(r"(?i)password\s*=\s*[\"'][^\"'{}]+[\"']", migration_code)
    assert literal is None, (
        f"{MIGRATION_REVISION} appears to assign a literal password: {literal.group(0)!r}"
    )
