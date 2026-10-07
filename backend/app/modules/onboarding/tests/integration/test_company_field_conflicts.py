"""Two people editing one company: a stale edit of the same field is refused.

The check is **field-level**: each edited field's value as the screen showed it
(``seen``) is compared, under the row lock, with the current one. A field someone else
changed since refuses the whole edit with 409 ``COMPANY_FIELD_CHANGED``, naming who and
when; a different field, a gauge move or an RM change on the same row does not. A
masked identifier is compared masked. Omitting ``seen`` keeps the old behaviour. There
is no version column and no ETag.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect as sa_inspect

from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.integration._compliance_support import start_review
from app.modules.onboarding.tests.integration._verification_support import BASE
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, tuple[str, str]]:
    return {
        "rm": await user_with_role(client, UserRole.OPERATIONS, email_prefix="cf-rm"),
        "rm2": await user_with_role(client, UserRole.OPERATIONS, email_prefix="cf-rm2"),
        "compliance": await user_with_role(client, UserRole.COMPLIANCE, email_prefix="cf-co"),
    }


def _pan() -> str:
    import random
    import string

    letters = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
    return f"{letters}{random.randint(0, 9999):04d}{random.choice(string.ascii_uppercase)}"


async def _company(client, token) -> dict:
    response = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": f"Field Co {uuid.uuid4().hex[:8]}", "country": "IN",
              "pan": _pan(), "industry": "Textiles"},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _patch(client, token, company_id, body):
    return await client.patch(f"{BASE}/exporters/{company_id}", json=body, headers=auth_header(token))


async def test_a_stale_edit_of_the_same_field_names_who_and_when(client, people):
    _, rm = people["rm"]
    rm2_id, rm2 = people["rm2"]
    company = await _company(client, rm)
    cid = company["customer_id"]
    first = await _patch(client, rm2, cid, {"industry": "Leather", "seen": {"industry": "Textiles"}})
    assert first.status_code == 200, first.text
    stale = await _patch(client, rm, cid, {"industry": "Spices", "seen": {"industry": "Textiles"}})
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "COMPANY_FIELD_CHANGED"
    body = stale.json()["error_context"]
    assert body["field"] == "industry"
    assert body["current"] == "Leather"
    assert body["changed_by"] == rm2_id
    assert body["changed_by_name"]
    assert body["changed_at"]
    # Nothing in the refused edit was written.
    detail = (await client.get(f"{BASE}/exporters/{cid}", headers=auth_header(rm))).json()
    assert detail["industry"] == "Leather"


async def test_a_different_field_passes_and_both_are_on_the_record(client, people):
    _, rm = people["rm"]
    _, rm2 = people["rm2"]
    company = await _company(client, rm)
    cid = company["customer_id"]
    a = await _patch(client, rm, cid, {"industry": "Leather", "seen": {"industry": "Textiles"}})
    b = await _patch(client, rm2, cid, {"year_established": 1999, "seen": {"year_established": None}})
    assert a.status_code == 200 and b.status_code == 200
    history = (
        await client.get(f"{BASE}/exporters/{cid}/history?dimension=profile", headers=auth_header(rm))
    ).json()["entries"]
    assert {e["to_value"] for e in history} >= {"industry", "year_established"}


async def test_a_masked_viewer_is_compared_masked_to_masked(client, people):
    _, rm = people["rm"]
    _, compliance = people["compliance"]
    company = await _company(client, rm)
    cid = company["customer_id"]
    masked_pan = company["pan"]
    assert "•" in masked_pan
    # The masked value the RM was shown matches; the edit itself is of another field.
    ok = await _patch(client, rm, cid, {"industry": "Jute", "seen": {"pan": masked_pan}})
    assert ok.status_code == 200, ok.text
    full = (await client.get(f"{BASE}/exporters/{cid}", headers=auth_header(compliance))).json()["pan"]
    new_pan = full[:5] + ("0000" if full[5:9] != "0000" else "1111") + full[9]
    changed = await _patch(client, compliance, cid, {"pan": new_pan, "seen": {"pan": full}})
    assert changed.status_code == 200, changed.text
    stale = await _patch(client, rm, cid, {"industry": "Rice", "seen": {"pan": masked_pan}})
    assert stale.status_code == 409
    assert "•" in stale.json()["error_context"]["current"]  # never the raw PAN to a masked viewer


async def test_omitting_seen_keeps_last_write_wins(client, people):
    _, rm = people["rm"]
    _, rm2 = people["rm2"]
    company = await _company(client, rm)
    cid = company["customer_id"]
    assert (await _patch(client, rm2, cid, {"industry": "Leather"})).status_code == 200
    assert (await _patch(client, rm, cid, {"industry": "Spices"})).status_code == 200


async def test_a_gauge_move_between_read_and_save_is_not_a_conflict(client, people):
    _, rm = people["rm"]
    company = await _company(client, rm)
    cid = company["customer_id"]
    await start_review(uuid.UUID(cid))  # moves the gauge and `updated_at`
    ok = await _patch(client, rm, cid, {"industry": "Leather", "seen": {"industry": "Textiles"}})
    assert ok.status_code == 200, ok.text


async def test_two_sessions_racing_on_one_field_leave_one_success_and_one_409(client, people):
    _, rm = people["rm"]
    _, rm2 = people["rm2"]
    company = await _company(client, rm)
    cid = company["customer_id"]
    results = await asyncio.gather(
        _patch(client, rm, cid, {"industry": "Spices", "seen": {"industry": "Textiles"}}),
        _patch(client, rm2, cid, {"industry": "Leather", "seen": {"industry": "Textiles"}}),
    )
    assert sorted(r.status_code for r in results) == [200, 409]


async def test_seen_must_name_editable_fields(client, people):
    _, rm = people["rm"]
    company = await _company(client, rm)
    bad = await _patch(client, rm, company["customer_id"], {"industry": "X", "seen": {"journey": "LEAD"}})
    assert bad.status_code == 422


def test_there_is_no_version_column():
    columns = {c.key for c in sa_inspect(ExporterProfile).columns}
    assert not {"version", "row_version", "etag"} & columns
