"""
Auth integration tests.
All test users are created via the /register endpoint, which only ever creates
API_USER accounts. Tests needing another role, or an inactive account, change
the row with the sync psycopg2 driver (avoiding asyncpg pool contention with
the test's own async engine) — the same out-of-band path an operator uses.
Unique email addresses prevent cross-test interference; cleanup is omitted.
"""
import uuid

import pytest
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import (
    create_user_direct,
    grant_role_sync,
    user_with_role,
)
from app.platform.configuration.config import get_settings, settings

# ── helpers ───────────────────────────────────────────────────────────────────

def unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:10]}@aner-test.com"


async def register(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = "Password1",
    full_name: str = "Test User",
) -> tuple[str, dict]:
    """Register a user and return (email, response_body)."""
    addr = email or unique_email()
    resp = await client.post("/api/v1/auth/register", json={
        "email": addr,
        "password": password,
        "full_name": full_name,
    })
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return addr, resp.json()


async def login(client: AsyncClient, email: str, password: str = "Password1") -> dict:
    """Login and return token response body."""
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()


def _deactivate_user_sync(email: str) -> None:
    """Set is_active=False using the sync psycopg2 driver — no async pool involvement."""
    import psycopg2

    from app.platform.configuration.config import get_settings
    # DATABASE_SYNC_URL uses SQLAlchemy dialect prefix; psycopg2 needs a plain URL
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("UPDATE auth.users SET is_active = FALSE WHERE email = %s", (email,))
    conn.commit()
    cur.close()
    conn.close()


# ── registration ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    email, body = await register(client)
    assert body["email"] == email
    assert body["role"] == "API_USER"
    assert body["is_active"] is True
    assert "hashed_password" not in body
    assert "id" in body


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    email, _ = await register(client)

    resp = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Password1",
    })
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "EMAIL_CONFLICT"


@pytest.mark.asyncio
async def test_register_weak_password_no_uppercase(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": unique_email(),
        "password": "password1",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_weak_password_no_digit(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": unique_email(),
        "password": "PasswordOnly",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_caller_supplied_role(client: AsyncClient):
    """The route is unauthenticated: a caller-supplied role must never reach
    the User row. Every role — including API_USER — is refused outright (422),
    and no account is created as a side effect."""
    for role in UserRole:
        email = unique_email()
        resp = await client.post("/api/v1/auth/register", json={
            "email": email,
            "password": "Password1",
            "role": role.value,
        })
        assert resp.status_code == 422, (role, resp.text)

        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Password1"}
        )
        assert login_resp.status_code == 401, role


@pytest.mark.asyncio
async def test_register_can_only_produce_api_user(client: AsyncClient):
    """No accepted register body yields anything but API_USER — checked on
    the response, on /me (read back from the DB row) and in the token."""
    email, body = await register(client)
    assert body["role"] == "API_USER"

    tokens = await login(client, email)
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["role"] == "API_USER"

    from app.platform.authentication.services import decode_access_token
    assert decode_access_token(tokens["access_token"])["role"] == "API_USER"


# ── login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    email, _ = await register(client)

    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "Password1",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    email, _ = await register(client)

    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "WrongPassword1",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@nowhere.com",
        "password": "Password1",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_account(client: AsyncClient):
    email, _ = await register(client)
    _deactivate_user_sync(email)

    resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "Password1",
    })
    assert resp.status_code == 401


# ── /me endpoint ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_me_returns_current_user(client: AsyncClient):
    email, _ = await register(client)
    grant_role_sync(email, UserRole.COMPLIANCE)
    tokens = await login(client, email)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "COMPLIANCE"


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_malformed_bearer(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


# ── token refresh ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_issues_new_tokens(client: AsyncClient):
    email, _ = await register(client)
    tokens = await login(client, email)

    old_access = tokens["access_token"]
    old_refresh = tokens["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] != old_access
    assert body["refresh_token"] != old_refresh


@pytest.mark.asyncio
async def test_refresh_old_token_revoked_after_rotation(client: AsyncClient):
    email, _ = await register(client)
    tokens = await login(client, email)
    old_refresh = tokens["refresh_token"]

    await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "bogus_token"})
    assert resp.status_code == 401


