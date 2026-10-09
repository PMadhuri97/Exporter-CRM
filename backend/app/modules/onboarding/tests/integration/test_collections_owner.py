"""A company's collections owner, over HTTP: named by whoever may assign collectors,
a reason to change or clear one, any active staff user eligible, a stale screen
refused, every change in History, "My collections", and a bulk move."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import (
    auth_header,
    deactivate,
    user_with_permissions,
    user_with_role,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


async def _assign(client, token, company_id, user_id, *, seen=None, reason=None):
    return await client.post(
        f"{BASE}/exporters/{company_id}/collections-owner",
        headers=auth_header(token),
        json={"user_id": user_id, "seen_user_id": seen, "reason": reason},
    )


async def test_compliance_names_a_collections_owner_and_history_says_so(client: AsyncClient):
    _, compliance = await user_with_role(client, UserRole.COMPLIANCE)
    finance_id, _ = await user_with_role(client, UserRole.OPERATIONS)
    company_id = await make_company()

    resp = await _assign(client, compliance, company_id, finance_id)

    assert resp.status_code == 200, resp.text
    assert resp.json()["collections_owner_user_id"] == finance_id
    assert resp.json()["collections_owner_name"]
    history = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        headers=auth_header(compliance),
        params={"dimension": "collections_owner"},
    )
    [row] = history.json()["entries"]
    assert row["event_type"] == "collections_owner_assigned"


async def test_an_rm_and_the_admin_may_not_name_one_but_a_sales_lead_may(client: AsyncClient):
    owner_id, rm = await user_with_role(client, UserRole.OPERATIONS)
    _, admin = await user_with_role(client, UserRole.ADMIN)
    _, lead = await user_with_permissions(
        client, UserRole.OPERATIONS, ("exporters", "assign_rm"), ("exporters", "assign_collector")
    )
    company_id = await make_company()

    assert (await _assign(client, rm, company_id, owner_id)).status_code == 403
    assert (await _assign(client, admin, company_id, owner_id)).status_code == 403
    assert (await _assign(client, lead, company_id, owner_id)).status_code == 200


async def test_the_administrator_and_developer_cannot_be_named(client: AsyncClient):
    _, compliance = await user_with_role(client, UserRole.COMPLIANCE)
    admin_id, _ = await user_with_role(client, UserRole.ADMIN)
    developer_id, _ = await user_with_role(client, UserRole.DEVELOPER)
    company_id = await make_company()

    for user_id in (admin_id, developer_id):
        refused = await _assign(client, compliance, company_id, user_id)
        assert refused.status_code == 422, refused.text


async def test_a_change_needs_a_reason_and_a_stale_screen_is_refused(client: AsyncClient):
    _, compliance = await user_with_role(client, UserRole.COMPLIANCE)
    first, _ = await user_with_role(client, UserRole.OPERATIONS)
    second, _ = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await make_company()
    await _assign(client, compliance, company_id, first)

    stale = await _assign(client, compliance, company_id, second, seen=None, reason="x")
    assert stale.status_code == 409, stale.text
    no_reason = await _assign(client, compliance, company_id, second, seen=first)
    assert no_reason.status_code == 422, no_reason.text
    changed = await _assign(client, compliance, company_id, second, seen=first, reason="Moved team")
    assert changed.status_code == 200, changed.text


async def test_a_deactivated_or_developer_account_cannot_be_named(client: AsyncClient):
    _, compliance = await user_with_role(client, UserRole.COMPLIANCE)
    gone, _ = await user_with_role(client, UserRole.OPERATIONS)
    deactivate(gone)
    developer, _ = await user_with_role(client, UserRole.DEVELOPER)
    company_id = await make_company()

    assert (await _assign(client, compliance, company_id, gone)).status_code == 422
    assert (await _assign(client, compliance, company_id, developer)).status_code == 422


async def test_my_collections_and_a_bulk_reassignment(client: AsyncClient):
    _, compliance = await user_with_role(client, UserRole.COMPLIANCE)
    leaver_id, leaver = await user_with_role(client, UserRole.OPERATIONS)
    stayer_id, _ = await user_with_role(client, UserRole.OPERATIONS)
    companies = [await make_company() for _ in range(3)]
    for company_id in companies:
        await _assign(client, compliance, company_id, leaver_id)

    mine = await client.get(
        f"{BASE}/exporters",
        headers=auth_header(leaver),
        params={"collections_owner": "me", "limit": 200},
    )
    assert {row["customer_id"] for row in mine.json()["profiles"]} >= {str(c) for c in companies}

    dry = await client.post(
        f"{BASE}/collections-owners/reassign",
        headers=auth_header(compliance),
        json={"from_user_id": leaver_id, "to_user_id": stayer_id, "reason": "Leaving", "dry_run": True},
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["moved"] == 0 and dry.json()["matched"] >= 3

    run = await client.post(
        f"{BASE}/collections-owners/reassign",
        headers=auth_header(compliance),
        json={
            "from_user_id": leaver_id,
            "to_user_id": stayer_id,
            "company_ids": [str(c) for c in companies],
            "reason": "Leaving",
        },
    )
    assert run.status_code == 200, run.text
    assert run.json()["moved"] == 3
    history = await client.get(
        f"{BASE}/exporters/{companies[0]}/history",
        headers=auth_header(compliance),
        params={"dimension": "collections_owner"},
    )
    assert [e["event_type"] for e in history.json()["entries"]][0] == "collections_owner_reassigned"
