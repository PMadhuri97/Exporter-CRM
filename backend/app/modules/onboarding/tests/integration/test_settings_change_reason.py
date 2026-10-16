"""No live rule changes without a reason.

Qualification criteria, deal required documents, payment terms and sanctions lists are
changed by writing a new version. Every one of those writes must carry
``change_reason`` — a ticket number or a real explanation — or it is refused with
nothing written; a valid reason is kept on the version and read back with it.

The success paths use their own throwaway codes and keys, so nothing here changes a
rule another test depends on. The required-documents rule is global (every deal's
handover reads it), so only its refusal is exercised here; ``test_deal_required_documents``
covers its writes, with a reason, and puts the rule back after itself.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
REASON = "CHG-1042: agreed at the change advisory board"

#: A body without a reason, and two whose reason says nothing a reviewer could use.
MISSING_OR_VAGUE = [
    pytest.param({}, id="missing"),
    pytest.param({"change_reason": "   "}, id="blank"),
    pytest.param({"change_reason": "test"}, id="vague"),
]


def _code() -> str:
    return f"T_{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
async def admin(client: AsyncClient) -> dict[str, str]:
    return auth_header(await token_with_role(client, UserRole.ADMIN))


# ── Refused without a reason, and nothing is written ─────────────────────────


@pytest.mark.parametrize("reason", MISSING_OR_VAGUE)
async def test_a_payment_term_is_not_added_without_a_reason(
    client: AsyncClient, admin: dict[str, str], reason: dict
):
    code = _code()
    resp = await client.post(
        f"{BASE}/settings/payment-terms",
        headers=admin,
        json={"code": code, "label": "Advance", "kind": "ADVANCE", **reason},
    )
    assert resp.status_code == 422, resp.text
    assert "change_reason" in resp.text

    listing = await client.get(f"{BASE}/settings/payment-terms", headers=admin)
    assert code not in {term["code"] for term in listing.json()["history"]}


@pytest.mark.parametrize("reason", MISSING_OR_VAGUE)
async def test_a_payment_term_is_not_retired_without_a_reason(
    client: AsyncClient, admin: dict[str, str], reason: dict
):
    code = _code()
    added = await client.post(
        f"{BASE}/settings/payment-terms",
        headers=admin,
        json={"code": code, "label": "Advance", "kind": "ADVANCE", "change_reason": REASON},
    )
    assert added.status_code == 201, added.text

    # The one-click change the reason exists for: retiring a term in use.
    resp = await client.patch(
        f"{BASE}/settings/payment-terms/{code}", headers=admin, json={"active": False, **reason}
    )
    assert resp.status_code == 422, resp.text

    listing = await client.get(f"{BASE}/settings/payment-terms", headers=admin)
    [current] = [term for term in listing.json()["terms"] if term["code"] == code]
    assert (current["version"], current["active"]) == (1, True)


@pytest.mark.parametrize("reason", MISSING_OR_VAGUE)
async def test_a_sanctions_list_is_not_changed_without_a_reason(
    client: AsyncClient, admin: dict[str, str], reason: dict
):
    code = _code()
    refused_add = await client.post(
        f"{BASE}/settings/sanctions-lists",
        headers=admin,
        json={"code": code, "name": "Test list", "list_version_date": "2026-10-01", **reason},
    )
    assert refused_add.status_code == 422, refused_add.text

    await client.post(
        f"{BASE}/settings/sanctions-lists",
        headers=admin,
        json={
            "code": code,
            "name": "Test list",
            "list_version_date": "2026-10-01",
            "change_reason": REASON,
        },
    )
    refused_revise = await client.patch(
        f"{BASE}/settings/sanctions-lists/{code}", headers=admin, json={"active": False, **reason}
    )
    assert refused_revise.status_code == 422, refused_revise.text

    listing = await client.get(f"{BASE}/settings/sanctions-lists", headers=admin)
    [current] = [row for row in listing.json()["lists"] if row["code"] == code]
    assert (current["version"], current["active"]) == (1, True)
    await client.patch(  # Out of use again, so no screening is asked to cover it.
        f"{BASE}/settings/sanctions-lists/{code}",
        headers=admin,
        json={"active": False, "change_reason": REASON},
    )


@pytest.mark.parametrize("reason", MISSING_OR_VAGUE)
async def test_a_criterion_is_not_added_or_versioned_without_a_reason(
    client: AsyncClient, admin: dict[str, str], reason: dict
):
    key = f"test_{uuid.uuid4().hex[:12]}"
    definition = {"label": "Throwaway", "kind": "YES_NO", "required": False, "active": False}
    refused_create = await client.post(
        f"{BASE}/qualification/criteria", headers=admin, json={"key": key, **definition, **reason}
    )
    assert refused_create.status_code == 422, refused_create.text
    missing = await client.get(f"{BASE}/qualification/criteria/{key}/versions", headers=admin)
    assert missing.status_code == 404, missing.text

    await client.post(
        f"{BASE}/qualification/criteria",
        headers=admin,
        json={"key": key, **definition, "change_reason": REASON},
    )
    refused_version = await client.post(
        f"{BASE}/qualification/criteria/{key}/versions",
        headers=admin,
        json={**definition, "label": "Renamed", **reason},
    )
    assert refused_version.status_code == 422, refused_version.text
    versions = await client.get(f"{BASE}/qualification/criteria/{key}/versions", headers=admin)
    assert [c["version"] for c in versions.json()["criteria"]] == [1]


@pytest.mark.parametrize("reason", MISSING_OR_VAGUE)
async def test_a_required_document_is_not_changed_without_a_reason(
    client: AsyncClient, admin: dict[str, str], reason: dict
):
    before = await client.get(f"{BASE}/settings/deal-required-documents", headers=admin)
    resp = await client.post(
        f"{BASE}/settings/deal-required-documents",
        headers=admin,
        json={"category": "INSURANCE", **reason},
    )
    assert resp.status_code == 422, resp.text
    after = await client.get(f"{BASE}/settings/deal-required-documents", headers=admin)
    assert len(after.json()["history"]) == len(before.json()["history"])


# ── A valid reason is kept on the version it wrote ───────────────────────────


async def test_every_version_keeps_the_reason_it_was_written_with(
    client: AsyncClient, admin: dict[str, str]
):
    code = _code()
    added = await client.post(
        f"{BASE}/settings/payment-terms",
        headers=admin,
        json={"code": code, "label": "Advance", "kind": "ADVANCE", "change_reason": REASON},
    )
    retired = await client.patch(
        f"{BASE}/settings/payment-terms/{code}",
        headers=admin,
        # Whitespace is tidied; the words are kept as written.
        json={"active": False, "change_reason": "  Replaced by   ADVANCE_50 for all buyers "},
    )
    assert added.json()["change_reason"] == REASON
    assert retired.json()["change_reason"] == "Replaced by ADVANCE_50 for all buyers"

    listing = await client.get(f"{BASE}/settings/payment-terms", headers=admin)
    history = [term for term in listing.json()["history"] if term["code"] == code]
    assert [(t["version"], t["change_reason"]) for t in history] == [
        (2, "Replaced by ADVANCE_50 for all buyers"),
        (1, REASON),
    ]
    assert all(t["created_by"] and t["created_at"] for t in history)

    key = f"test_{uuid.uuid4().hex[:12]}"
    criterion = await client.post(
        f"{BASE}/qualification/criteria",
        headers=admin,
        json={
            "key": key,
            "label": "Throwaway",
            "kind": "YES_NO",
            "required": False,
            "active": False,
            "change_reason": "INC0012345",
        },
    )
    assert criterion.status_code == 201, criterion.text
    versions = await client.get(f"{BASE}/qualification/criteria/{key}/versions", headers=admin)
    assert versions.json()["criteria"][0]["change_reason"] == "INC0012345"
