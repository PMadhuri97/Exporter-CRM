"""Payment terms, a company's default, and a deal's value, currency and term.

The walk-through: a customer whose default is "DA 90 days" opens a deal that shows DA
90 days; changing it to "LC at sight" asks for a reason, and the reason is in History.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _terms(client, token) -> dict[str, dict]:
    resp = await client.get(f"{BASE}/settings/payment-terms", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    return {term["code"]: term for term in resp.json()["terms"]}


async def _set_default(client, token, company_id, term_id):
    resp = await client.put(
        f"{BASE}/exporters/{company_id}/default-payment-term",
        headers=auth_header(token),
        json={"payment_term_id": term_id},
    )
    assert resp.status_code == 200, resp.text


async def _open(client, token, company_id, **body) -> dict:
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/deals",
        headers=auth_header(token),
        json={"reference": f"Deal {uuid.uuid4().hex[:6]}", **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_deal_takes_the_company_default_and_a_change_needs_a_reason(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    terms = await _terms(client, token)
    company_id = await make_prospect()
    await _set_default(client, token, company_id, terms["DA_90"]["id"])

    deal = await _open(client, token, company_id)
    assert deal["payment_term"]["label"] == "DA 90 days"
    assert deal["company_default_payment_term"]["code"] == "DA_90"

    refused = await client.patch(
        f"{BASE}/deals/{deal['id']}/terms",
        headers=auth_header(token),
        json={"payment_term_id": terms["LC_SIGHT"]["id"]},
    )
    assert refused.status_code == 422, refused.text

    changed = await client.patch(
        f"{BASE}/deals/{deal['id']}/terms",
        headers=auth_header(token),
        json={
            "payment_term_id": terms["LC_SIGHT"]["id"],
            "payment_term_override_reason": "First shipment to a new buyer",
            "value_amount": "125000.50",
            "currency": "usd",
        },
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["payment_term"]["code"] == "LC_SIGHT"
    assert body["payment_term_override_reason"] == "First shipment to a new buyer"
    assert (body["value_amount"], body["currency"]) == ("125000.50", "USD")

    history = await client.get(
        f"{BASE}/deals/{deal['id']}/history", headers=auth_header(token)
    )
    [row] = [e for e in history.json()["entries"] if e["event_type"] == "deal_terms_changed"]
    assert row["reason"] == "First shipment to a new buyer"


async def test_going_back_to_the_default_needs_no_reason_and_clears_it(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    terms = await _terms(client, token)
    company_id = await make_prospect()
    await _set_default(client, token, company_id, terms["DA_90"]["id"])
    deal = await _open(
        client, token, company_id,
        payment_term_id=terms["ADVANCE"]["id"], payment_term_override_reason="New buyer",
    )
    assert deal["payment_term"]["code"] == "ADVANCE"

    back = await client.patch(
        f"{BASE}/deals/{deal['id']}/terms",
        headers=auth_header(token),
        json={"payment_term_id": terms["DA_90"]["id"]},
    )
    assert back.status_code == 200, back.text
    assert back.json()["payment_term_override_reason"] is None


async def test_a_value_needs_its_currency(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    deal = await _open(client, token, await make_prospect())
    refused = await client.patch(
        f"{BASE}/deals/{deal['id']}/terms", headers=auth_header(token), json={"value_amount": "10"}
    )
    assert refused.status_code == 422, refused.text


async def test_a_retired_term_stays_on_old_deals_but_is_no_longer_offered(client: AsyncClient):
    ops = await token_with_role(client, UserRole.OPERATIONS)
    admin = await token_with_role(client, UserRole.ADMIN)
    code = f"T_{uuid.uuid4().hex[:6].upper()}"
    added = await client.post(
        f"{BASE}/settings/payment-terms",
        headers=auth_header(admin),
        json={"code": code, "label": "DA 120 days", "kind": "DA", "days": 120},
    )
    assert added.status_code == 201, added.text
    company_id = await make_prospect()
    deal = await _open(
        client, ops, company_id,
        payment_term_id=added.json()["id"], payment_term_override_reason=None,
    )
    assert deal["payment_term"]["label"] == "DA 120 days"

    retired = await client.patch(
        f"{BASE}/settings/payment-terms/{code}", headers=auth_header(admin), json={"active": False}
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["version"] == 2

    still = await client.get(f"{BASE}/deals/{deal['id']}", headers=auth_header(ops))
    assert still.json()["payment_term"]["label"] == "DA 120 days"
    refused = await client.patch(
        f"{BASE}/deals/{(await _open(client, ops, company_id))['id']}/terms",
        headers=auth_header(ops),
        json={"payment_term_id": added.json()["id"]},
    )
    assert refused.status_code == 422, refused.text


async def test_an_edit_writes_a_new_version_and_days_must_fit_the_kind(client: AsyncClient):
    admin = await token_with_role(client, UserRole.ADMIN)
    code = f"T_{uuid.uuid4().hex[:6].upper()}"
    bad = await client.post(
        f"{BASE}/settings/payment-terms",
        headers=auth_header(admin),
        json={"code": code, "label": "DA", "kind": "DA"},
    )
    assert bad.status_code == 422, bad.text
    await client.post(
        f"{BASE}/settings/payment-terms",
        headers=auth_header(admin),
        json={"code": code, "label": "Advance 50%", "kind": "ADVANCE"},
    )
    revised = await client.patch(
        f"{BASE}/settings/payment-terms/{code}",
        headers=auth_header(admin),
        json={"label": "Advance (half up front)"},
    )
    assert revised.json()["version"] == 2
    listing = await client.get(f"{BASE}/settings/payment-terms", headers=auth_header(admin))
    versions = [t for t in listing.json()["history"] if t["code"] == code]
    assert [(t["version"], t["is_current"]) for t in versions] == [(2, True), (1, False)]
    assert listing.json()["can_edit"] is True


async def test_only_settings_managers_change_terms(client: AsyncClient):
    ops = await token_with_role(client, UserRole.OPERATIONS)
    refused = await client.post(
        f"{BASE}/settings/payment-terms",
        headers=auth_header(ops),
        json={"code": "X1", "label": "x", "kind": "ADVANCE"},
    )
    assert refused.status_code == 403
    assert (await client.get(f"{BASE}/settings/payment-terms", headers=auth_header(ops))).json()[
        "can_edit"
    ] is False


async def test_the_all_deals_list_shows_the_value(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    company_id = await make_prospect()
    deal = await _open(client, token, company_id, value_amount="5000", currency="EUR")
    listing = await client.get(
        f"{BASE}/deals", headers=auth_header(token), params={"company_id": str(company_id)}
    )
    [row] = [d for d in listing.json()["deals"] if d["id"] == deal["id"]]
    assert (row["value_amount"], row["currency"]) == ("5000.00", "EUR")


def test_a_closed_deals_value_does_not_change():
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM onboarding.deal WHERE stage IN ('HANDED_OVER', 'WITHDRAWN') LIMIT 1"
            )
            row = cursor.fetchone()
            if row is None:
                pytest.skip("no closed deal in this database")
            with pytest.raises(psycopg2.errors.RaiseException):
                cursor.execute(
                    "UPDATE onboarding.deal SET value_amount = 1, currency = 'INR' WHERE id = %s",
                    (row[0],),
                )
    finally:
        conn.rollback()
        conn.close()
