"""Test support: authenticated users with a given role.

Imported only by test suites. `POST /auth/register` always creates an
`API_USER` (a caller-supplied role on an unauthenticated route would be a
privilege escalation), so a test needing any other role registers normally and
then grants the role directly in the database — the same out-of-band path an
operator uses. `get_current_active_user` reads the role from the `auth.users`
row on every request, so the grant applies immediately.

Lives in `platform` so every module's tests can share it without importing
another module's internals (see importlinter.ini).
"""

from __future__ import annotations

import uuid

import psycopg2
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

PASSWORD = "Password1"


def grant_role_sync(email: str, role: UserRole) -> None:
    """Set `role` on an existing user via the sync driver — no async pool involvement."""
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE auth.users SET role = %s WHERE email = %s", (role.value, email))
            assert cur.rowcount == 1, f"no user {email} to grant {role.value}"
        conn.commit()
    finally:
        conn.close()


async def user_with_role(
    client: AsyncClient, role: UserRole, *, email_prefix: str | None = None
) -> tuple[str, str]:
    """Register a user, grant it `role`, log in. Returns (user_id, access_token)."""
    prefix = email_prefix or role.value.lower()
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@aner-test.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert reg.status_code == 201, reg.text
    if role != UserRole.API_USER:
        grant_role_sync(email, role)
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return reg.json()["id"], login.json()["access_token"]


async def token_with_role(client: AsyncClient, role: UserRole) -> str:
    _, token = await user_with_role(client, role)
    return token


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
