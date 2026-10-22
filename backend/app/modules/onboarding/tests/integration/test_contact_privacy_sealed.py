"""A contact's email and date of birth over HTTP, now that both columns are sealed.

Companion to `test_contact_phone_sealed`. What has to stay true for the screens: the
values go in as typed and come back readable to a viewer who may see them, masked to
everyone else, and no client ever receives a ciphertext. What has to become true for
the database: neither column holds anything readable.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


async def _add(client: AsyncClient, token: str, customer_id, **fields):
    resp = await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": "Jane Doe", **fields},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _stored(contact_id: str) -> tuple[str | None, str | None]:
    """The columns as the database holds them, not as the API renders them.

    Through the module rather than an imported name: the suite rebinds
    `AsyncSessionLocal` to a sessionmaker on its own loop.
    """
    async with db_services.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ExporterContact.email, ExporterContact.date_of_birth).where(
                ExporterContact.id == contact_id
            )
        )
        return row.one()


# ── What the database holds ──────────────────────────────────────────────────


async def test_neither_column_holds_anything_readable(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    contact = await _add(
        client,
        token,
        await make_company(),
        email="jane.doe@acme-exports.example",
        date_of_birth="1983-07-14",
        is_director=True,
    )

    email, dob = await _stored(contact["id"])

    assert email.startswith("d1."), email
    assert "jane.doe" not in email
    assert "acme-exports" not in email
    assert dob.startswith("v1."), dob
    assert "1983" not in dob


async def test_the_same_address_typed_two_ways_is_stored_identically(client: AsyncClient):
    """Deterministic, so a duplicate check on this column keeps working."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    first = await _add(client, token, await make_company(), email="Jane@Acme.Example")
    second = await _add(client, token, await make_company(), email="  jane@acme.example ")

    assert (await _stored(first["id"]))[0] == (await _stored(second["id"]))[0]


async def test_two_people_sharing_a_birthday_do_not_look_alike(client: AsyncClient):
    """The other cipher, and the reason for it: nothing compares this column, so it
    leaks nothing — not even that these two were born on the same day."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    one = await _add(
        client, token, await make_company(), date_of_birth="1983-07-14", is_director=True
    )
    two = await _add(
        client, token, await make_company(), date_of_birth="1983-07-14", is_director=True
    )

    assert (await _stored(one["id"]))[1] != (await _stored(two["id"]))[1]


# ── What the API answers ─────────────────────────────────────────────────────


async def test_compliance_reads_both_in_full(client: AsyncClient):
    writer = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add(
        client,
        writer,
        customer_id,
        email="Jane.Doe@Acme-Exports.Example",
        date_of_birth="1983-07-14",
        is_director=True,
    )

    reader = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(reader))
    assert resp.status_code == 200, resp.text
    served = next(c for c in resp.json()["contacts"] if c["id"] == contact["id"])

    # Canonical, which is what the column now holds.
    assert served["email"] == "jane.doe@acme-exports.example"
    assert served["date_of_birth"] == "1983-07-14"


async def test_operations_reads_them_masked_and_never_the_ciphertext(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add(
        client,
        token,
        customer_id,
        email="jane.doe@acme-exports.example",
        date_of_birth="1983-07-14",
        is_director=True,
    )

    resp = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(token))
    served = next(c for c in resp.json()["contacts"] if c["id"] == contact["id"])

    assert not served["email"].startswith("d1."), "the ciphertext reached a client"
    assert served["email"] == "j•••@acme-exports.example"
    assert not (served["date_of_birth"] or "").startswith("v1.")
    assert "1983" not in (served["date_of_birth"] or "")


async def test_the_write_response_is_masked_too(client: AsyncClient):
    """The 201 carries the same rules as a read."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    contact = await _add(
        client,
        token,
        await make_company(),
        email="jane@acme.example",
        date_of_birth="1983-07-14",
        is_director=True,
    )

    assert not contact["email"].startswith("d1.")
    assert "•" in contact["email"]
    assert not (contact["date_of_birth"] or "").startswith("v1.")


# ── Editing ──────────────────────────────────────────────────────────────────


async def test_editing_the_email_seals_the_new_one(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add(client, token, customer_id, email="jane@acme.example")

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact['id']}",
        headers=auth_header(token),
        json={"email": "Jane.Roe@Acme.Example"},
    )
    assert resp.status_code == 200, resp.text

    email, _ = await _stored(contact["id"])
    assert email.startswith("d1.")
    assert "jane.roe" not in email

    reader = await token_with_role(client, UserRole.COMPLIANCE)
    read = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(reader))
    served = next(c for c in read.json()["contacts"] if c["id"] == contact["id"])
    assert served["email"] == "jane.roe@acme.example"


async def test_editing_another_field_leaves_the_email_sealed_once(client: AsyncClient):
    """A second sealing would store a ciphertext of a ciphertext."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add(client, token, customer_id, email="jane@acme.example")
    before, _ = await _stored(contact["id"])

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact['id']}",
        headers=auth_header(token),
        json={"name": "Jane Roe"},
    )
    assert resp.status_code == 200, resp.text

    assert (await _stored(contact["id"]))[0] == before


async def test_clearing_the_email_empties_the_column(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add(client, token, customer_id, email="jane@acme.example")

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact['id']}",
        headers=auth_header(token),
        json={"email": None},
    )
    assert resp.status_code == 200, resp.text

    assert (await _stored(contact["id"]))[0] is None
