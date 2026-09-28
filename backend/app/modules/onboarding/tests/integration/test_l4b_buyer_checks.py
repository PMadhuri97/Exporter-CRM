"""Buyer verification — **owner: Developer 4B** (4B-5; ``docs/dev4/4b-task.md`` §5.7,
architecture §3.5 and decision 9).

* a BUYER check names a ``deal_buyer.id`` — a company id or a deal id is refused;
* the buyer's identity is snapshotted at record time and survives ``set_buyer``;
* the snapshot's registration number and tax id are masked for OPERATIONS;
* the history row lands on the deal's company with ``deal_id`` set;
* a failed buyer check leaves the company record and every company input unchanged;
* ``ComplianceInputsReader.buyer_checks`` reads it; ``company_inputs`` never does.

D17 (lead, 28 Sep 2026): a new buyer check on a HANDED_OVER or WITHDRAWN deal is
refused (409 ``DEAL_CLOSED``); checks already recorded stay readable and reviewable.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import EvidenceRef, VerificationEvidence
from app.modules.onboarding.exceptions import (
    ComplianceInputsBuyerNotFoundError,
    VerificationBuyerDealClosedError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.integration._l4b_support import (
    BASE,
    NOTE,
    deal_buyer,
    history_rows,
    insert_document,
    open_deal,
    pg,
    set_buyer,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

_IDENTITY = {
    "name": "Rotterdam Trading BV",
    "country": "NL",
    "registration_number": "KVK-12345678",
    "tax_id": "NL123456789B01",
}


async def _buyer_check(buyer_id: uuid.UUID, *, status: str = "FAILED", evidence=None):
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).trigger_verification(
            VerificationType.BUYER,
            VerificationEntityType.BUYER,
            buyer_id,
            payload={"status": status},
            actor_id="tester",
            evidence=evidence,
        )


# ── The subject is the buyer ─────────────────────────────────────────────────


async def test_a_company_id_is_not_a_buyer_subject():
    company_id, _, _ = await deal_buyer()
    with pytest.raises(ComplianceInputsBuyerNotFoundError):
        await _buyer_check(company_id)


async def test_a_deal_id_is_not_a_buyer_subject():
    _, deal_id, _ = await deal_buyer()
    with pytest.raises(ComplianceInputsBuyerNotFoundError):
        await _buyer_check(deal_id)


async def test_an_unknown_id_is_not_a_buyer_subject():
    with pytest.raises(ComplianceInputsBuyerNotFoundError) as missing:
        await _buyer_check(uuid.uuid4())
    assert missing.value.status_code == 404


# ── Snapshot ─────────────────────────────────────────────────────────────────


async def test_the_snapshot_survives_a_later_set_buyer():
    _, deal_id, buyer_id = await deal_buyer(**_IDENTITY)
    result = await _buyer_check(buyer_id)

    # DealService.set_buyer rewrites the same buyer row in place.
    assert await set_buyer(
        deal_id, name="Renamed Holdings", country="BE", registration_number="X", tax_id="Y"
    ) == buyer_id

    async with db_services.AsyncSessionLocal() as db:
        view = await VerificationService(db).get_result_view(result.id)
    assert view.result.subject_snapshot == {
        "deal_buyer_id": str(buyer_id),
        "deal_id": str(deal_id),
        **_IDENTITY,
    }


# ── History and company isolation ────────────────────────────────────────────


async def test_history_lands_on_the_deals_company_with_the_deal_id():
    company_id, deal_id, buyer_id = await deal_buyer()
    result = await _buyer_check(buyer_id)
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            result.id, reviewed_by="c1", review_status=VerificationReviewStatus.REJECTED
        )

    with pg() as cur:
        rows = history_rows(cur, company_id)
    assert [(r[0], r[2], r[5]) for r in rows] == [
        ("verification_initial", "FAILED", str(deal_id)),
        ("verification_reviewed", "REJECTED", str(deal_id)),
    ]


async def test_a_failed_buyer_check_leaves_the_company_untouched():
    company_id, _, buyer_id = await deal_buyer()
    with pg() as cur:
        cur.execute(
            "SELECT to_jsonb(p) - 'updated_at' FROM onboarding.exporter_profile p "
            "WHERE customer_id = %s",
            (str(company_id),),
        )
        (before,) = cur.fetchone()
        cur.execute(
            "SELECT updated_at FROM onboarding.exporter_profile WHERE customer_id = %s",
            (str(company_id),),
        )
        (before_updated,) = cur.fetchone()
    async with db_services.AsyncSessionLocal() as db:
        inputs_before = await ComplianceInputsService(db).company_inputs(company_id)

    result = await _buyer_check(buyer_id, status="FAILED")
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            result.id, reviewed_by="c1", review_status=VerificationReviewStatus.REJECTED
        )

    with pg() as cur:
        cur.execute(
            "SELECT to_jsonb(p) - 'updated_at', updated_at FROM onboarding.exporter_profile p "
            "WHERE customer_id = %s",
            (str(company_id),),
        )
        after, after_updated = cur.fetchone()
    assert after == before
    assert after_updated == before_updated
    async with db_services.AsyncSessionLocal() as db:
        inputs_after = await ComplianceInputsService(db).company_inputs(company_id)
    assert inputs_after == inputs_before
    assert inputs_after.verifications == ()


async def test_buyer_checks_are_read_by_buyer_id_only():
    company_id, _, buyer_id = await deal_buyer()
    result = await _buyer_check(buyer_id, status="FAILED")

    async with db_services.AsyncSessionLocal() as db:
        reader = ComplianceInputsService(db)
        checks = await reader.buyer_checks(buyer_id)
        company = await reader.company_inputs(company_id)

    assert [c.verification_result_id for c in checks] == [result.id]
    assert checks[0].entity_type == "BUYER"
    assert company.verifications == ()


# ── Evidence on a buyer check ────────────────────────────────────────────────


async def test_a_document_of_the_buyers_deal_or_its_company_is_buyer_evidence():
    company_id, deal_id, buyer_id = await deal_buyer()
    with pg() as cur:
        on_deal = insert_document(cur, deal_id=deal_id)
        on_company = insert_document(cur, company_id=company_id)
    evidence = VerificationEvidence(
        refs=(
            EvidenceRef(type="document", ref=str(on_deal)),
            EvidenceRef(type="document", ref=str(on_company)),
        )
    )
    result = await _buyer_check(buyer_id, status="PASSED", evidence=evidence)
    async with db_services.AsyncSessionLocal() as db:
        [read] = await ComplianceInputsService(db).buyer_checks(buyer_id)
    assert read.evidence_document_ids == (on_deal, on_company)
    assert result.status.value == "PASSED"


async def test_a_document_of_another_deal_is_not_buyer_evidence():
    company_id, _, buyer_id = await deal_buyer()
    other_deal = await open_deal(company_id, reference="Another shipment")
    with pg() as cur:
        foreign = insert_document(cur, deal_id=other_deal)
    with pytest.raises(ValidationError, match="does not belong"):
        await _buyer_check(
            buyer_id,
            status="PASSED",
            evidence=VerificationEvidence(refs=(EvidenceRef(type="document", ref=str(foreign)),)),
        )


@pytest.mark.parametrize("scan_status", ["PENDING_SCAN", "QUARANTINED", "SCAN_FAILED"])
async def test_a_buyer_document_that_is_not_available_is_not_evidence(scan_status):
    """The buyer's own deal document still has to be AVAILABLE (storage §4)."""
    _, deal_id, buyer_id = await deal_buyer()
    with pg() as cur:
        on_deal = insert_document(cur, deal_id=deal_id, scan_status=scan_status)
    with pytest.raises(ValidationError, match=f"is {scan_status}"):
        await _buyer_check(
            buyer_id,
            status="PASSED",
            evidence=VerificationEvidence(refs=(EvidenceRef(type="document", ref=str(on_deal)),)),
        )
    async with db_services.AsyncSessionLocal() as db:
        assert await ComplianceInputsService(db).buyer_checks(buyer_id) == ()


