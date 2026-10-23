"""One DIN, one person, per company: a second holder is refused with the first named.

A Director Identification Number is issued to one individual for life, so two people
of one company holding it means one record is wrong. Refused on add and on edit, over
every status; allowed on another company, where it is the same director on a second
board. No database index stands behind it yet — the service check is the rule.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


def _din() -> str:
    """A DIN nothing else uses: the suite's database persists between runs."""
    return f"{uuid.uuid4().int % 10**8:08d}"


async def _add(client: AsyncClient, token: str, customer_id, name: str, **body):
    return await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": name, "is_contact": False, "is_director": True, **body},
    )


async def _people(client: AsyncClient, token: str, customer_id) -> list[dict]:
    resp = await client.get(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        params={"role": "ALL", "include_inactive": "true"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["contacts"]


async def test_a_second_director_with_the_same_din_is_refused_naming_the_first(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    din = _din()
    first = (await _add(client, token, customer_id, "Nirup", din=din)).json()

    refused = await _add(client, token, customer_id, "Nithin", din=din)

    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["error_code"] == "EXPORTER_PERSON_DIN_ALREADY_EXISTS"
    assert body["error_context"]["name"] == "Nirup"
    assert body["error_context"]["contact_id"] == first["id"]
    assert body["error_context"]["field"] == "din"
    assert "Nirup" in body["detail"]
    assert din not in refused.text, "the DIN is not repeated back"
    # Nothing was written.
    assert [p["name"] for p in await _people(client, token, customer_id)] == ["Nirup"]


async def test_editing_a_director_onto_anothers_din_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    din = _din()
    await _add(client, token, customer_id, "Nirup", din=din)
    second = (await _add(client, token, customer_id, "Nithin", din=_din())).json()

    refused = await client.patch(
        f"{BASE}/{customer_id}/contacts/{second['id']}",
        headers=auth_header(token),
        json={"din": din},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error_context"]["name"] == "Nirup"
    people = {p["name"]: p["din"] for p in await _people(client, token, customer_id)}
    assert people["Nithin"] == second["din"], "the refused edit left the DIN as it was"


async def test_a_director_keeping_their_own_din_is_not_a_duplicate(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    din = _din()
    person = (await _add(client, token, customer_id, "Nirup", din=din)).json()

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{person['id']}",
        headers=auth_header(token),
        json={"din": din, "name": "Nirup Rao"},
    )

    assert resp.status_code == 200, resp.text


async def test_the_same_din_on_another_company_is_allowed(client: AsyncClient):
    """The same director on a second board."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    din = _din()
    await _add(client, token, await make_company(), "Nirup", din=din)

    resp = await _add(client, token, await make_company(), "Nirup", din=din)

    assert resp.status_code == 201, resp.text


async def test_a_director_who_left_still_holds_their_din(client: AsyncClient):
    """The DIN still names that person: bring the record back rather than add anew."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    din = _din()
    leaver = (await _add(client, token, customer_id, "Nirup", din=din)).json()
    left = await client.post(
        f"{BASE}/{customer_id}/contacts/{leaver['id']}/status",
        headers=auth_header(token),
        json={"status": "LEFT_COMPANY", "reason": "Resigned from the board"},
    )
    assert left.status_code == 200, left.text

    refused = await _add(client, token, customer_id, "Nithin", din=din)

    assert refused.status_code == 409, refused.text
    assert refused.json()["error_context"]["name"] == "Nirup"
