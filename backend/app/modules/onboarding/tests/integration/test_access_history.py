"""Who changed whose access: every user and role change lands in the audit trail.

There is no approval step — one administrator acts and the change applies at once —
so the trail is what answers "who gave Priya Compliance, and when". Each history
route reads it back for one account or one role, newest first.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

AUTH = "/api/v1/auth"


async def _admin(client: AsyncClient) -> tuple[str, dict]:
    admin_id, token = await user_with_role(client, UserRole.ADMIN)
    return admin_id, auth_header(token)


async def _history(client: AsyncClient, headers: dict, kind: str, subject_id: str) -> list[dict]:
    resp = await client.get(f"{AUTH}/{kind}/{subject_id}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["entries"]


def _changes(entry: dict) -> dict[str, tuple]:
    return {c["field"]: (c["from_value"], c["to_value"]) for c in entry["changes"]}


async def test_creating_and_changing_an_account_is_recorded_with_who_did_it(client: AsyncClient):
    admin_id, headers = await _admin(client)
    email = f"priya-{uuid.uuid4().hex[:8]}@aner-test.com"
    created = await client.post(
        f"{AUTH}/users",
        json={
            "email": email,
            "password": "Str0ng!Passw0rd",
            "full_name": "Priya Nair",
            "role": "OPERATIONS",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    changed = await client.patch(
        f"{AUTH}/users/{user_id}", json={"role": "COMPLIANCE"}, headers=headers
    )
    assert changed.status_code == 200, changed.text
    # The change applied at once: no approval step.
    assert changed.json()["role"] == "COMPLIANCE"
    await client.patch(f"{AUTH}/users/{user_id}", json={"is_active": False}, headers=headers)
    reset = await client.post(
        f"{AUTH}/users/{user_id}/password",
        json={"new_password": "An0ther!Passw0rd"},
        headers=headers,
    )
    assert reset.status_code == 204, reset.text

    entries = await _history(client, headers, "users", user_id)
    assert [e["event_type"] for e in entries] == [
        "access.user_password_reset",
        "access.user_updated",
        "access.user_updated",
        "access.user_created",
    ]
    assert all(e["actor_id"] == admin_id for e in entries)
    assert _changes(entries[0]) == {"password": (None, "reset")}
    assert _changes(entries[1]) == {"is_active": (True, False)}
    assert _changes(entries[2]) == {"role": ("OPERATIONS", "COMPLIANCE")}
    assert _changes(entries[3])["email"] == (None, email)
    assert _changes(entries[3])["role"] == (None, "OPERATIONS")
    # A password is never written to the trail.
    assert "Str0ng" not in str(entries) and "An0ther" not in str(entries)


async def test_an_edit_that_changes_nothing_records_no_changes(client: AsyncClient):
    _, headers = await _admin(client)
    target_id, _ = await user_with_role(client, UserRole.OPERATIONS)
    await client.patch(f"{AUTH}/users/{target_id}", json={"role": "OPERATIONS"}, headers=headers)
    [entry] = await _history(client, headers, "users", target_id)
    assert entry["changes"] == []


async def test_a_roles_permission_changes_and_its_deletion_are_recorded(client: AsyncClient):
    admin_id, headers = await _admin(client)
    slug = f"desk-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        f"{AUTH}/roles",
        json={
            "slug": slug,
            "name": "Desk",
            "description": None,
            "permissions": [{"module": "exporters", "action": "view"}],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    updated = await client.patch(
        f"{AUTH}/roles/{role_id}",
        json={
            "name": "Front desk",
            "permissions": [
                {"module": "exporters", "action": "view"},
                {"module": "deals", "action": "view"},
            ],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    deleted = await client.delete(f"{AUTH}/roles/{role_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text

    # A deleted role's history stays readable.
    entries = await _history(client, headers, "roles", role_id)
    assert [e["event_type"] for e in entries] == [
        "access.role_deleted",
        "access.role_updated",
        "access.role_created",
    ]
    assert all(e["actor_id"] == admin_id for e in entries)
    update = {c["field"]: c for c in entries[1]["changes"]}
    assert (update["name"]["from_value"], update["name"]["to_value"]) == ("Desk", "Front desk")
    assert (update["permissions"]["added"], update["permissions"]["removed"]) == (
        ["deals:view"],
        [],
    )
    creation = {c["field"]: c for c in entries[2]["changes"]}
    assert creation["permissions"]["added"] == ["exporters:view"]


@pytest.mark.parametrize(
    ("role", "status"),
    [
        (UserRole.ADMIN, 200),
        (UserRole.COMPLIANCE, 403),
        (UserRole.OPERATIONS, 403),
        (UserRole.DEVELOPER, 403),
    ],
)
async def test_history_is_read_with_users_view_and_roles_view(
    client: AsyncClient, role: UserRole, status: int
):
    reader_id, token = await user_with_role(client, role)
    for kind in ("users", "roles"):
        resp = await client.get(
            f"{AUTH}/{kind}/{reader_id}/history", headers=auth_header(token)
        )
        assert resp.status_code == status, (kind, resp.text)