# ── API and masking ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


async def test_the_api_records_a_buyer_check_and_masks_the_snapshot_per_role(client, tokens):
    _, _, buyer_id = await deal_buyer(**_IDENTITY)
    created = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "BUYER",
            "entity_type": "BUYER",
            "entity_reference": str(buyer_id),
            "payload": {"status": "PASSED"},
            "evidence_note": NOTE.note,
        },
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert created.status_code == 201, created.text
    assert created.json()["subject_snapshot"]["tax_id"] == _IDENTITY["tax_id"]

    url = f"{BASE}/verifications?entity_type=BUYER&entity_reference={buyer_id}"
    for role, revealed in (
        (UserRole.COMPLIANCE, True),
        (UserRole.ADMIN, True),
        (UserRole.OPERATIONS, False),
    ):
        resp = await client.get(url, headers=auth_header(tokens[role]))
        assert resp.status_code == 200, (role, resp.text)
        snapshot = resp.json()["results"][0]["subject_snapshot"]
        assert snapshot["name"] == _IDENTITY["name"]
        assert snapshot["country"] == "NL"
        if revealed:
            assert snapshot["tax_id"] == _IDENTITY["tax_id"]
            assert snapshot["registration_number"] == _IDENTITY["registration_number"]
        else:
            assert snapshot["tax_id"] != _IDENTITY["tax_id"]
            assert snapshot["tax_id"].endswith(_IDENTITY["tax_id"][-4:])
            assert "•" in snapshot["registration_number"]


