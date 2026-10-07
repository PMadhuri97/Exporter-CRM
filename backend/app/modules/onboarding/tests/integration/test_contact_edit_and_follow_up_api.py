"""The contact edit route and the follow-up due-date rule, over HTTP.

The service tests (`test_exporter_contact_activity_service.py`) prove what a write
does to the rows. These prove what the API answers: which bodies are refused before
the service sees them, and that a refusal is a 4xx a screen can show rather than a
500.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding/exporters"


async def _company_with_contact(client: AsyncClient, token: str, **contact) -> tuple:
    customer_id = await make_company()
    resp = await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": "Jane Doe", **contact},
    )
    assert resp.status_code == 201, resp.text
    return customer_id, resp.json()["id"]


# ── Editing a contact ─────────────────────────────────────────────────────────


async def test_edit_trims_the_name(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _company_with_contact(client, token)

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact_id}",
        headers=auth_header(token),
        json={"name": "  Jane Smith  "},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Jane Smith"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"name": None}, id="name-null"),
        # Null alongside a real change used to be dropped silently, so the role
        # changed and the request reported success for a name it never touched.
        pytest.param({"name": None, "role": "CFO"}, id="name-null-with-another-field"),
        pytest.param({"name": "   "}, id="name-blank"),
        pytest.param({"is_primary": None}, id="is-primary-null"),
        pytest.param({}, id="empty-body"),
        pytest.param({"nickname": "JD"}, id="unknown-field"),
    ],
)
async def test_edit_refuses_a_body_it_cannot_apply(client: AsyncClient, body: dict):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _company_with_contact(client, token, role="CEO")

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact_id}",
        headers=auth_header(token),
        json=body,
    )
    assert resp.status_code == 422, resp.text

    # Refused whole: nothing in the body was applied.
    listed = await client.get(f"{BASE}/{customer_id}/contacts", headers=auth_header(token))
    [contact] = listed.json()["contacts"]
    assert contact["name"] == "Jane Doe"
    assert contact["role"] == "CEO"


async def test_edit_of_an_unknown_contact_is_404(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, _ = await _company_with_contact(client, token)

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{uuid.uuid4()}",
        headers=auth_header(token),
        json={"role": "CFO"},
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "EXPORTER_CONTACT_NOT_FOUND"


async def test_edit_through_another_company_is_404(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    _, theirs = await _company_with_contact(client, token)
    mine = await make_company()

    resp = await client.patch(
        f"{BASE}/{mine}/contacts/{theirs}",
        headers=auth_header(token),
        json={"role": "CFO"},
    )

    assert resp.status_code == 404, resp.text


async def test_edit_answers_operations_with_the_contact_masked(client: AsyncClient):
    """The edit answers in the same shape the list does: an OPERATIONS caller that
    changes the role gets the email back masked, not in full."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id, contact_id = await _company_with_contact(
        client, token, email="jane.doe@example.com"
    )

    resp = await client.patch(
        f"{BASE}/{customer_id}/contacts/{contact_id}",
        headers=auth_header(token),
        json={"role": "CFO"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] != "jane.doe@example.com"


async def test_adding_a_contact_with_a_blank_name_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()

    resp = await client.post(
        f"{BASE}/{customer_id}/contacts",
        headers=auth_header(token),
        json={"name": "   "},
    )

    assert resp.status_code == 422, resp.text


# ── A follow-up's due date ────────────────────────────────────────────────────


async def test_a_due_date_without_a_timezone_is_422_not_500(client: AsyncClient):
    """`2030-01-01T10:00:00` names no moment until an offset says where. The service
    compares it with an aware "now", so letting it through was a 500."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    naive = (datetime.now(UTC) + timedelta(days=3)).replace(tzinfo=None)

    resp = await client.post(
        f"{BASE}/{customer_id}/activities",
        headers=auth_header(token),
        json={
            "activity_type": "FOLLOW_UP",
            "subject": "Call back",
            "due_at": naive.isoformat(timespec="seconds"),
        },
    )

    assert resp.status_code == 422, resp.text


async def test_a_due_date_in_the_past_is_refused_in_words_a_person_can_read(
    client: AsyncClient,
):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)

    resp = await client.post(
        f"{BASE}/{customer_id}/activities",
        headers=auth_header(token),
        json={
            "activity_type": "FOLLOW_UP",
            "subject": "Call back",
            "due_at": an_hour_ago.isoformat(),
        },
    )

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error_code"] == "ACTIVITY_DUE_IN_PAST"
    # The screen shows this message as is, so it carries no ids or raw timestamps.
    assert str(customer_id) not in body["human_readable_message"]
    assert "past" in body["human_readable_message"]


async def test_a_due_date_with_an_offset_in_the_future_is_accepted(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    customer_id = await make_company()
    ist = timezone(timedelta(hours=5, minutes=30))
    tomorrow_in_india = (datetime.now(UTC) + timedelta(days=1)).astimezone(ist)

    resp = await client.post(
        f"{BASE}/{customer_id}/activities",
        headers=auth_header(token),
        json={
            "activity_type": "FOLLOW_UP",
            "subject": "Call back",
            "due_at": tomorrow_in_india.isoformat(),
        },
    )

    assert resp.status_code == 201, resp.text
