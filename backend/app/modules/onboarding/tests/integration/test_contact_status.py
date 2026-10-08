"""A contact's status and its "last verified" date, over HTTP.

A contact who leaves stays on the record, out of the way: marked INACTIVE or
LEFT_COMPANY with a reason, no longer primary, and never primary again until it is
active. Verifying a contact stamps when and who, and a contact not verified for
``CRM_CONTACT_REVERIFY_MONTHS`` reads ``verification_due``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


async def _contact(client: AsyncClient, token: str, **fields) -> tuple[uuid.UUID, str]:
    customer_id = await make_company()
    resp = await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": "Jane Doe", **fields},
    )
    assert resp.status_code == 201, resp.text
    return customer_id, resp.json()["id"]


async def _set_status(client, token, customer_id, contact_id, **body):
    return await client.post(
        f"{BASE}/{customer_id}/contacts/{contact_id}/status",
        headers=auth_header(token),
        json=body,
    )


async def _contact_history(client, token, customer_id) -> list[dict]:
    resp = await client.get(
        f"{BASE}/{customer_id}/history",
        headers=auth_header(token),
        params={"dimension": "contact"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["entries"]


async def test_a_contact_who_left_keeps_the_reason_and_stops_being_primary(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token, is_primary=True)

    resp = await _set_status(
        client, token, customer_id, contact_id,
        status="LEFT_COMPANY", reason="Moved to another firm",
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "LEFT_COMPANY"
    assert body["status_reason"] == "Moved to another firm"
    assert body["status_changed_at"] is not None
    assert body["is_primary_contact"] is False

    [entry] = await _contact_history(client, token, customer_id)
    assert entry["event_type"] == "contact_status_changed"
    assert (entry["from_value"], entry["to_value"]) == ("ACTIVE", "LEFT_COMPANY")
    assert entry["reason"] == "Moved to another firm"
    assert entry["details"]["was_primary"] is True


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_leaving_active_needs_a_reason(client: AsyncClient, reason):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token)

    resp = await _set_status(
        client, token, customer_id, contact_id, status="INACTIVE", reason=reason
    )

    assert resp.status_code == 422, resp.text
    listed = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(token))
    assert listed.json()["contacts"][0]["status"] == "ACTIVE"


async def test_an_inactive_contact_cannot_be_made_primary(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token)
    await _set_status(client, token, customer_id, contact_id, status="INACTIVE", reason="On leave")

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact_id}",
        headers=auth_header(token),
        json={"is_primary": True},
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "CONTACT_NOT_ACTIVE"


async def test_a_contact_made_active_again_needs_no_reason_and_may_be_primary(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token)
    await _set_status(client, token, customer_id, contact_id, status="INACTIVE", reason="On leave")

    back = await _set_status(client, token, customer_id, contact_id, status="ACTIVE")
    assert back.status_code == 200, back.text
    assert back.json()["status_reason"] is None

    promoted = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact_id}",
        headers=auth_header(token),
        json={"is_primary": True},
    )
    assert promoted.status_code == 200, promoted.text
    assert len(await _contact_history(client, token, customer_id)) == 2


async def test_the_same_status_again_writes_nothing(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token)

    resp = await _set_status(client, token, customer_id, contact_id, status="ACTIVE")

    assert resp.status_code == 200, resp.text
    assert await _contact_history(client, token, customer_id) == []


async def test_marking_a_contact_verified_stamps_when_and_who(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token)

    resp = await client.post(
        f"{BASE}/{customer_id}/contacts/{contact_id}/verification", headers=auth_header(token)
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_verified_at"] is not None
    assert body["last_verified_by"] is not None
    assert body["verification_due"] is False
    [entry] = await _contact_history(client, token, customer_id)
    assert entry["event_type"] == "contact_verified"


async def test_a_contact_not_verified_for_a_year_is_due_a_check(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _contact(client, token)
    months = get_settings().CRM_CONTACT_REVERIFY_MONTHS
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterContact)
            .where(ExporterContact.id == uuid.UUID(contact_id))
            .values(created_at=datetime.now(UTC) - timedelta(days=31 * months + 1))
        )
        await db.commit()

    listed = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(token))
    assert listed.json()["contacts"][0]["verification_due"] is True

    await client.post(
        f"{BASE}/{customer_id}/contacts/{contact_id}/verification", headers=auth_header(token)
    )
    listed = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(token))
    assert listed.json()["contacts"][0]["verification_due"] is False


async def test_developer_may_not_change_a_contacts_status(client: AsyncClient):
    ops = await token_with_role(client, UserRole.OPERATIONS)
    developer = await token_with_role(client, UserRole.DEVELOPER)
    customer_id, contact_id = await _contact(client, ops)

    resp = await _set_status(
        client, developer, customer_id, contact_id, status="INACTIVE", reason="x"
    )
    assert resp.status_code == 403, resp.text
    verify = await client.post(
        f"{BASE}/{customer_id}/contacts/{contact_id}/verification", headers=auth_header(developer)
    )
    assert verify.status_code == 403, verify.text


def test_the_database_refuses_a_primary_contact_who_is_not_active():
    customer_id = uuid.uuid4()
    conn = psycopg2.connect(
        get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    )
    try:
        with conn.cursor() as cursor:
            from app.modules.onboarding.tests.fixtures.companies import insert_company

            insert_company(cursor, customer_id)
            with pytest.raises(psycopg2.errors.CheckViolation) as raised:
                cursor.execute(
                    "INSERT INTO onboarding.exporter_contact "
                    "(id, customer_id, name, is_primary_contact, status) "
                    "VALUES (%s, %s, 'Gone', true, 'LEFT_COMPANY')",
                    (str(uuid.uuid4()), str(customer_id)),
                )
            assert "ck_exporter_contact_primary_is_active" in str(raised.value)
    finally:
        conn.rollback()
        conn.close()


async def test_the_company_list_flags_and_filters_companies_with_no_primary_contact(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.OPERATIONS)
    with_primary, contact_id = await _contact(client, token, is_primary=True)
    without, _ = await _contact(client, token)

    async def listed(**params) -> dict[str, bool]:
        resp = await client.get(
            BASE, headers=auth_header(token), params={"limit": 200, **params}
        )
        assert resp.status_code == 200, resp.text
        return {
            row["customer_id"]: row["has_active_primary_contact"]
            for row in resp.json()["profiles"]
        }

    rows = await listed()
    assert rows[str(with_primary)] is True
    assert rows[str(without)] is False

    missing = await listed(missing_primary_contact="true")
    assert str(without) in missing
    assert str(with_primary) not in missing

    # The primary leaves: the company now has nobody to reach.
    await _set_status(
        client, token, with_primary, contact_id, status="LEFT_COMPANY", reason="Retired"
    )
    assert str(with_primary) in await listed(missing_primary_contact="true")