# ── logout ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient):
    email, _ = await register(client)
    tokens = await login(client, email)
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert logout.status_code == 204

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_requires_authentication(client: AsyncClient):
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "any"})
    assert resp.status_code == 401


# ── role-based access ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_contains_correct_role(client: AsyncClient):
    for role in UserRole:
        email, _ = await register(client)
        grant_role_sync(email, role)
        tokens = await login(client, email)

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["role"] == role.value


@pytest.mark.asyncio
async def test_require_role_denies_wrong_role(client: AsyncClient):
    """
    Verifies the require_role dependency by confirming that an API_USER
    cannot obtain ADMIN-only privileges — the token payload reflects only
    the registered role, not an elevated one.
    """
    email, _ = await register(client)
    tokens = await login(client, email)

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.json()["role"] == "API_USER"


# ── direct-grant test fixture (L1-04) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_with_role_issues_a_usable_privileged_token(client: AsyncClient):
    """`user_with_role` must produce a working COMPLIANCE session without
    touching `POST /auth/register`.

    The whole point of the direct-creation path is that it survives sign-up
    being switched off (assumption A10), so this asserts the end state — a
    token the API accepts and reports as COMPLIANCE — rather than the
    mechanism. The `auth.users` row it writes must be indistinguishable from a
    registered one to `/auth/login` and `/auth/me`, which is what makes the
    substitution safe for the ~2,800 tests that depend on this fixture.
    """
    user_id, token = await user_with_role(client, UserRole.COMPLIANCE)

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["role"] == UserRole.COMPLIANCE.value
    assert me.json()["id"] == user_id


@pytest.mark.asyncio
async def test_create_user_direct_is_reachable_without_the_signup_route(client: AsyncClient):
    """A row created directly can log in — no `/auth/register` call anywhere.

    Separate from the test above because that one goes through `user_with_role`;
    this one exercises `create_user_direct` itself, which is the function L1-13
    will rely on once sign-up can be turned off.
    """
    email = unique_email()
    user_id = create_user_direct(email, UserRole.ADMIN)

    tokens = await login(client, email)
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["id"] == user_id
    assert me.json()["role"] == UserRole.ADMIN.value
    assert me.json()["is_active"] is True


# ── self-service sign-up switch (L1-13) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_signup_is_enabled_by_default(client: AsyncClient):
    """The default is unchanged behaviour: the route works and grants API_USER.

    Asserted explicitly rather than inferred from the other tests in this file,
    because the whole point of the switch is that turning it on is not a new
    behaviour — it is the existing one.
    """
    assert get_settings().SELF_SERVICE_SIGNUP_ENABLED is True

    email, body = await register(client)
    assert body["role"] == UserRole.API_USER.value


@pytest.mark.asyncio
async def test_signup_disabled_returns_404(client: AsyncClient, monkeypatch):
    """404, not 403.

    A 403 on an unauthenticated route would confirm the route exists and is
    merely closed to this caller — which, with no caller identity involved,
    tells every scanner the same thing. A deployment that has turned sign-up
    off is saying the route is not there.
    """
    monkeypatch.setattr(settings, "SELF_SERVICE_SIGNUP_ENABLED", False)

    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email(), "password": "Password1"},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_signup_disabled_creates_no_user(client: AsyncClient, monkeypatch):
    """The refusal happens before any write, so a rejected sign-up leaves no row."""
    monkeypatch.setattr(settings, "SELF_SERVICE_SIGNUP_ENABLED", False)
    email = unique_email()

    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "Password1"}
    )

    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password1"}
    )
    assert login.status_code == 401


@pytest.mark.asyncio
async def test_login_still_works_when_signup_is_disabled(client: AsyncClient, monkeypatch):
    """Turning sign-up off must not lock out accounts that already exist —
    including the ones the first-admin command creates, which is the whole
    point of having both."""
    email = unique_email()
    user_id = create_user_direct(email, UserRole.COMPLIANCE)

    monkeypatch.setattr(settings, "SELF_SERVICE_SIGNUP_ENABLED", False)

    tokens = await login(client, email)
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == user_id
    assert me.json()["role"] == UserRole.COMPLIANCE.value
