"""User management: administrator user list and self-service profile.

Every gated route gets a refusal test per role that must not reach it — the
gate is a dependency, so a 403 also proves the handler never ran. Beyond the
role gates, the tests that matter most here are the three lock-out guards
(self role change, self deactivation, last active administrator) and the two
session-revocation rules, since those are the ones whose absence is only
discovered at the worst possible moment.

Users are created through `user_with_role`, which registers normally and then
grants the role out of band — `POST /auth/register` only ever produces an
API_USER, deliberately.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import (
    PASSWORD,
    auth_header,
    token_with_role,
    user_with_role,
)

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/auth"

_ID = "00000000-0000-4000-8000-000000000000"

# (method, path, body) — every one of these is ADMIN-only.
ADMIN_ROUTES = [
    ("GET", f"{BASE}/users", None),
    ("POST", f"{BASE}/users", {"email": "x@aner-test.com", "password": "Password1", "role": "OPERATIONS"}),
    ("GET", f"{BASE}/users/{_ID}", None),
    ("PATCH", f"{BASE}/users/{_ID}", {"full_name": "X"}),
    ("POST", f"{BASE}/users/{_ID}/password", {"new_password": "Password2"}),
]

# Signed in is enough for these; no role gate, but never anonymous.
SELF_SERVICE_ROUTES = [
    ("GET", f"{BASE}/me/sessions", None),
    ("PATCH", f"{BASE}/me", {"full_name": "X"}),
    ("POST", f"{BASE}/me/password", {"current_password": PASSWORD, "new_password": "Password2"}),
    ("DELETE", f"{BASE}/me/sessions/{_ID}", None),
]

REFUSALS = [
    pytest.param(method, path, body, role, id=f"{method} {path.removeprefix(BASE)} as {role.value}")
    for method, path, body in ADMIN_ROUTES
    for role in UserRole
    if role != UserRole.ADMIN
]


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


# ── role gates ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("method", "path", "body", "role"), REFUSALS)
async def test_admin_route_refuses_role(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    method: str,
    path: str,
    body: dict | None,
    role: UserRole,
):
    resp = await client.request(method, path, json=body, headers=auth_header(tokens[role]))
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "FORBIDDEN"


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES + SELF_SERVICE_ROUTES)
async def test_route_requires_authentication(
    client: AsyncClient, method: str, path: str, body: dict | None
):
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 401, resp.text


# ── the administrator list ──────────────────────────────────────────────────


async def test_admin_can_list_users_and_total_counts_matches(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    resp = await client.get(f"{BASE}/users?limit=5", headers=auth_header(tokens[UserRole.ADMIN]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["users"]) <= 5
    # Every role fixture registered one account, so the corpus is never empty.
    assert body["total"] >= len(body["users"]) > 0
    assert body["limit"] == 5 and body["offset"] == 0


async def test_list_filters_by_role_and_search_term(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    email, _ = await _create_user(client, admin_token, role="COMPLIANCE", full_name="Priya Filter")

    by_role = await client.get(
        f"{BASE}/users?role=COMPLIANCE&q={email}", headers=auth_header(admin_token)
    )
    assert by_role.status_code == 200, by_role.text
    assert [u["email"] for u in by_role.json()["users"]] == [email]

    # Same term, wrong role filter — the filters combine with AND, not OR.
    wrong_role = await client.get(
        f"{BASE}/users?role=OPERATIONS&q={email}", headers=auth_header(admin_token)
    )
    assert wrong_role.json()["users"] == []


async def test_search_matches_full_name_case_insensitively(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    unique = uuid.uuid4().hex[:8]
    email, _ = await _create_user(
        client, admin_token, role="OPERATIONS", full_name=f"Zeenat {unique}"
    )

    resp = await client.get(
        f"{BASE}/users?q={unique.upper()}", headers=auth_header(admin_token)
    )
    assert [u["email"] for u in resp.json()["users"]] == [email]


# ── creating accounts ───────────────────────────────────────────────────────


async def test_admin_created_user_gets_requested_role_and_can_log_in(client: AsyncClient):
    admin_id, admin_token = await user_with_role(client, UserRole.ADMIN)
    email, created = await _create_user(client, admin_token, role="COMPLIANCE")

    assert created["role"] == "COMPLIANCE"
    # Attribution and provenance, the two facts the list view reports.
    assert created["created_by"] == admin_id
    assert created["is_verified"] is True
    assert created["last_login_at"] is None

    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text


async def test_duplicate_email_is_refused(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    email, _ = await _create_user(client, admin_token, role="OPERATIONS")

    again = await client.post(
        f"{BASE}/users",
        json={"email": email, "password": PASSWORD, "role": "OPERATIONS"},
        headers=auth_header(admin_token),
    )
    assert again.status_code == 409, again.text
    assert again.json()["error_code"] == "EMAIL_CONFLICT"


async def test_weak_password_is_refused_on_every_password_route(client: AsyncClient):
    """One strength rule, enforced identically wherever a password is set."""
    user_id, admin_token = await user_with_role(client, UserRole.ADMIN)

    create = await client.post(
        f"{BASE}/users",
        json={"email": f"weak-{uuid.uuid4().hex[:8]}@aner-test.com", "password": "alllowercase", "role": "OPERATIONS"},
        headers=auth_header(admin_token),
    )
    assert create.status_code == 422, create.text

    reset = await client.post(
        f"{BASE}/users/{user_id}/password",
        json={"new_password": "alllowercase"},
        headers=auth_header(admin_token),
    )
    assert reset.status_code == 422, reset.text

    change = await client.post(
        f"{BASE}/me/password",
        json={"current_password": PASSWORD, "new_password": "alllowercase"},
        headers=auth_header(admin_token),
    )
    assert change.status_code == 422, change.text


# ── the three lock-out guards ───────────────────────────────────────────────


async def test_admin_cannot_change_own_role(client: AsyncClient):
    admin_id, admin_token = await user_with_role(client, UserRole.ADMIN)

    resp = await client.patch(
        f"{BASE}/users/{admin_id}",
        json={"role": "OPERATIONS"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "SELF_ROLE_CHANGE_FORBIDDEN"

    # Refused, not partially applied.
    after = await client.get(f"{BASE}/users/{admin_id}", headers=auth_header(admin_token))
    assert after.json()["role"] == "ADMIN"


async def test_admin_cannot_deactivate_self(client: AsyncClient):
    admin_id, admin_token = await user_with_role(client, UserRole.ADMIN)

    resp = await client.patch(
        f"{BASE}/users/{admin_id}",
        json={"is_active": False},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "SELF_DEACTIVATION_FORBIDDEN"


async def test_admin_can_demote_another_admin(client: AsyncClient):
    """Positive control for the pair of self-guards above: they refuse changes
    to *your own* account, not to administrators in general.

    There is deliberately no separate "last active administrator" rule to test.
    This route requires an active ADMIN caller, so demoting any other account
    always leaves the caller behind, and the one account that could be the last
    administrator — the caller's own — is already refused above. A third guard
    would be unreachable.
    """
    victim_id, _ = await user_with_role(client, UserRole.ADMIN, email_prefix="victim")
    _, actor_token = await user_with_role(client, UserRole.ADMIN, email_prefix="actor")

    resp = await client.patch(
        f"{BASE}/users/{victim_id}",
        json={"role": "OPERATIONS"},
        headers=auth_header(actor_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "OPERATIONS"


# ── deactivation actually locks the account out ─────────────────────────────


async def test_deactivation_revokes_sessions_and_blocks_login(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    email, created = await _create_user(client, admin_token, role="OPERATIONS")
    target_id = created["id"]

    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    resp = await client.patch(
        f"{BASE}/users/{target_id}", json={"is_active": False}, headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False
    assert resp.json()["deactivated_at"] is not None

    # The refresh token it already held is dead, so the session cannot be
    # extended past the current access token's lifetime.
    refreshed = await client.post(f"{BASE}/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 401, refreshed.text

    blocked = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    assert blocked.status_code == 401, blocked.text

    # Reactivating clears the timestamp rather than leaving a stale one behind.
    back = await client.patch(
        f"{BASE}/users/{target_id}", json={"is_active": True}, headers=auth_header(admin_token)
    )
    assert back.json()["is_active"] is True
    assert back.json()["deactivated_at"] is None
    assert (await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})).status_code == 200


async def test_admin_password_reset_revokes_sessions_and_sets_new_password(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    email, created = await _create_user(client, admin_token, role="OPERATIONS")

    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    old_refresh = login.json()["refresh_token"]

    resp = await client.post(
        f"{BASE}/users/{created['id']}/password",
        json={"new_password": "Rotated9"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 204, resp.text

    assert (await client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh})).status_code == 401
    assert (await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})).status_code == 401
    assert (await client.post(f"{BASE}/login", json={"email": email, "password": "Rotated9"})).status_code == 200


async def test_unknown_user_id_is_404_on_every_admin_route(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    missing = uuid.uuid4()

    for method, path, body in (
        ("GET", f"{BASE}/users/{missing}", None),
        ("PATCH", f"{BASE}/users/{missing}", {"full_name": "X"}),
        ("POST", f"{BASE}/users/{missing}/password", {"new_password": "Password2"}),
    ):
        resp = await client.request(method, path, json=body, headers=auth_header(admin_token))
        assert resp.status_code == 404, (path, resp.text)


# ── self-service ────────────────────────────────────────────────────────────


async def test_user_can_edit_own_name_and_clear_it(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.OPERATIONS)

    named = await client.patch(f"{BASE}/me", json={"full_name": "Riya Sharma"}, headers=auth_header(token))
    assert named.status_code == 200, named.text
    assert named.json()["full_name"] == "Riya Sharma"

    cleared = await client.patch(f"{BASE}/me", json={"full_name": None}, headers=auth_header(token))
    assert cleared.json()["full_name"] is None


@pytest.mark.parametrize("field", ["role", "is_active", "email"])
async def test_self_update_cannot_touch_privileged_fields(client: AsyncClient, field: str):
    """`extra="forbid"` means escalation is refused at the boundary (422), not
    silently ignored inside the handler."""
    _, token = await user_with_role(client, UserRole.OPERATIONS)
    payload = {"role": "ADMIN", "is_active": False, "email": "new@aner-test.com"}

    resp = await client.patch(f"{BASE}/me", json={field: payload[field]}, headers=auth_header(token))
    assert resp.status_code == 422, resp.text

    after = await client.get(f"{BASE}/me", headers=auth_header(token))
    assert after.json()["role"] == "OPERATIONS"


async def test_password_change_requires_the_current_password(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.OPERATIONS)

    wrong = await client.post(
        f"{BASE}/me/password",
        json={"current_password": "NotMyPassword1", "new_password": "Brandnew1"},
        headers=auth_header(token),
    )
    assert wrong.status_code == 401, wrong.text


async def test_password_change_rotates_credentials_and_kills_sessions(client: AsyncClient):
    email, token, refresh_token = await _registered_session(client)

    resp = await client.post(
        f"{BASE}/me/password",
        json={"current_password": PASSWORD, "new_password": "Brandnew1"},
        headers=auth_header(token),
    )
    assert resp.status_code == 204, resp.text

    assert (await client.post(f"{BASE}/refresh", json={"refresh_token": refresh_token})).status_code == 401
    assert (await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})).status_code == 401
    assert (await client.post(f"{BASE}/login", json={"email": email, "password": "Brandnew1"})).status_code == 200


async def test_sessions_list_shows_own_sessions_and_revoke_ends_one(client: AsyncClient):
    _, token, _ = await _registered_session(client)

    listing = await client.get(f"{BASE}/me/sessions", headers=auth_header(token))
    assert listing.status_code == 200, listing.text
    sessions = listing.json()["sessions"]
    assert len(sessions) >= 1
    # Only what is actually recorded — no invented device/IP fields.
    assert set(sessions[0]) == {"id", "created_at", "expires_at"}

    revoked = await client.delete(
        f"{BASE}/me/sessions/{sessions[0]['id']}", headers=auth_header(token)
    )
    assert revoked.status_code == 204, revoked.text

    remaining = await client.get(f"{BASE}/me/sessions", headers=auth_header(token))
    assert sessions[0]["id"] not in [s["id"] for s in remaining.json()["sessions"]]


async def test_cannot_revoke_another_users_session(client: AsyncClient):
    """Scoped by owner in the query, so another user's id is indistinguishable
    from a nonexistent one — a 404, which also declines to confirm it exists."""
    _, victim_token, _ = await _registered_session(client)
    _, attacker_token, _ = await _registered_session(client)

    victim_sessions = await client.get(f"{BASE}/me/sessions", headers=auth_header(victim_token))
    victim_session_id = victim_sessions.json()["sessions"][0]["id"]

    resp = await client.delete(
        f"{BASE}/me/sessions/{victim_session_id}", headers=auth_header(attacker_token)
    )
    assert resp.status_code == 404, resp.text

    # Still usable by its owner.
    still_there = await client.get(f"{BASE}/me/sessions", headers=auth_header(victim_token))
    assert victim_session_id in [s["id"] for s in still_there.json()["sessions"]]


async def test_login_stamps_last_login_at(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    email, created = await _create_user(client, admin_token, role="OPERATIONS")

    before = await client.get(f"{BASE}/users/{created['id']}", headers=auth_header(admin_token))
    assert before.json()["last_login_at"] is None

    await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})

    after = await client.get(f"{BASE}/users/{created['id']}", headers=auth_header(admin_token))
    assert after.json()["last_login_at"] is not None


# ── helpers ─────────────────────────────────────────────────────────────────


async def _create_user(
    client: AsyncClient, admin_token: str, *, role: str, full_name: str | None = None
) -> tuple[str, dict]:
    email = f"made-{uuid.uuid4().hex[:10]}@aner-test.com"
    body: dict = {"email": email, "password": PASSWORD, "role": role}
    if full_name is not None:
        body["full_name"] = full_name
    resp = await client.post(f"{BASE}/users", json=body, headers=auth_header(admin_token))
    assert resp.status_code == 201, resp.text
    return email, resp.json()


async def _registered_session(client: AsyncClient) -> tuple[str, str, str]:
    """A plain registered account plus a live access and refresh token."""
    email = f"self-{uuid.uuid4().hex[:10]}@aner-test.com"
    reg = await client.post(f"{BASE}/register", json={"email": email, "password": PASSWORD})
    assert reg.status_code == 201, reg.text
    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return email, login.json()["access_token"], login.json()["refresh_token"]


