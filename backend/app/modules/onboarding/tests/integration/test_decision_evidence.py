"""A decision's evidence, resolved, and the screening checklist going from 8 items to 7
(``rules_version``).

A decision pins ids; ``GET …/decisions/{id}/evidence`` resolves each into what a
reviewer needs: the verification result with the review the decision rested on, the
exact screening answer, the document. Every pinned id on a sample ``CLEAR`` resolves;
a decision taken under the eight-item rules still shows its website row; nothing in
the shapes is an identifier (masking for OPERATIONS; DEVELOPER refused).
"""

from __future__ import annotations

import json
import random
import string
import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
)
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_RULES_V1,
    CLEAR_RULES_V2,
    CLEAR_RULES_V3,
    CURRENT_CLEAR_RULES,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import EvidenceRef, VerificationEvidence
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import record_required_checks
from app.modules.onboarding.tests.integration._compliance_support import (
    MAKER,
    answer_screening,
    clear,
    start_review,
)
from app.modules.onboarding.tests.integration._verification_support import (
    BASE,
    exporter_result,
    insert_document,
    pg,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

def _pan() -> str:
    """A fresh, well-formed PAN (unique per company)."""
    letters = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
    return f"{letters}{random.randint(0, 9999):04d}{random.choice(string.ascii_uppercase)}"


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


async def _sample_clear(client: AsyncClient, tokens) -> tuple[str, dict]:
    """A company with identifiers, a document, a reviewed KYB result, AML and sanctions
    results and seven PASSED answers (one with document evidence), cleared by a
    maker and a checker. Returns
    ``(company_id, clearing decision)``."""
    created = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "name": f"Evidence Co {uuid.uuid4().hex[:6]}",
            "country": "IN",
            "pan": _pan(),
        },
        headers={
            **auth_header(tokens[UserRole.COMPLIANCE]),
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert created.status_code == 201, created.text
    company_id = uuid.UUID(created.json()["customer_id"])
    with pg() as cursor:
        document_id = insert_document(cursor, company_id=company_id)
    evidence = VerificationEvidence(refs=(EvidenceRef(type="document", ref=str(document_id)),))
    result = await exporter_result(company_id, verification_type=VerificationType.KYB)
    async with db_services.AsyncSessionLocal() as db:
        review = await VerificationService(db).record_review(
            result.id, reviewed_by=MAKER.user_id, review_status=VerificationReviewStatus.ACCEPTED
        )
    await answer_screening(company_id, keys=SCREENING_CATALOGUE[:1], evidence=evidence)
    await answer_screening(company_id, keys=SCREENING_CATALOGUE[1:])
    await record_required_checks(company_id, types=("AML", "SANCTIONS"))
    await start_review(company_id)
    decision = await clear(company_id)
    return str(company_id), {
        "id": str(decision.id),
        "document_id": str(document_id),
        "result_id": str(result.id),
        "review_id": str(review.id),
    }


async def _evidence(client, tokens, company_id, decision_id, role=UserRole.COMPLIANCE):
    return await client.get(
        f"{BASE}/exporters/{company_id}/background-check/decisions/{decision_id}/evidence",
        headers=auth_header(tokens[role]),
    )


async def test_every_pinned_id_on_a_clear_resolves(client: AsyncClient, tokens):
    company_id, pinned = await _sample_clear(client, tokens)
    resp = await _evidence(client, tokens, company_id, pinned["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision_id"] == pinned["id"] and body["to_value"] == "CLEAR"
    assert body["rules_version"] == CLEAR_RULES_V3
    assert body["cycle_number"] == 1

    kinds = [item["kind"] for item in body["items"]]
    assert kinds.count("SCREENING_ITEM") == len(SCREENING_CATALOGUE) == 7
    assert kinds.count("VERIFICATION_RESULT") == 3 and kinds.count("DOCUMENT") == 1
    # Every pinned id resolved: exactly the detail for its kind, never an empty item.
    for item in body["items"]:
        details = {"VERIFICATION_RESULT": "verification", "SCREENING_ITEM": "screening_item",
                   "DOCUMENT": "document"}
        for kind, key in details.items():
            assert (item[key] is not None) == (item["kind"] == kind), item

    verifications = [i["verification"] for i in body["items"] if i["verification"]]
    assert {v["verification_type"] for v in verifications} == {"KYB", "AML", "SANCTIONS"}
    [verification] = [v for v in verifications if v["verification_type"] == "KYB"]
    assert verification["verification_result_id"] == pinned["result_id"]
    assert verification["verification_type"] == "KYB"
    assert verification["status"] == "PASSED" and verification["provenance"] == "MANUAL"
    assert verification["recorded_by"] == "tester"  # the actor of its history row
    assert verification["evidence_note"]
    assert verification["pinned_review"]["id"] == pinned["review_id"]
    assert verification["pinned_review"]["review_status"] == "ACCEPTED"
    assert verification["review_superseded"] is False

    screening = {i["screening_item"]["item_key"]: i["screening_item"] for i in body["items"]
                 if i["screening_item"]}
    first = screening[SCREENING_CATALOGUE[0]]
    assert first["status"] == "PASSED" and first["retired"] is False
    assert first["label"] and first["reviewed_by"] == MAKER.user_id
    assert first["evidence_refs"] == [{"type": "document", "ref": pinned["document_id"]}]

    [document] = [i["document"] for i in body["items"] if i["document"]]
    assert document["crm_document_id"] == pinned["document_id"]
    assert document["scan_status"] == "AVAILABLE" and document["is_downloadable"] is True


async def test_a_later_review_shows_the_pinned_one_as_superseded(client, tokens):
    company_id, pinned = await _sample_clear(client, tokens)
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            uuid.UUID(pinned["result_id"]),
            reviewed_by="another-officer",
            review_status=VerificationReviewStatus.ESCALATED,
            note="New adverse media",
            supersedes_review_id=uuid.UUID(pinned["review_id"]),
        )
    body = (await _evidence(client, tokens, company_id, pinned["id"])).json()
    [verification] = [
        i["verification"] for i in body["items"]
        if i["verification"] and i["verification"]["verification_result_id"] == pinned["result_id"]
    ]
    # What the decision rested on is unchanged; the reader is told it has moved on.
    assert verification["pinned_review"]["id"] == pinned["review_id"]
    assert verification["review_superseded"] is True


async def test_a_legacy_eight_item_decision_still_shows_its_website_row(client, tokens):
    """Old decisions keep their pinned `website-reviewed` answer and
    read under the v1 rules. Such a pin can no longer be made through the service, so
    the legacy row and its pin are written directly — as they were before 0025."""
    company_id, pinned = await _sample_clear(client, tokens)
    website_row = uuid.uuid4()
    with pg() as cursor:
        cursor.execute(
            "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status, "
            " reviewed_by, reviewed_at) VALUES (%s, %s, 'website-reviewed', 'PASSED', 'legacy', now())",
            (str(website_row), company_id),
        )
        cursor.execute(
            "INSERT INTO onboarding.background_check_evidence (id, decision_id, kind, "
            " screening_review_item_id) VALUES (%s, %s, 'SCREENING_ITEM', %s)",
            (str(uuid.uuid4()), pinned["id"], str(website_row)),
        )
    body = (await _evidence(client, tokens, company_id, pinned["id"])).json()
    screening = [i["screening_item"] for i in body["items"] if i["screening_item"]]
    assert len(screening) == 8
    [website] = [item for item in screening if item["item_key"] == "website-reviewed"]
    assert website["retired"] is True
    assert website["label"] == "Has the website been reviewed?"
    assert website["cycle_id"] is not None  # a legacy row reads as cycle 1


async def test_a_decision_recorded_before_rules_were_versioned_reads_as_v1(client, tokens):
    company_id, pinned = await _sample_clear(client, tokens)
    # A decision written before 0025 has no rules version and no cycle. The chain head
    # is the only place one can be appended, so append a legacy-shaped reopen.
    legacy = uuid.uuid4()
    with pg() as cursor:
        cursor.execute(
            "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
            " to_value, decided_by, decided_by_kind, source, reason, supersedes_decision_id) "
            "VALUES (%s, %s, 'CLEAR', 'IN_REVIEW', 'legacy', 'MANUAL', 'MANUAL', 'old', %s)",
            (str(legacy), company_id, pinned["id"]),
        )
    body = (await _evidence(client, tokens, company_id, str(legacy))).json()
    assert body["rules_version"] == CLEAR_RULES_V1
    assert body["items"] == []
    assert body["cycle_number"] == 1  # a NULL cycle reads as cycle 1


async def test_new_decisions_record_the_current_rules_and_cycle(client, tokens):
    assert CLEAR_RULES_V2 == "clear-2026-10-01-7items"
    assert CURRENT_CLEAR_RULES == CLEAR_RULES_V3 == "clear-2026-10-01-7items-kyb-aml-sanctions"
    company_id, _ = await _sample_clear(client, tokens)
    listing = await client.get(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert listing.status_code == 200
    decisions = listing.json()["decisions"]
    assert [d["to_value"] for d in decisions] == ["CLEAR", "IN_REVIEW"]
    assert {d["rules_version"] for d in decisions} == {CLEAR_RULES_V3}
    assert {d["cycle_number"] for d in decisions} == {1}
    assert len({d["cycle_id"] for d in decisions}) == 1


async def test_a_decision_of_another_company_is_404(client, tokens):
    _company_id, pinned = await _sample_clear(client, tokens)
    other = await make_company()
    resp = await _evidence(client, tokens, other, pinned["id"])
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "BACKGROUND_CHECK_DECISION_NOT_FOUND"
    missing = await _evidence(client, tokens, other, uuid.uuid4())
    assert missing.json()["error_code"] == "BACKGROUND_CHECK_DECISION_NOT_FOUND"
    unknown_company = await _evidence(client, tokens, uuid.uuid4(), pinned["id"])
    assert unknown_company.status_code == 404
    assert unknown_company.json()["error_code"] == "EXPORTER_PROFILE_NOT_FOUND"


@pytest.mark.parametrize("role", [UserRole.DEVELOPER, UserRole.API_USER])
async def test_the_evidence_is_refused_to_developer_and_api_user(client, tokens, role):
    company_id, pinned = await _sample_clear(client, tokens)
    resp = await _evidence(client, tokens, company_id, pinned["id"], role=role)
    assert resp.status_code == 403


async def test_the_evidence_carries_no_identifier_for_operations(client, tokens):
    """Masking: the shape has no identifier to mask, and none leaks —
    the company's full PAN appears nowhere in what OPERATIONS is served."""
    company_id, pinned = await _sample_clear(client, tokens)
    full = await client.get(
        f"{BASE}/exporters/{company_id}", headers=auth_header(tokens[UserRole.COMPLIANCE])
    )
    pan = full.json()["pan"]
    assert pan and "•" not in pan
    resp = await _evidence(client, tokens, company_id, pinned["id"], role=UserRole.OPERATIONS)
    assert resp.status_code == 200
    text = json.dumps(resp.json())
    assert pan not in text
    for forbidden in ("pan", "gstin", "iec", "cin", "tax_id", "registration_number",
                      "subject_snapshot", "raw_result", "normalized_result", "contact_email"):
        assert f'"{forbidden}"' not in text, forbidden


async def test_every_pinned_id_on_the_sample_clear_resolves(client: AsyncClient, tokens):
    """Resolved evidence on the seeded sample company B (§3.9).
    In a database seeded before 1 October 2026, B's Clear is a legacy eight-item one: its
    website answer still resolves, marked retired."""
    from app.modules.onboarding.sample_data import COMPANIES, load_sample_data

    await load_sample_data()
    [company_b] = [company.customer_id for company in COMPANIES if company.slug == "company-b"]
    listing = await client.get(
        f"{BASE}/exporters/{company_b}/background-check/decisions",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    clears = [d for d in listing.json()["decisions"] if d["to_value"] == "CLEAR"]
    assert clears, "sample company B has been cleared"
    for decision in clears:
        body = (await _evidence(client, tokens, company_b, decision["id"])).json()
        assert len(body["items"]) == len(decision["evidence"]) > 0
        for item in body["items"]:
            detail = {
                "VERIFICATION_RESULT": item["verification"],
                "SCREENING_ITEM": item["screening_item"],
                "DOCUMENT": item["document"],
            }[item["kind"]]
            assert detail is not None, item
        # V1 by the read rule, or the version stored (V2 before the required checks, V3 since).
        expected = decision["rules_version"] or CLEAR_RULES_V1
        assert expected in (CLEAR_RULES_V1, CLEAR_RULES_V2, CLEAR_RULES_V3)
        assert body["rules_version"] == expected
