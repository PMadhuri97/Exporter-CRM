"""A company's addresses, over HTTP.

Many per company, one active default per type, deactivated rather than deleted, every
change in the company's history; a GST registration can be linked to the address it
trades from; and the list says when the registered address changed after a Clear.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"

REGISTERED = {
    "address_type": "REGISTERED",
    "line1": "12 Marine Drive",
    "city": "Mumbai",
    "state": "Maharashtra",
    "postal_code": "400001",
    "country": "in",
}


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _add(client, token, customer_id, **body) -> dict:
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/addresses",
        headers=auth_header(token),
        json={**REGISTERED, **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _list(client, token, customer_id) -> dict:
    resp = await client.get(f"{BASE}/exporters/{customer_id}/addresses", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _history(client, token, customer_id) -> list[dict]:
    resp = await client.get(
        f"{BASE}/exporters/{customer_id}/history",
        headers=auth_header(token),
        params={"dimension": "address"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["entries"]


async def test_the_first_address_of_a_type_is_its_default(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()

    first = await _add(client, token, customer_id)
    second = await _add(client, token, customer_id, line1="Plot 7, MIDC")

    assert first["is_default"] is True
    assert first["country"] == "IN"
    assert second["is_default"] is False


async def test_making_another_the_default_demotes_the_old_one(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    first = await _add(client, token, customer_id)
    second = await _add(client, token, customer_id, line1="Plot 7, MIDC")

    resp = await client.post(f"{BASE}/addresses/{second['id']}/default", headers=auth_header(token))

    assert resp.status_code == 200, resp.text
    rows = {a["id"]: a for a in (await _list(client, token, customer_id))["addresses"]}
    assert rows[second["id"]]["is_default"] is True
    assert rows[first["id"]]["is_default"] is False
    # A billing address is a different type: it has its own default.
    billing = await _add(client, token, customer_id, address_type="BILLING")
    assert billing["is_default"] is True


async def test_a_foreign_buyer_with_no_gstin_can_hold_an_address(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()

    address = await _add(
        client, token, customer_id,
        address_type="SHIPPING", line1="Wilhelminakade 909", city="Rotterdam",
        state=None, postal_code="3072 AP", country="NL",
    )

    assert address["country"] == "NL"
    assert address["state"] is None


async def test_an_edit_changes_only_what_was_sent_and_is_in_history(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    address = await _add(client, token, customer_id)

    resp = await client.patch(
        f"{BASE}/addresses/{address['id']}",
        headers=auth_header(token),
        json={"postal_code": "400021"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["postal_code"] == "400021"
    assert resp.json()["line1"] == "12 Marine Drive"
    events = [e["event_type"] for e in await _history(client, token, customer_id)]
    assert sorted(events) == ["address_added", "address_updated"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({"line1": None}, id="line1-null"),
        pytest.param({"city": "  "}, id="city-blank"),
        pytest.param({"country": "IND"}, id="country-three-letters"),
    ],
)
async def test_an_edit_that_cannot_apply_is_refused(client: AsyncClient, body: dict):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    address = await _add(client, token, customer_id)

    resp = await client.patch(
        f"{BASE}/addresses/{address['id']}", headers=auth_header(token), json=body
    )

    assert resp.status_code == 422, resp.text


async def test_a_deactivated_address_keeps_its_row_and_loses_its_default(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    address = await _add(client, token, customer_id)

    resp = await client.post(
        f"{BASE}/addresses/{address['id']}/deactivate",
        headers=auth_header(token),
        json={"reason": "Moved office"},
    )

    assert resp.status_code == 200, resp.text
    assert (resp.json()["is_active"], resp.json()["is_default"]) == (False, False)
    [row] = (await _list(client, token, customer_id))["addresses"]
    assert row["is_active"] is False
    refused = await client.patch(
        f"{BASE}/addresses/{address['id']}", headers=auth_header(token), json={"city": "Pune"}
    )
    assert refused.status_code == 422, refused.text
    # The next registered address becomes the default, there being none now.
    assert (await _add(client, token, customer_id, line1="New office"))["is_default"] is True


async def test_an_address_can_be_linked_to_a_gst_registration_of_the_same_company(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.OPERATIONS)
    pan = "ABCDE" + str(uuid.uuid4().int)[:4] + "F"
    customer_id = await make_company()
    patched = await client.patch(
        f"{BASE}/exporters/{customer_id}", headers=auth_header(token), json={"pan": pan}
    )
    assert patched.status_code == 200, patched.text
    added = await client.post(
        f"{BASE}/exporters/{customer_id}/gst-registrations",
        headers=auth_header(token),
        json={"gstin": f"27{pan}1Z5"},
    )
    assert added.status_code == 201, added.text
    registration_id = added.json()["id"]

    address = await _add(client, token, customer_id, gst_registration_id=registration_id)

    listed = await client.get(
        f"{BASE}/exporters/{customer_id}/gst-registrations", headers=auth_header(token)
    )
    [registration] = listed.json()["registrations"]
    assert registration["address_id"] == address["id"]

    other_company = await make_company()
    refused = await client.post(
        f"{BASE}/exporters/{other_company}/addresses",
        headers=auth_header(token),
        json={**REGISTERED, "gst_registration_id": registration_id},
    )
    assert refused.status_code == 404, refused.text


async def test_developer_reads_addresses_but_may_not_add_one(client: AsyncClient):
    ops = await token_with_role(client, UserRole.OPERATIONS)
    developer = await token_with_role(client, UserRole.DEVELOPER)
    customer_id = await make_company()
    await _add(client, ops, customer_id)

    assert len((await _list(client, developer, customer_id))["addresses"]) == 1
    refused = await client.post(
        f"{BASE}/exporters/{customer_id}/addresses",
        headers=auth_header(developer),
        json=REGISTERED,
    )
    assert refused.status_code == 403, refused.text


async def test_the_registered_address_changed_since_the_last_clear_is_flagged(
    client: AsyncClient,
):
    from app.modules.onboarding.tests.integration._compliance_support import cleared_company

    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    address = await _add(client, token, customer_id)
    await cleared_company(customer_id)

    before = await _list(client, token, customer_id)
    assert before["last_clear_at"] is not None
    assert before["registered_changed_since_clear"] is False

    await client.patch(
        f"{BASE}/addresses/{address['id']}", headers=auth_header(token), json={"line2": "Floor 3"}
    )
    assert (await _list(client, token, customer_id))["registered_changed_since_clear"] is True


def test_the_database_keeps_one_default_per_type_and_refuses_a_delete():
    customer_id = uuid.uuid4()
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            insert_company(cursor, customer_id)
            insert = (
                "INSERT INTO onboarding.company_address "
                "(id, customer_id, address_type, line1, city, country, is_default) "
                "VALUES (%s, %s, 'BILLING', 'x', 'y', 'IN', true)"
            )
            first = str(uuid.uuid4())
            cursor.execute(insert, (first, str(customer_id)))
            cursor.execute("SAVEPOINT second_default")
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(insert, (str(uuid.uuid4()), str(customer_id)))
            cursor.execute("ROLLBACK TO SAVEPOINT second_default")
            with pytest.raises(psycopg2.errors.RestrictViolation):
                cursor.execute("DELETE FROM onboarding.company_address WHERE id = %s", (first,))
    finally:
        conn.rollback()
        conn.close()
