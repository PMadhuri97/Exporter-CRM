"""Honest placeholders and provenance — **owner: Developer 4B** (4B-6;
``docs/dev4/4b-task.md`` §5.4, §5.9, architecture §7.6's gate).

* the bank response says no provider feed is connected, and carries no findings;
* existing placeholder rows are flagged (``is_placeholder``), never deleted;
* no route creates a PENDING result nothing could resolve — manual or stub;
* provenance is labelled: manual is a person, the RXIL stub is a STUB;
* the stored provider never changes after write.

D7 (lead, 28 Sep 2026): the manual route accepts ``provider="manual"`` only; ``rxil``
is refused there and reserved for the future RXIL intake path.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._l4b_support import BASE, insert_result, pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def token(client: AsyncClient) -> str:
    return await token_with_role(client, UserRole.COMPLIANCE)


async def _list(client, token, entity_type: str, reference: uuid.UUID) -> list[dict]:
    resp = await client.get(
        f"{BASE}/verifications",
        params={"entity_type": entity_type, "entity_reference": str(reference)},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


# ── Bank activity ────────────────────────────────────────────────────────────


async def test_the_bank_panel_says_no_provider_feed_is_connected(client, token):
    company_id = await make_company()
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/bank-activity", headers=auth_header(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider_feed_connected"] is False
    assert body["provider_feed_status"] == "NOT_CONNECTED"
    assert "not connected" in body["provider_feed_message"].lower() or (
        "no bank-monitoring provider feed" in body["provider_feed_message"].lower()
    )
    assert body["findings"] == []
    assert body["open_findings"] == 0
    assert body["connected_accounts"] == 0


# ── Placeholders ─────────────────────────────────────────────────────────────


async def test_an_existing_placeholder_row_is_flagged_not_deleted(client, token):
    company_id = await make_company()
    with pg() as cur:
        placeholder = insert_result(
            cur,
            entity_type="EXPORTER",
            entity_reference=company_id,
            status="PENDING",
            normalized_result={"stub": True, "message": "Provider integration not configured."},
        )
        real = insert_result(
            cur,
            entity_type="EXPORTER",
            entity_reference=company_id,
            status="PENDING",
            provider_reference="vendor-ref-1",
            normalized_result={"stub": True},
        )

    results = {r["id"]: r for r in await _list(client, token, "EXPORTER", company_id)}
    assert results[str(placeholder)]["is_placeholder"] is True
    assert results[str(real)]["is_placeholder"] is False  # it has a provider reference

    single = await client.get(f"{BASE}/verifications/{placeholder}", headers=auth_header(token))
    assert single.json()["is_placeholder"] is True


@pytest.mark.parametrize("provider", ["manual", "rxil"])
async def test_no_route_creates_a_pending_result_that_could_never_resolve(client, token, provider):
    company_id = await make_company()
    resp = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "KYB",
            "entity_type": "EXPORTER",
            "entity_reference": str(company_id),
            "provider": provider,
            "payload": {"status": "PENDING", "normalized_result": {"stub": True}},
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
    assert await _list(client, token, "EXPORTER", company_id) == []


# ── Provenance ───────────────────────────────────────────────────────────────


async def test_a_manual_result_is_labelled_manual(client, token):
    company_id = await make_company()
    resp = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "KYB",
            "entity_type": "EXPORTER",
            "entity_reference": str(company_id),
            "payload": {"status": "FAILED"},
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    assert (resp.json()["provider"], resp.json()["provenance"]) == ("manual", "MANUAL")


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE, UserRole.ADMIN])
async def test_the_manual_route_refuses_provider_rxil_for_every_role(client, token, role):
    """D7: nobody records a result *as RXIL's* through the manual route."""
    company_id = await make_company()
    resp = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "KYB",
            "entity_type": "EXPORTER",
            "entity_reference": str(company_id),
            "provider": "rxil",
            "payload": {"status": "PASSED"},
            "evidence_note": "x",
        },
        headers=auth_header(await token_with_role(client, role)),
    )
    assert resp.status_code == 422, resp.text
    assert "provider" in resp.text
    assert await _list(client, token, "EXPORTER", company_id) == []


async def test_a_stub_result_is_labelled_stub_and_its_provider_never_changes(client, token):
    """The stub is still reachable from code (not from the manual route, D7); a row it
    writes must never pass for RXIL's own answer."""
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        result = await VerificationService(db).trigger_verification(
            VerificationType.KYB,
            VerificationEntityType.EXPORTER,
            company_id,
            provider="rxil",
            payload={"status": "PASSED"},
            actor_id="tester",
        )
    result_id = str(result.id)
    first_read = await client.get(f"{BASE}/verifications/{result_id}", headers=auth_header(token))
    assert (first_read.json()["provider"], first_read.json()["provenance"]) == (
        "rxil_stub",
        "STUB",
    )

    # Reviewing the result, and reading it back every way, never rewrites the provider.
    await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"review_status": "ACCEPTED"},
        headers=auth_header(token),
    )
    read = await client.get(f"{BASE}/verifications/{result_id}", headers=auth_header(token))
    [listed] = await _list(client, token, "EXPORTER", company_id)
    with pg() as cur:
        cur.execute(
            "SELECT provider FROM onboarding.verification_result WHERE id = %s", (result_id,)
        )
        stored = cur.fetchone()[0]
    assert read.json()["provider"] == listed["provider"] == stored == "rxil_stub"


async def test_a_row_the_stub_wrote_before_4b6_is_still_labelled_stub(client, token):
    company_id = await make_company()
    with pg() as cur:
        legacy = insert_result(
            cur, entity_type="EXPORTER", entity_reference=company_id, provider="RXIL"
        )
    [row] = await _list(client, token, "EXPORTER", company_id)
    assert row["id"] == str(legacy)
    assert (row["provider"], row["provenance"]) == ("RXIL", "STUB")
