"""A contact's phone number over HTTP, now that the column holds a ciphertext.

What has to stay true for the screens: a number goes in as typed and comes back
readable to a viewer who may see it, masked to everyone else, and the ciphertext
itself never reaches a client. What has to become true for the database: the column
holds no dialable number, and the same line stored twice stores identically.
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


async def _add_contact(client: AsyncClient, token: str, customer_id, phone: str | None):
    resp = await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": "Jane Doe", "phone": phone},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _stored_phone(contact_id: str) -> str | None:
    """The column as the database holds it — not as the API renders it.

    Through the module rather than an imported name: the suite rebinds
    ``AsyncSessionLocal`` to a sessionmaker on its own loop, and a binding captured at
    import time would open a connection on a different one.
    """
    async with db_services.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ExporterContact.phone).where(ExporterContact.id == contact_id)
        )
        return row.scalar_one()


# ── What the database holds ──────────────────────────────────────────────────


async def test_the_column_holds_no_dialable_number(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add_contact(client, token, customer_id, "+91 98765 43210")

    stored = await _stored_phone(contact["id"])
    assert stored is not None
    assert stored.startswith("d1."), stored
    # The point of the whole exercise: a dump of this column reveals no number.
    assert "9876543210" not in stored
    assert "98765" not in stored


async def test_the_same_line_typed_two_ways_is_stored_identically(client: AsyncClient):
    """Deterministic, so a unique constraint or an equality lookup on this column
    still works. `encrypt_field` would store these differently."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    first = await _add_contact(client, token, await make_company(), "+91 98765 43210")
    second = await _add_contact(client, token, await make_company(), "09876543210")

    assert await _stored_phone(first["id"]) == await _stored_phone(second["id"])


async def test_two_different_numbers_are_stored_differently(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    first = await _add_contact(client, token, await make_company(), "080 2234 5678")
    second = await _add_contact(client, token, await make_company(), "044 2234 5678")

    # Two cities. The suffix rule this replaced called them one number.
    assert await _stored_phone(first["id"]) != await _stored_phone(second["id"])


async def test_a_phone_that_is_not_sent_stores_nothing(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    contact = await _add_contact(client, token, await make_company(), None)

    assert await _stored_phone(contact["id"]) is None


# ── What the API answers ─────────────────────────────────────────────────────


async def test_compliance_reads_the_real_number(client: AsyncClient):
    """A holder of `exporters:view_full_tax_id` sees it in full — in canonical form,
    which is what the column now holds."""
    writer = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add_contact(client, writer, customer_id, "09876543210")

    reader = await token_with_role(client, UserRole.COMPLIANCE)
    resp = await client.get(
        f"{BASE}/{customer_id}/contacts", headers=auth_header(reader)
    )
    assert resp.status_code == 200, resp.text
    served = next(c for c in resp.json()["contacts"] if c["id"] == contact["id"])

    assert served["phone"] == "+919876543210"


async def test_operations_reads_it_masked_and_never_the_ciphertext(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add_contact(client, token, customer_id, "09876543210")

    resp = await client.get(
        f"{BASE}/{customer_id}/contacts", headers=auth_header(token)
    )
    assert resp.status_code == 200, resp.text
    served = next(c for c in resp.json()["contacts"] if c["id"] == contact["id"])

    assert served["phone"] is not None
    assert not served["phone"].startswith("d1."), "the ciphertext reached a client"
    assert "•" in served["phone"]
    # Masked from the canonical number, so the last four are the real last four.
    assert served["phone"].endswith("3210")


async def test_the_write_response_is_masked_too(client: AsyncClient):
    """The 201 from the create carries the same rules as a read. A response built
    without `masked_for` would otherwise hand back the ciphertext."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    contact = await _add_contact(client, token, await make_company(), "09876543210")

    assert not (contact["phone"] or "").startswith("d1.")
    assert "•" in contact["phone"]


# ── Editing ──────────────────────────────────────────────────────────────────


async def test_editing_the_phone_seals_the_new_one(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add_contact(client, token, customer_id, "09876543210")

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact['id']}",
        headers=auth_header(token),
        json={"phone": "+91 98765 43211"},
    )
    assert resp.status_code == 200, resp.text

    stored = await _stored_phone(contact["id"])
    assert stored.startswith("d1.")
    assert "43211" not in stored

    reader = await token_with_role(client, UserRole.COMPLIANCE)
    read = await client.get(
        f"{BASE}/{customer_id}/contacts", headers=auth_header(reader)
    )
    served = next(c for c in read.json()["contacts"] if c["id"] == contact["id"])
    assert served["phone"] == "+919876543211"


async def test_editing_another_field_leaves_the_phone_sealed_once(client: AsyncClient):
    """A second sealing would store a ciphertext of a ciphertext, which no key could
    open back to a number."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add_contact(client, token, customer_id, "09876543210")
    before = await _stored_phone(contact["id"])

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact['id']}",
        headers=auth_header(token),
        json={"name": "Jane Roe"},
    )
    assert resp.status_code == 200, resp.text

    assert await _stored_phone(contact["id"]) == before


async def test_clearing_the_phone_empties_the_column(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    contact = await _add_contact(client, token, customer_id, "09876543210")

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact['id']}",
        headers=auth_header(token),
        json={"phone": None},
    )
    assert resp.status_code == 200, resp.text

    assert await _stored_phone(contact["id"]) is None
