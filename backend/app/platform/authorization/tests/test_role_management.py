"""Role management: roles as editable data, permissions as the gate.

The tests that matter most here are the ones about *not* changing behaviour.
Moving user management from `require_role(ADMIN)` to `require_permission` is
only safe if the seeded built-in roles reproduce section 3.7 of the architecture
plan exactly, so the first group asserts that seed directly, and the refusal
tests from user management keep passing untouched.

The second group covers the two lockouts that are genuinely reachable now that
"who may do this" is editable: stripping role management from your own role, and
removing the last account that holds it.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import (
    PASSWORD,
    auth_header,
    token_with_role,
    user_with_role,
)
from app.platform.configuration.config import get_settings

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/auth"
ROLES = f"{BASE}/roles"

# Transcribed from section 3.7, independently of catalog.py: a test that imports
# the value it verifies would pass no matter what that value became.
EXPECTED_BUILTIN_PERMISSIONS = {
    "COMPLIANCE": {
        ("exporters", "view"),
        ("exporters", "create"),
        ("exporters", "edit"),
        ("exporters", "transition"),
        ("exporters", "view_full_tax_id"),
        ("exporters", "search_by_tax_id"),
        ("verifications", "view"),
        ("verifications", "create"),
        ("verifications", "review"),
        ("screening", "view"),
        ("screening", "decide"),
        ("audit", "view"),
    },
    "OPERATIONS": {
        ("exporters", "view"),
        ("exporters", "create"),
        ("exporters", "edit"),
        ("exporters", "transition"),
        ("exporters", "search_by_tax_id"),
        ("verifications", "view"),
        ("verifications", "create"),
        ("screening", "view"),
    },
    "DEVELOPER": {
        ("exporters", "view"),
        ("verifications", "view"),
        ("screening", "view"),
    },
    "API_USER": set(),
}


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


def _pairs(role_body: dict) -> set[tuple[str, str]]:
    return {(p["module"], p["action"]) for p in role_body["permissions"]}


async def _roles_by_slug(client: AsyncClient, admin_token: str) -> dict[str, dict]:
    resp = await client.get(ROLES, headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    return {role["slug"]: role for role in resp.json()["roles"]}


# ── the seed reproduces section 3.7 ─────────────────────────────────────────


async def test_five_builtin_roles_exist_and_cannot_be_deleted(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    roles = await _roles_by_slug(client, tokens[UserRole.ADMIN])
    assert set(roles) >= {"admin", "compliance", "operations", "developer", "api-user"}

    for slug in ("admin", "compliance", "operations", "developer", "api-user"):
        assert roles[slug]["is_builtin"] is True
        resp = await client.delete(
            f"{ROLES}/{roles[slug]['id']}", headers=auth_header(tokens[UserRole.ADMIN])
        )
        assert resp.status_code == 409, (slug, resp.text)
        assert resp.json()["error_code"] == "BUILTIN_ROLE_PROTECTED"


@pytest.mark.parametrize("slug", ["compliance", "operations", "developer", "api-user"])
async def test_builtin_role_permissions_match_the_plan(
    client: AsyncClient, tokens: dict[UserRole, str], slug: str
):
    roles = await _roles_by_slug(client, tokens[UserRole.ADMIN])
    role = roles[slug]
    expected = EXPECTED_BUILTIN_PERMISSIONS[role["builtin_role"]]
    assert _pairs(role) == expected


async def test_admin_holds_every_permission_in_the_catalogue(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    catalog = await client.get(f"{ROLES}/catalog", headers=auth_header(tokens[UserRole.ADMIN]))
    assert catalog.status_code == 200, catalog.text
    every_pair = {
        (module["key"], action["key"])
        for module in catalog.json()["modules"]
        for action in module["actions"]
    }

    roles = await _roles_by_slug(client, tokens[UserRole.ADMIN])
    assert _pairs(roles["admin"]) == every_pair


async def test_catalogue_admits_which_modules_are_not_enforced_yet(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """The honesty requirement: only users and roles actually gate anything, and
    the catalogue has to say so rather than implying every checkbox works."""
    catalog = await client.get(f"{ROLES}/catalog", headers=auth_header(tokens[UserRole.ADMIN]))
    enforced = {m["key"] for m in catalog.json()["modules"] if m["enforced"]}
    assert enforced == {"users", "roles"}


async def test_operations_does_not_get_blanket_tax_id_reveal(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """A flat grant cannot express "only records I own", so OPERATIONS must not
    be seeded with view_full_tax_id — that would widen today's owner-scoped
    reveal to every company."""
    roles = await _roles_by_slug(client, tokens[UserRole.ADMIN])
    assert ("exporters", "view_full_tax_id") not in _pairs(roles["operations"])
    assert ("exporters", "search_by_tax_id") in _pairs(roles["operations"])


# ── permissions gate the routes, and nothing else changed ───────────────────


@pytest.mark.parametrize(
    "role", [UserRole.COMPLIANCE, UserRole.OPERATIONS, UserRole.DEVELOPER, UserRole.API_USER]
)
async def test_role_routes_refuse_everyone_but_admin_by_default(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole
):
    for method, path, body in (
        ("GET", ROLES, None),
        ("GET", f"{ROLES}/catalog", None),
        ("POST", ROLES, {"slug": "nope", "name": "Nope"}),
    ):
        resp = await client.request(method, path, json=body, headers=auth_header(tokens[role]))
        assert resp.status_code == 403, (path, role, resp.text)
        assert resp.json()["error_code"] == "FORBIDDEN"


async def test_my_permissions_needs_no_permission_of_its_own(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """Every caller may ask what they themselves can do — that is what a client
    branches on instead of comparing role names."""
    for role in UserRole:
        resp = await client.get(f"{BASE}/me/permissions", headers=auth_header(tokens[role]))
        assert resp.status_code == 200, (role, resp.text)
        body = resp.json()
        assert body["role"] == role.value
        pairs = {(p["module"], p["action"]) for p in body["permissions"]}
        if role is UserRole.ADMIN:
            assert ("users", "view") in pairs
        else:
            assert ("users", "view") not in pairs


async def test_the_operations_role_reads_rm_everywhere_it_is_named(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """`auth_0005_rm_role_name`: the built-in row is what the
    Roles tab, the user form and "Signed in as …" show, so the rename has to reach
    it. An account with no `role_id` is named by that same built-in row — the one
    its permissions come from — not by the enum title-cased into "Operations"."""
    roles = await _roles_by_slug(client, tokens[UserRole.ADMIN])
    assert roles["operations"]["name"] == "RM (Relationship Manager)"
    assert "unless you own" not in (roles["operations"]["description"] or "")

    mine = await client.get(
        f"{BASE}/me/permissions", headers=auth_header(tokens[UserRole.OPERATIONS])
    )
    assert mine.json()["role_id"] is None
    assert mine.json()["role_name"] == "RM (Relationship Manager)"


async def test_granting_users_view_opens_the_user_list_without_a_code_change(
    client: AsyncClient,
):
    """The point of the whole feature: what used to need a code change ("let
    COMPLIANCE see the Users tab") becomes a permission grant.

    Deliberately does NOT edit the shared `compliance` built-in role. Every test
    in this session resolves its permissions through those five rows, so mutating
    one — even with a restore afterwards — makes this suite order-dependent, and
    a failure before the restore leaves the database wrong for everything that
    follows. Granting through a custom role assigned to a COMPLIANCE account
    proves the same thing against state this test owns.
    """
    _, admin_token = await user_with_role(client, UserRole.ADMIN)

    # A plain COMPLIANCE account: refused, as the built-in role has no users:*.
    _, plain_token = await user_with_role(client, UserRole.COMPLIANCE)
    assert (
        await client.get(f"{BASE}/users", headers=auth_header(plain_token))
    ).status_code == 403

    # The same role's permissions plus users:view, as a role of this test's own.
    granted_role = await client.post(
        ROLES,
        json={
            "slug": f"compliance-plus-{uuid.uuid4().hex[:8]}",
            "name": "Compliance + user list",
            "permissions": [
                {"module": "exporters", "action": "view"},
                {"module": "screening", "action": "decide"},
                {"module": "users", "action": "view"},
            ],
        },
        headers=auth_header(admin_token),
    )
    assert granted_role.status_code == 201, granted_role.text

    email = f"compliance-plus-{uuid.uuid4().hex[:8]}@aner-test.com"
    made = await client.post(
        f"{BASE}/users",
        json={
            "email": email,
            "password": PASSWORD,
            "role": "COMPLIANCE",
            "role_id": granted_role.json()["id"],
        },
        headers=auth_header(admin_token),
    )
    assert made.status_code == 201, made.text
    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    granted_token = login.json()["access_token"]

    listing = await client.get(f"{BASE}/users", headers=auth_header(granted_token))
    assert listing.status_code == 200, listing.text

    # One grant, not a bundle: reading is allowed, creating still is not.
    create = await client.post(
        f"{BASE}/users",
        json={
            "email": f"x-{uuid.uuid4().hex[:8]}@aner-test.com",
            "password": PASSWORD,
            "role": "OPERATIONS",
        },
        headers=auth_header(granted_token),
    )
    assert create.status_code == 403, create.text

    # And the plain COMPLIANCE account is untouched by any of it.
    assert (
        await client.get(f"{BASE}/users", headers=auth_header(plain_token))
    ).status_code == 403


# ── custom roles ────────────────────────────────────────────────────────────


async def test_custom_role_round_trips_and_can_be_assigned(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    slug = f"reviewer-{uuid.uuid4().hex[:8]}"

    created = await client.post(
        ROLES,
        json={
            "slug": slug,
            "name": "Credit reviewer",
            "description": "Reads companies, reviews verifications.",
            "permissions": [
                {"module": "exporters", "action": "view"},
                {"module": "verifications", "action": "review"},
            ],
        },
        headers=auth_header(admin_token),
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["is_builtin"] is False
    assert role["builtin_role"] is None
    assert role["user_count"] == 0
    assert _pairs(role) == {("exporters", "view"), ("verifications", "review")}

    # Assign it to a new account, and see it resolve through the custom role.
    email = f"custom-{uuid.uuid4().hex[:8]}@aner-test.com"
    made = await client.post(
        f"{BASE}/users",
        json={
            "email": email,
            "password": PASSWORD,
            "role": "OPERATIONS",
            "role_id": role["id"],
        },
        headers=auth_header(admin_token),
    )
    assert made.status_code == 201, made.text
    assert made.json()["role_id"] == role["id"]

    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    theirs = await client.get(
        f"{BASE}/me/permissions", headers=auth_header(login.json()["access_token"])
    )
    assert {(p["module"], p["action"]) for p in theirs.json()["permissions"]} == {
        ("exporters", "view"),
        ("verifications", "review"),
    }
    # The custom role overrides the OPERATIONS default it would otherwise get.
    assert theirs.json()["role_name"] == "Credit reviewer"


async def test_duplicate_slug_is_refused(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    slug = f"dupe-{uuid.uuid4().hex[:8]}"
    body = {"slug": slug, "name": "First"}

    first = await client.post(ROLES, json=body, headers=auth_header(admin_token))
    assert first.status_code == 201, first.text

    again = await client.post(ROLES, json=body, headers=auth_header(admin_token))
    assert again.status_code == 409, again.text
    assert again.json()["error_code"] == "ROLE_SLUG_CONFLICT"


@pytest.mark.parametrize(
    "bad",
    [
        {"module": "exporters", "action": "teleport"},
        {"module": "nonexistent", "action": "view"},
        {"module": "users", "action": "delete"},  # not in the users catalogue
    ],
)
async def test_unknown_permission_is_refused_at_the_boundary(client: AsyncClient, bad: dict):
    """A permission nobody enforces would look granted in the UI, so an unknown
    pair is a 422 rather than a stored row."""
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    resp = await client.post(
        ROLES,
        json={"slug": f"bad-{uuid.uuid4().hex[:8]}", "name": "Bad", "permissions": [bad]},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("slug", ["Has Spaces", "UPPER", "trailing-", "a", "with_underscore"])
async def test_slug_shape_is_enforced(client: AsyncClient, slug: str):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    resp = await client.post(
        ROLES, json={"slug": slug, "name": "X"}, headers=auth_header(admin_token)
    )
    assert resp.status_code == 422, (slug, resp.text)


async def test_permissions_update_replaces_rather_than_merges(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    created = await client.post(
        ROLES,
        json={
            "slug": f"replace-{uuid.uuid4().hex[:8]}",
            "name": "Replace me",
            "permissions": [
                {"module": "exporters", "action": "view"},
                {"module": "exporters", "action": "edit"},
            ],
        },
        headers=auth_header(admin_token),
    )
    role_id = created.json()["id"]

    updated = await client.patch(
        f"{ROLES}/{role_id}",
        json={"permissions": [{"module": "audit", "action": "view"}]},
        headers=auth_header(admin_token),
    )
    assert updated.status_code == 200, updated.text
    assert _pairs(updated.json()) == {("audit", "view")}


async def test_role_held_by_someone_cannot_be_deleted(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    created = await client.post(
        ROLES,
        json={"slug": f"held-{uuid.uuid4().hex[:8]}", "name": "Held"},
        headers=auth_header(admin_token),
    )
    role_id = created.json()["id"]

    made = await client.post(
        f"{BASE}/users",
        json={
            "email": f"holder-{uuid.uuid4().hex[:8]}@aner-test.com",
            "password": PASSWORD,
            "role": "OPERATIONS",
            "role_id": role_id,
        },
        headers=auth_header(admin_token),
    )
    assert made.status_code == 201, made.text

    refused = await client.delete(f"{ROLES}/{role_id}", headers=auth_header(admin_token))
    assert refused.status_code == 409, refused.text
    assert refused.json()["error_code"] == "ROLE_STILL_ASSIGNED"

    # Move them off it, and the delete goes through.
    moved = await client.patch(
        f"{BASE}/users/{made.json()['id']}",
        json={"role_id": None},
        headers=auth_header(admin_token),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["role_id"] is None

    deleted = await client.delete(f"{ROLES}/{role_id}", headers=auth_header(admin_token))
    assert deleted.status_code == 204, deleted.text


async def test_unassignable_role_cannot_be_given_to_anyone(client: AsyncClient):
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    created = await client.post(
        ROLES,
        json={"slug": f"wip-{uuid.uuid4().hex[:8]}", "name": "Work in progress"},
        headers=auth_header(admin_token),
    )
    role_id = created.json()["id"]
    await client.patch(
        f"{ROLES}/{role_id}", json={"is_assignable": False}, headers=auth_header(admin_token)
    )

    resp = await client.post(
        f"{BASE}/users",
        json={
            "email": f"wip-{uuid.uuid4().hex[:8]}@aner-test.com",
            "password": PASSWORD,
            "role": "OPERATIONS",
            "role_id": role_id,
        },
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "ROLE_NOT_ASSIGNABLE"


async def test_user_count_includes_enum_fallback_holders(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """Built-in roles are held by every account carrying the matching enum value,
    not only by accounts with an explicit assignment. Counting only the column
    would report 0 holders for roles the whole deployment is using."""
    roles = await _roles_by_slug(client, tokens[UserRole.ADMIN])
    assert roles["operations"]["user_count"] > 0


# ── the two reachable lockouts ──────────────────────────────────────────────


async def test_cannot_strip_role_management_from_your_own_role(client: AsyncClient):
    """Reachable, unlike user management's "last admin": an administrator editing the
    role they themselves hold can remove the permission needed to put it back."""
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    roles = await _roles_by_slug(client, admin_token)
    admin_role = roles["admin"]

    resp = await client.patch(
        f"{ROLES}/{admin_role['id']}",
        json={"permissions": [{"module": "users", "action": "view"}]},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "SELF_LOCKOUT_FORBIDDEN"

    # Unchanged — a refused edit must not apply partially.
    after = await _roles_by_slug(client, admin_token)
    assert _pairs(after["admin"]) == _pairs(admin_role)


async def test_can_edit_a_role_you_do_not_hold(client: AsyncClient):
    """Positive control for the guard above: it is about your own role only."""
    _, admin_token = await user_with_role(client, UserRole.ADMIN)
    created = await client.post(
        ROLES,
        json={
            "slug": f"other-{uuid.uuid4().hex[:8]}",
            "name": "Someone else's role",
            "permissions": [{"module": "roles", "action": "edit"}],
        },
        headers=auth_header(admin_token),
    )
    resp = await client.patch(
        f"{ROLES}/{created.json()['id']}",
        json={"permissions": []},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _pairs(resp.json()) == set()


def _sync_cursor_dsn() -> str:
    return get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")


def _deactivate_other_holders_of_roles_edit(keep_id: str) -> list[str]:
    """Deactivate every active account other than ``keep_id`` that holds
    ``roles:edit`` by either route — the query the guard itself counts with
    (``RoleRepository.count_active_holders_of``). Returns their ids for
    :func:`_reactivate`.

    All of them, not the first page of ADMINs: a shared test database collects
    administrators and custom role managers from earlier runs, and a single one left
    active is enough for the guard to rightly allow the demotion."""
    conn = psycopg2.connect(_sync_cursor_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT u.id::text FROM auth.users u "
                "JOIN auth.role r ON (u.role_id = r.id "
                "  OR (u.role_id IS NULL AND u.role = r.builtin_role)) "
                "JOIN auth.role_permission p ON p.role_id = r.id "
                "WHERE u.is_active AND p.module = 'roles' AND p.action = 'edit' "
                "  AND u.id <> %s::uuid",
                (keep_id,),
            )
            ids = [row[0] for row in cur.fetchall()]
            cur.execute(
                "UPDATE auth.users SET is_active = false WHERE id = ANY(%s::uuid[])", (ids,)
            )
        conn.commit()
    finally:
        conn.close()
    return ids


def _reactivate(ids: list[str]) -> None:
    conn = psycopg2.connect(_sync_cursor_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE auth.users SET is_active = true WHERE id = ANY(%s::uuid[])", (ids,))
        conn.commit()
    finally:
        conn.close()


async def test_last_role_manager_cannot_be_demoted_by_a_non_admin_user_editor(
    client: AsyncClient,
):
    """The lockout that opened up when these routes stopped requiring ADMIN.

    A user-editor who is not an administrator can reach every other account, so
    without this guard they could demote the last account holding `roles:edit` —
    after which nobody, including them, could grant it back.

    Isolated from the shared built-in roles: both actors get custom roles, and
    every other active role manager in the database is parked out of the way and
    restored.
    """
    _, admin_token = await user_with_role(client, UserRole.ADMIN)

    # An editor who can manage users but not roles.
    editor_role = await client.post(
        ROLES,
        json={
            "slug": f"useredit-{uuid.uuid4().hex[:8]}",
            "name": "User editor",
            "permissions": [
                {"module": "users", "action": "view"},
                {"module": "users", "action": "edit"},
            ],
        },
        headers=auth_header(admin_token),
    )
    editor_email = f"editor-{uuid.uuid4().hex[:8]}@aner-test.com"
    await client.post(
        f"{BASE}/users",
        json={
            "email": editor_email,
            "password": PASSWORD,
            "role": "API_USER",
            "role_id": editor_role.json()["id"],
        },
        headers=auth_header(admin_token),
    )
    editor_login = await client.post(
        f"{BASE}/login", json={"email": editor_email, "password": PASSWORD}
    )
    editor_token = editor_login.json()["access_token"]

    # The only role manager: a custom role holding roles:edit, on one account.
    manager_role = await client.post(
        ROLES,
        json={
            "slug": f"rolemgr-{uuid.uuid4().hex[:8]}",
            "name": "Role manager",
            "permissions": [{"module": "roles", "action": "edit"}],
        },
        headers=auth_header(admin_token),
    )
    manager_email = f"manager-{uuid.uuid4().hex[:8]}@aner-test.com"
    manager = await client.post(
        f"{BASE}/users",
        json={
            "email": manager_email,
            "password": PASSWORD,
            "role": "API_USER",
            "role_id": manager_role.json()["id"],
        },
        headers=auth_header(admin_token),
    )
    manager_id = manager.json()["id"]

    # Park every other active holder of roles:edit, so the manager really is the last
    # one, then put them back.
    parked = _deactivate_other_holders_of_roles_edit(manager_id)

    try:
        refused = await client.patch(
            f"{BASE}/users/{manager_id}",
            json={"role_id": None},
            headers=auth_header(editor_token),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error_code"] == "LAST_ROLE_MANAGER_PROTECTED"

        deactivation = await client.patch(
            f"{BASE}/users/{manager_id}",
            json={"is_active": False},
            headers=auth_header(editor_token),
        )
        assert deactivation.status_code == 409, deactivation.text
        assert deactivation.json()["error_code"] == "LAST_ROLE_MANAGER_PROTECTED"
    finally:
        _reactivate(parked)

    # With administrators back, the same edit is allowed: the guard is about the
    # last holder, not about this account.
    allowed = await client.patch(
        f"{BASE}/users/{manager_id}",
        json={"role_id": None},
        headers=auth_header(admin_token),
    )
    assert allowed.status_code == 200, allowed.text
