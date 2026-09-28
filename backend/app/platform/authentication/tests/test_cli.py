"""First-admin command (L1-09).

The command exists so that granting a privileged role is a reviewed, tested
operation instead of a hand-written `UPDATE auth.users`. These tests therefore
assert the two properties an operator actually relies on — that a second run
changes nothing, and that a blank password stops the run rather than producing
an account nobody chose the password for — plus the end-to-end fact that the
row it writes can log in and is reported at the right role.

`get_settings` is `lru_cache`d and `config.settings` is bound at import, so the
credentials are injected by patching `cli.get_settings` rather than the
environment: patching `os.environ` after import would be read by nothing.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import psycopg2
import pytest
from httpx import AsyncClient

from app.platform.authentication import cli
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

pytestmark = pytest.mark.asyncio

PASSWORD = "Bootstrap1"


def _dsn() -> str:
    return get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")


def _row(email: str):
    """(id, role, hashed_password, created_at, updated_at) for one user, or None."""
    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, role, hashed_password, created_at, updated_at "
                "FROM auth.users WHERE email = %s",
                (email,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def _count(email: str) -> int:
    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM auth.users WHERE email = %s", (email,))
            return cur.fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def credentials(monkeypatch) -> SimpleNamespace:
    """Unique bootstrap credentials, injected into the command.

    Fresh addresses per test so the suite can run repeatedly against the same
    database without the second run seeing the first run's accounts — the
    command is idempotent, which would otherwise mask a broken create path.
    """
    suffix = uuid.uuid4().hex[:10]
    creds = SimpleNamespace(
        DATABASE_SYNC_URL=get_settings().DATABASE_SYNC_URL,
        FIRST_ADMIN_EMAIL=f"boot-admin-{suffix}@aner-test.com",
        FIRST_ADMIN_PASSWORD=PASSWORD,
        FIRST_COMPLIANCE_EMAIL=f"boot-compliance-{suffix}@aner-test.com",
        FIRST_COMPLIANCE_PASSWORD=PASSWORD,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: creds)
    return creds


# ── bootstrap ─────────────────────────────────────────────────────────────────


async def test_first_run_creates_both_accounts(client: AsyncClient, credentials):
    """The admin and the compliance user exist afterwards, at the right roles,
    and both can actually log in — a row with an unusable password hash would
    satisfy a database-only assertion while helping nobody."""
    assert cli.bootstrap() == 0

    admin = _row(credentials.FIRST_ADMIN_EMAIL)
    compliance = _row(credentials.FIRST_COMPLIANCE_EMAIL)
    assert admin is not None and admin[1] == UserRole.ADMIN.value
    assert compliance is not None and compliance[1] == UserRole.COMPLIANCE.value

    for email, role in (
        (credentials.FIRST_ADMIN_EMAIL, UserRole.ADMIN),
        (credentials.FIRST_COMPLIANCE_EMAIL, UserRole.COMPLIANCE),
    ):
        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["role"] == role.value


async def test_second_identical_run_changes_nothing(client: AsyncClient, credentials):
    """Idempotence, asserted on the row rather than on the exit code.

    A command that re-hashed the password or re-issued the id every run would
    still exit 0 and still leave one account, so the check is that the stored
    hash, the id and `updated_at` are byte-for-byte what the first run wrote.
    `updated_at` matters most: a routine re-run that touches it makes the audit
    trail lie about when the account last changed.
    """
    assert cli.bootstrap() == 0
    before = (
        _row(credentials.FIRST_ADMIN_EMAIL),
        _row(credentials.FIRST_COMPLIANCE_EMAIL),
    )

    assert cli.bootstrap() == 0
    after = (
        _row(credentials.FIRST_ADMIN_EMAIL),
        _row(credentials.FIRST_COMPLIANCE_EMAIL),
    )

    assert after == before
    assert _count(credentials.FIRST_ADMIN_EMAIL) == 1
    assert _count(credentials.FIRST_COMPLIANCE_EMAIL) == 1


async def test_an_existing_account_is_not_re_elevated(client: AsyncClient, credentials):
    """A demotion made on purpose survives a re-run.

    `bootstrap` creates; it does not repair. If someone has deliberately moved
    the bootstrap admin down to OPERATIONS, a later routine run must not put it
    back — that is what `promote` is for, and it says so in its name.
    """
    assert cli.bootstrap() == 0
    cli.promote(credentials.FIRST_ADMIN_EMAIL, "OPERATIONS")

    assert cli.bootstrap() == 0

    assert _row(credentials.FIRST_ADMIN_EMAIL)[1] == UserRole.OPERATIONS.value


async def test_the_same_address_for_both_roles_is_refused(client: AsyncClient, credentials):
    """One account cannot hold both roles, and a copy-paste in `.env` is the
    likely way to ask for it."""
    credentials.FIRST_COMPLIANCE_EMAIL = credentials.FIRST_ADMIN_EMAIL

    with pytest.raises(cli.BootstrapError, match="same address"):
        cli.bootstrap()

    assert _count(credentials.FIRST_ADMIN_EMAIL) == 0


# ── blank credentials ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("FIRST_ADMIN_PASSWORD", "FIRST_ADMIN_PASSWORD is blank"),
        ("FIRST_COMPLIANCE_PASSWORD", "FIRST_COMPLIANCE_PASSWORD is blank"),
    ],
)
async def test_a_blank_password_fails_explicitly(
    client: AsyncClient, credentials, field: str, expected: str
):
    """Named in the message, and nothing written.

    The failure mode this guards against is a command that "helpfully" invents
    or defaults a password, leaving a privileged account whose credentials
    nobody chose and nobody knows.
    """
    setattr(credentials, field, "")

    with pytest.raises(cli.BootstrapError, match=expected):
        cli.bootstrap()

    assert _count(credentials.FIRST_ADMIN_EMAIL) == 0
    assert _count(credentials.FIRST_COMPLIANCE_EMAIL) == 0


async def test_a_blank_email_fails_explicitly(client: AsyncClient, credentials):
    credentials.FIRST_ADMIN_EMAIL = "   "

    with pytest.raises(cli.BootstrapError, match="FIRST_ADMIN_EMAIL is not set"):
        cli.bootstrap()


async def test_main_turns_a_refusal_into_a_nonzero_exit(
    client: AsyncClient, credentials, capsys
):
    """The refusal reaches a shell as an exit code and a message on stderr, not
    a traceback — this is what a deploy script branches on."""
    credentials.FIRST_ADMIN_PASSWORD = ""

    assert cli.main(["bootstrap"]) == cli.EXIT_INVALID
    assert "FIRST_ADMIN_PASSWORD is blank" in capsys.readouterr().err


# ── promote ───────────────────────────────────────────────────────────────────


async def test_promote_changes_an_existing_users_role(client: AsyncClient, credentials):
    assert cli.bootstrap() == 0
    email = credentials.FIRST_COMPLIANCE_EMAIL

    assert cli.promote(email, "ADMIN") == 0
    assert _row(email)[1] == UserRole.ADMIN.value

    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.json()["role"] == UserRole.ADMIN.value


async def test_promote_accepts_a_lowercase_role(client: AsyncClient, credentials):
    assert cli.bootstrap() == 0
    assert cli.promote(credentials.FIRST_COMPLIANCE_EMAIL, "operations") == 0
    assert _row(credentials.FIRST_COMPLIANCE_EMAIL)[1] == UserRole.OPERATIONS.value


async def test_promote_to_the_same_role_is_a_no_op(client: AsyncClient, credentials):
    """No write at all, so `updated_at` does not move for a command that
    changed nothing."""
    assert cli.bootstrap() == 0
    before = _row(credentials.FIRST_ADMIN_EMAIL)

    assert cli.promote(credentials.FIRST_ADMIN_EMAIL, "ADMIN") == 0

    assert _row(credentials.FIRST_ADMIN_EMAIL) == before


async def test_promote_refuses_an_unknown_user(client: AsyncClient, credentials):
    """It must not create one: a typo would otherwise mint a second ADMIN."""
    missing = f"nobody-{uuid.uuid4().hex[:8]}@aner-test.com"

    with pytest.raises(cli.BootstrapError, match="does not create one"):
        cli.promote(missing, "ADMIN")

    assert _count(missing) == 0


async def test_promote_refuses_an_unknown_role(client: AsyncClient, credentials):
    assert cli.bootstrap() == 0

    with pytest.raises(cli.BootstrapError, match="Unknown role"):
        cli.promote(credentials.FIRST_ADMIN_EMAIL, "SUPERUSER")

    assert _row(credentials.FIRST_ADMIN_EMAIL)[1] == UserRole.ADMIN.value
