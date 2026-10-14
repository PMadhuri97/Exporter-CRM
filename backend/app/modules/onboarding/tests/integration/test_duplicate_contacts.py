"""A contact this company can already reach is refused, not recorded twice.

Either field is enough: an email address already on the company, or a phone number
already on it. A second row holds nothing the first does not, and two identical
contacts on a company are what a double submit or a re-typed form leaves behind.

Worth knowing what the rule also refuses, since it was chosen rather than fallen into:
one person listed twice under two roles shares an email, and an office switchboard is
shared by several people. Both are refused; the second contact goes in without the
shared field, or the first is edited.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


async def _add(client: AsyncClient, token: str, customer_id, **contact):
    """Adds a contact and returns the raw response, refusal included."""
    return await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": "Jane Doe", **contact},
    )


async def _added(client: AsyncClient, token: str, customer_id, **contact) -> dict:
    response = await _add(client, token, customer_id, **contact)
    assert response.status_code == 201, response.text
    return response.json()


async def _contacts(client: AsyncClient, token: str, customer_id) -> list[dict]:
    listed = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(token))
    assert listed.status_code == 200, listed.text
    return listed.json()["contacts"]


async def test_the_first_contact_goes_in(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()

    created = await _added(client, token, customer_id, email="jane@acme.example")

    assert created["email"]


async def test_the_same_contact_twice_is_refused(client: AsyncClient):
    """The case from the screen: the same details entered a second time."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    first = await _added(
        client, token, customer_id, email="jane@acme.example", phone="9876543210"
    )

    refused = await _add(
        client, token, customer_id, email="jane@acme.example", phone="9876543210"
    )

    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["error_code"] == "EXPORTER_CONTACT_ALREADY_EXISTS"
    assert body["error_context"]["name"] == "Jane Doe"
    assert body["error_context"]["contact_id"] == first["id"]
    # Nothing was written: still the one contact.
    assert len(await _contacts(client, token, customer_id)) == 1


async def test_the_same_email_alone_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, email="jane@acme.example", phone="9876500001")

    refused = await _add(
        client, token, customer_id, name="John Roe", email="jane@acme.example", phone="9876500002"
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error_context"]["field"] == "email"
    assert len(await _contacts(client, token, customer_id)) == 1


async def test_the_same_phone_alone_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, email="jane@acme.example", phone="9876543210")

    refused = await _add(
        client, token, customer_id, name="John Roe", email="john@acme.example", phone="9876543210"
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error_context"]["field"] == "phone"
    assert len(await _contacts(client, token, customer_id)) == 1


async def test_the_email_is_compared_without_case(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, email="jane@acme.example")

    refused = await _add(client, token, customer_id, email="JANE@Acme.Example")

    assert refused.status_code == 409, refused.text


async def test_a_phone_is_compared_by_its_digits(client: AsyncClient):
    """`+91 98765 43210` and `9876543210` are the same line to call."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, phone="+91 98765 43210")

    refused = await _add(client, token, customer_id, name="John Roe", phone="9876543210")

    assert refused.status_code == 409, refused.text
    assert refused.json()["error_context"]["field"] == "phone"


async def test_different_people_at_one_domain_are_not_the_same_contact(client: AsyncClient):
    """Why this cannot be done in the browser: most roles are shown
    `d•••@acme.example` for both of these, which look identical as displayed and are
    two people as stored."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, name="Dev One", email="dev@acme.example")

    created = await _add(client, token, customer_id, name="Dana Two", email="dana@acme.example")

    assert created.status_code == 201, created.text


async def test_a_contact_with_neither_email_nor_phone_is_never_a_duplicate(
    client: AsyncClient,
):
    """Nothing to compare. A name alone can repeat — two people do share a name."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, name="Jane Doe")

    created = await _add(client, token, customer_id, name="Jane Doe")

    assert created.status_code == 201, created.text


async def test_a_contact_who_left_does_not_block_their_replacement(client: AsyncClient):
    """The desk is handed over: the same email and line, a different person. The one
    who left is kept as a record of who was there and must not stand in the way."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    first = await _added(
        client, token, customer_id, email="desk@acme.example", phone="9876543210"
    )
    left = await client.post(
        f"{BASE}/{customer_id}/contacts/{first['id']}/status",
        headers=auth_header(token),
        json={"status": "LEFT_COMPANY", "reason": "Moved on"},
    )
    assert left.status_code == 200, left.text

    replacement = await _add(
        client, token, customer_id, name="New Person", email="desk@acme.example", phone="9876543210"
    )

    assert replacement.status_code == 201, replacement.text


async def test_another_company_with_the_same_contact_is_not_a_duplicate(client: AsyncClient):
    """One agent represents several exporters. This is about one company's own list."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    one = await make_company()
    another = await make_company()
    await _added(client, token, one, email="agent@broker.example")

    created = await _add(client, token, another, email="agent@broker.example")

    assert created.status_code == 201, created.text


# ── Editing onto one ─────────────────────────────────────────────────────────


async def test_an_edit_onto_an_existing_email_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, email="jane@acme.example")
    second = await _added(client, token, customer_id, name="John Roe", email="john@acme.example")

    refused = await client.patch(
        f"{BASE}/{customer_id}/contacts/{second['id']}",
        headers=auth_header(token),
        json={"email": "jane@acme.example"},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error_code"] == "EXPORTER_CONTACT_ALREADY_EXISTS"


async def test_an_edit_is_judged_on_what_it_leaves_behind(client: AsyncClient):
    """Changing only the phone onto one another contact already has is the same
    duplicate as sending both fields."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    await _added(client, token, customer_id, email="jane@acme.example", phone="9876543210")
    second = await _added(
        client, token, customer_id, name="John Roe", email="john@acme.example", phone="9000000000"
    )

    refused = await client.patch(
        f"{BASE}/{customer_id}/contacts/{second['id']}",
        headers=auth_header(token),
        json={"phone": "9876543210"},
    )

    assert refused.status_code == 409, refused.text


async def test_a_contact_is_never_a_duplicate_of_itself(client: AsyncClient):
    """Re-saving what a contact already holds must not refuse it against itself."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    only = await _added(client, token, customer_id, email="jane@acme.example", phone="9876543210")

    saved = await client.patch(
        f"{BASE}/{customer_id}/contacts/{only['id']}",
        headers=auth_header(token),
        json={"email": "jane@acme.example", "phone": "9876543210"},
    )

    assert saved.status_code == 200, saved.text


async def test_an_edit_that_touches_neither_is_not_checked(client: AsyncClient):
    """Correcting a name must not be refused over an email that was already there."""
    token = await token_with_role(client, UserRole.COMPLIANCE)
    customer_id = await make_company()
    only = await _added(client, token, customer_id, email="jane@acme.example")

    saved = await client.patch(
        f"{BASE}/{customer_id}/contacts/{only['id']}",
        headers=auth_header(token),
        json={"name": "Jane Doe Jr"},
    )

    assert saved.status_code == 200, saved.text