@pytest.mark.parametrize("which", ["company", "deal"])
async def test_the_api_refuses_a_company_or_deal_id_as_a_buyer(client, tokens, which):
    company_id, deal_id, _ = await deal_buyer()
    reference = company_id if which == "company" else deal_id
    resp = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "BUYER",
            "entity_type": "BUYER",
            "entity_reference": str(reference),
            "payload": {"status": "FAILED"},
        },
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "DEAL_BUYER_NOT_FOUND"


# ── D17: terminal deals ──────────────────────────────────────────────────────


async def _withdraw(deal_id: uuid.UUID) -> None:
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="Buyer cancelled", actor_id="tester"
        )


def _mark_handed_over(deal_id: uuid.UUID) -> None:
    """Straight to the stage: the handover's own prerequisites are Dev3's, not what
    this rule is about."""
    with pg() as cur:
        cur.execute(
            "UPDATE onboarding.deal SET stage = 'HANDED_OVER', handed_over_at = now() "
            "WHERE id = %s",
            (str(deal_id),),
        )


@pytest.mark.parametrize("stage", ["WITHDRAWN", "HANDED_OVER"])
async def test_a_new_buyer_check_on_a_terminal_deal_is_refused(stage):
    _, deal_id, buyer_id = await deal_buyer()
    if stage == "WITHDRAWN":
        await _withdraw(deal_id)
    else:
        _mark_handed_over(deal_id)

    with pytest.raises(VerificationBuyerDealClosedError) as closed:
        await _buyer_check(buyer_id)
    assert closed.value.status_code == 409
    assert closed.value.stage == stage
    async with db_services.AsyncSessionLocal() as db:
        assert await ComplianceInputsService(db).buyer_checks(buyer_id) == ()


async def test_an_existing_check_stays_readable_and_reviewable_after_the_deal_closes():
    company_id, deal_id, buyer_id = await deal_buyer()
    result = await _buyer_check(buyer_id, status="FAILED")
    await _withdraw(deal_id)

    async with db_services.AsyncSessionLocal() as db:
        review = await VerificationService(db).record_review(
            result.id, reviewed_by="c1", review_status=VerificationReviewStatus.REJECTED
        )
    async with db_services.AsyncSessionLocal() as db:
        [read] = await ComplianceInputsService(db).buyer_checks(buyer_id)
    assert read.latest_review_id == review.id
    with pg() as cur:
        assert [r[0] for r in history_rows(cur, company_id)] == [
            "verification_initial",
            "verification_reviewed",
        ]


async def test_the_api_answers_409_deal_closed(client, tokens):
    _, deal_id, buyer_id = await deal_buyer()
    await _withdraw(deal_id)
    resp = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "BUYER",
            "entity_type": "BUYER",
            "entity_reference": str(buyer_id),
            "payload": {"status": "FAILED"},
        },
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "DEAL_CLOSED"
