"""Test support: authenticated users with a given role.

Imported only by test suites. A test needing a privileged account creates the
`auth.users` row directly (`create_user_direct`) and then logs in normally, so
the fixture depends on `POST /auth/login` alone.

**Why not `POST /auth/register`.** That route always creates an `API_USER` (a
caller-supplied role on an unauthenticated route would be a privilege
escalation), so the fixture used to register and then grant the role in a
second step. That made every privileged test in the suite depend on
self-service sign-up being reachable — and sign-up is due to become switchable
(planning assumption A10). A suite that cannot get a `COMPLIANCE` token once
sign-up is off is a suite that cannot test the thing sign-up was turned off to
protect. Creating the row directly is the same out-of-band path an operator
uses and has no such dependency.

`grant_role_sync` is kept: promoting an *existing* user is a real operation
(assumption A12) and a test may need to exercise it. `user_with_role` no
longer uses it.

Lives in `platform` so every module's tests can share it without importing
another module's internals (see importlinter.ini).
"""

from __future__ import annotations

import uuid

import psycopg2
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.services import hash_password
from app.platform.configuration.config import get_settings

PASSWORD = "Password1"


def _sync_dsn() -> str:
    return get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")


def grant_role_sync(email: str, role: UserRole) -> None:
    """Set `role` on an existing user via the sync driver — no async pool involvement."""
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE auth.users SET role = %s WHERE email = %s", (role.value, email))
            assert cur.rowcount == 1, f"no user {email} to grant {role.value}"
        conn.commit()
    finally:
        conn.close()


def create_user_direct(
    email: str, role: UserRole, *, password: str = PASSWORD, full_name: str | None = None
) -> str:
    """Insert an active `auth.users` row at `role`. Returns the new user's id.

    Uses the sync driver for the same reason `grant_role_sync` does: the test
    session's async engine is swapped for a NullPool one in `conftest.py`, and
    a fixture that borrowed from it would be reaching into the machinery under
    test. The password goes through the application's own `hash_password`, so
    `POST /auth/login` verifies it exactly as it would any other account — the
    row this writes is indistinguishable from a registered one apart from its
    role.

    `id`, `created_at` and `updated_at` have database defaults, but `id` is
    generated here instead so the caller gets it back without a second query.
    """
    user_id = uuid.uuid4()
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth.users (id, email, hashed_password, full_name, role, is_active) "
                "VALUES (%s, %s, %s, %s, %s, TRUE)",
                (str(user_id), email, hash_password(password), full_name, role.value),
            )
        conn.commit()
    finally:
        conn.close()
    return str(user_id)


async def user_with_role(
    client: AsyncClient, role: UserRole, *, email_prefix: str | None = None
) -> tuple[str, str]:
    """Create a user at `role` and log it in. Returns (user_id, access_token)."""
    prefix = email_prefix or role.value.lower()
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@aner-test.com"
    user_id = create_user_direct(email, role)
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return user_id, login.json()["access_token"]


async def token_with_role(client: AsyncClient, role: UserRole) -> str:
    _, token = await user_with_role(client, role)
    return token


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
