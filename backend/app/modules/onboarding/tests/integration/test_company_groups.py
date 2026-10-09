"""Parent and child companies, over HTTP.

The walk-through: linking A as B's parent shows both in A's Group tab; linking A under
B as well is refused with a clear message. History is on both companies, a reader of
the group without compliance work does not see members' checks, and companies sharing
a beneficial owner are suggested — never linked.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _link(client, token, child, parent, relationship="SUBSIDIARY"):
    return await client.put(
        f"{BASE}/{child}/parent",
        headers=auth_header(token),
        json={"parent_company_id": str(parent) if parent else None, "relationship": relationship},
    )


async def test_linking_a_parent_shows_both_in_the_group_and_a_loop_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    a, b, c = [await make_company() for _ in range(3)]

    linked = await _link(client, token, b, a)
    assert linked.status_code == 200, linked.text
    await _link(client, token, c, b, "BRANCH_OFFICE")

    group = (await client.get(f"{BASE}/{a}/group", headers=auth_header(token))).json()
    depths = {m["company_id"]: m["depth"] for m in group["members"]}
    assert depths == {str(a): 0, str(b): 1, str(c): 2}
    from_c = (await client.get(f"{BASE}/{c}/group", headers=auth_header(token))).json()
    assert from_c["ultimate_parent_id"] == str(a)

    loop = await _link(client, token, a, c)
    assert loop.status_code == 422, loop.text
    assert "loop" in loop.json()["detail"]
    assert (await _link(client, token, a, a)).status_code == 422


async def test_a_link_and_an_unlink_are_in_both_companies_history(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    parent, child = await make_company(), await make_company()
    await _link(client, token, child, parent)
    cleared = await _link(client, token, child, None, None)
    assert cleared.status_code == 200, cleared.text

    async def events(company_id):
        resp = await client.get(
            f"{BASE}/{company_id}/history", headers=auth_header(token), params={"dimension": "group"}
        )
        return sorted(e["event_type"] for e in resp.json()["entries"])

    assert await events(child) == ["group_parent_cleared", "group_parent_set"]
    assert await events(parent) == ["group_member_added", "group_member_removed"]


async def test_a_relationship_is_required_and_developer_may_not_link(client: AsyncClient):
    ops = await token_with_role(client, UserRole.OPERATIONS)
    developer = await token_with_role(client, UserRole.DEVELOPER)
    parent, child = await make_company(), await make_company()

    assert (await _link(client, ops, child, parent, None)).status_code == 422
    assert (await _link(client, developer, child, parent)).status_code == 403
    group = await client.get(f"{BASE}/{child}/group", headers=auth_header(developer))
    assert group.status_code == 200
    assert all(m["background_check"] is None for m in group.json()["members"])


def test_the_database_refuses_a_loop_that_bypasses_the_service():
    a, b = uuid.uuid4(), uuid.uuid4()
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            from app.modules.onboarding.tests.fixtures.companies import insert_company

            insert_company(cursor, a)
            insert_company(cursor, b)
            cursor.execute(
                "UPDATE onboarding.exporter_profile SET parent_company_id = %s, "
                "group_relationship = 'SUBSIDIARY' WHERE customer_id = %s",
                (str(a), str(b)),
            )
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "UPDATE onboarding.exporter_profile SET parent_company_id = %s, "
                    "group_relationship = 'SUBSIDIARY' WHERE customer_id = %s",
                    (str(b), str(a)),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_companies_sharing_a_beneficial_owner_are_suggested(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    first, second, unrelated = [await make_company() for _ in range(3)]
    surname = f"Owner{uuid.uuid4().hex[:6]}"
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            for company, last in ((first, surname), (second, surname), (unrelated, "Nobody")):
                request_id = uuid.uuid4()
                cursor.execute(
                    "INSERT INTO onboarding.onboarding_request (id, tenant_id, idempotency_key, "
                    "customer_id, status, entity_type, legal_name, incorporation_country, "
                    "initial_user_id) VALUES (%s, %s, %s, %s, 'DRAFT', 'CORPORATION', "
                    "'Group test', 'IN', 'test')",
                    (str(request_id), str(uuid.uuid4()), uuid.uuid4().hex, str(company)),
                )
                cursor.execute(
                    "INSERT INTO onboarding.ubo_record (id, onboarding_request_id, first_name, "
                    "last_name, control_type, kyc_result) "
                    "VALUES (%s, %s, 'Priya', %s, 'DIRECT_OWNERSHIP', 'VERIFIED')",
                    (str(uuid.uuid4()), str(request_id), last),
                )
        conn.commit()
    finally:
        conn.close()

    resp = await client.get(f"{BASE}/{first}/group/suggestions", headers=auth_header(token))

    assert resp.status_code == 200, resp.text
    suggested = {s["company_id"]: s for s in resp.json()["suggestions"]}
    assert str(second) in suggested
    assert suggested[str(second)]["shared_people"] == [f"Priya {surname}"]
    assert str(unrelated) not in suggested
    # Never linked automatically.
    group = (await client.get(f"{BASE}/{first}/group", headers=auth_header(token))).json()
    assert len(group["members"]) == 1
