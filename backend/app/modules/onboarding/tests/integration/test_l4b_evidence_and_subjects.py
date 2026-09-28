"""Manual evidence and subject validation — **owner: Developer 4B** (4B-4;
``docs/dev4/4b-task.md`` §5.3, L4-07).

* a manual PASSED without evidence is 422 — service and API (D16, lead, 28 Sep 2026:
  a note or at least one reference);
* a note, a valid document, or a url is accepted; a foreign or missing document is
  refused; a document on a subject that cannot own one is refused;
* evidence is stored and the reader reports its document ids;
* a ghost EXPORTER subject is 404;
* no manual result is ever PENDING.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import EvidenceRef, VerificationEvidence
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._l4b_support import (
    BASE,
    deal_buyer,
    exporter_result,
    history_rows,
    insert_document,
    open_deal,
    pg,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


def _documents(*ids: uuid.UUID) -> VerificationEvidence:
    return VerificationEvidence(refs=tuple(EvidenceRef(type="document", ref=str(i)) for i in ids))


async def _count_results(entity_type: VerificationEntityType, reference: uuid.UUID) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return len(
            await VerificationService(db).list_verification_results(entity_type, reference)
        )


# ── The evidence rule ────────────────────────────────────────────────────────


async def test_a_manual_passed_without_evidence_is_refused_and_writes_nothing():
    company_id = await make_company()
    with pytest.raises(ValidationError, match="evidence"):
        await exporter_result(company_id, evidence=None)
    assert await _count_results(VerificationEntityType.EXPORTER, company_id) == 0
    with pg() as cur:
        assert history_rows(cur, company_id) == []


async def test_a_note_is_accepted_and_stored_until_d16_says_otherwise():
    company_id = await make_company()
    result = await exporter_result(
        company_id, evidence=VerificationEvidence(note="  Bank letter dated 2 Sep  ")
    )
    assert result.evidence_note == "Bank letter dated 2 Sep"
    assert result.evidence_refs == []


async def test_a_document_of_the_company_is_accepted_and_reported_by_the_reader():
    company_id = await make_company()
    with pg() as cur:
        first = insert_document(cur, company_id=company_id)
        second = insert_document(cur, company_id=company_id)
    evidence = VerificationEvidence(
        refs=(
            EvidenceRef(type="document", ref=str(first)),
            EvidenceRef(type="url", ref="https://registry.example/entity/1"),
            EvidenceRef(type="document", ref=str(second)),
        )
    )
    result = await exporter_result(company_id, evidence=evidence)

    assert result.evidence_refs == [ref.as_json() for ref in evidence.refs]
    async with db_services.AsyncSessionLocal() as db:
        [read] = (await ComplianceInputsService(db).company_inputs(company_id)).verifications
    assert read.evidence_document_ids == (first, second)


async def test_another_companys_document_is_refused():
    company_id = await make_company()
    other_company = await make_company()
    with pg() as cur:
        foreign = insert_document(cur, company_id=other_company)
    with pytest.raises(ValidationError, match="does not belong"):
        await exporter_result(company_id, evidence=_documents(foreign))
    assert await _count_results(VerificationEntityType.EXPORTER, company_id) == 0


async def test_a_document_on_one_of_the_companys_deals_is_not_the_companys():
    """For an EXPORTER subject the document must be the company's own (§5.3)."""
    company_id = await make_company()
    deal_id = await open_deal(company_id)
    with pg() as cur:
        on_deal = insert_document(cur, deal_id=deal_id)
    with pytest.raises(ValidationError, match="does not belong"):
        await exporter_result(company_id, evidence=_documents(on_deal))


async def test_a_missing_document_is_refused():
    company_id = await make_company()
    with pytest.raises(ValidationError, match="does not exist"):
        await exporter_result(company_id, evidence=_documents(uuid.uuid4()))


async def test_document_evidence_on_a_subject_with_no_company_is_refused():
    company_id = await make_company()
    with pg() as cur:
        document = insert_document(cur, company_id=company_id)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="cannot be attached"):
            await VerificationService(db).trigger_verification(
                VerificationType.KYC,
                VerificationEntityType.DIRECTOR,
                uuid.uuid4(),
                payload={"status": "PASSED"},
                actor_id="tester",
                evidence=_documents(document),
            )


@pytest.mark.parametrize("status", ["FAILED", "REVIEW"])
async def test_other_manual_outcomes_are_unchanged_pending_d16(status):
    result = await exporter_result(await make_company(), status=status, evidence=None)
    assert result.status.value == status


async def test_a_manual_pending_result_is_refused():
    company_id = await make_company()
    with pytest.raises(ValidationError, match="PENDING"):
        await exporter_result(company_id, status="PENDING")
    assert await _count_results(VerificationEntityType.EXPORTER, company_id) == 0


# ── Subjects ─────────────────────────────────────────────────────────────────


async def test_a_ghost_exporter_subject_is_404_and_writes_nothing():
    ghost = uuid.uuid4()
    with pytest.raises(ExporterProfileNotFoundError):
        await exporter_result(ghost)
    assert await _count_results(VerificationEntityType.EXPORTER, ghost) == 0


async def test_a_buyer_id_is_not_an_exporter_subject():
    _, _, buyer_id = await deal_buyer()
    with pytest.raises(ExporterProfileNotFoundError):
        await exporter_result(buyer_id)


async def test_recording_a_result_writes_a_verification_history_row():
    company_id = await make_company()
    result = await exporter_result(company_id)
    with pg() as cur:
        [row] = history_rows(cur, company_id)
    assert row[:6] == ("verification_initial", None, "PASSED", "tester", None, None)
    assert row[6] == {
        "source": "verification_service.trigger_verification",
        "verification_result_id": str(result.id),
        "verification_type": "KYB",
        "entity_type": "EXPORTER",
        "entity_reference": str(company_id),
        "provider": "manual",
    }


async def test_a_director_check_writes_no_history_row_pending_d15():
    """No company link — D15 (lead, 28 Sep 2026): no history row."""
    director = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.KYC,
            VerificationEntityType.DIRECTOR,
            director,
            payload={"status": "FAILED"},
            actor_id="tester",
        )
    with pg() as cur:
        cur.execute(
            "SELECT count(*) FROM onboarding.exporter_lifecycle_history "
            "WHERE event_metadata->>'entity_reference' = %s",
            (str(director),),
        )
        assert cur.fetchone() == (0,)


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def compliance_token(client: AsyncClient) -> str:
    return await token_with_role(client, UserRole.COMPLIANCE)


def _body(reference: uuid.UUID, **extra) -> dict:
    return {
        "verification_type": "KYB",
        "entity_type": "EXPORTER",
        "entity_reference": str(reference),
        "payload": {"status": "PASSED"},
        **extra,
    }


async def test_the_api_refuses_a_passed_without_evidence(client, compliance_token):
    resp = await client.post(
        f"{BASE}/verifications",
        json=_body(await make_company()),
        headers=auth_header(compliance_token),
    )
    assert resp.status_code == 422, resp.text
    assert "evidence" in resp.text


async def test_the_api_records_evidence_and_returns_it(client, compliance_token):
    company_id = await make_company()
    with pg() as cur:
        document = insert_document(cur, company_id=company_id)
    resp = await client.post(
        f"{BASE}/verifications",
        json=_body(
            company_id,
            evidence_note="Registry extract",
            evidence_refs=[{"type": "document", "ref": str(document)}],
        ),
        headers=auth_header(compliance_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["evidence_note"] == "Registry extract"
    assert body["evidence_refs"] == [{"type": "document", "ref": str(document)}]
    assert body["provenance"] == "MANUAL"
    assert body["is_placeholder"] is False


async def test_the_api_refuses_a_foreign_document(client, compliance_token):
    other = await make_company()
    with pg() as cur:
        foreign = insert_document(cur, company_id=other)
    resp = await client.post(
        f"{BASE}/verifications",
        json=_body(await make_company(), evidence_refs=[{"type": "document", "ref": str(foreign)}]),
        headers=auth_header(compliance_token),
    )
    assert resp.status_code == 422, resp.text


async def test_the_api_refuses_an_unknown_reference_type(client, compliance_token):
    resp = await client.post(
        f"{BASE}/verifications",
        json=_body(
            await make_company(),
            evidence_refs=[{"type": "verification_result", "ref": str(uuid.uuid4())}],
        ),
        headers=auth_header(compliance_token),
    )
    assert resp.status_code == 422, resp.text


async def test_the_api_404s_a_ghost_company(client, compliance_token):
    resp = await client.post(
        f"{BASE}/verifications",
        json=_body(uuid.uuid4(), evidence_note="x"),
        headers=auth_header(compliance_token),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "EXPORTER_PROFILE_NOT_FOUND"


@pytest.mark.parametrize("field", ["actor_id", "recorded_by", "source", "provenance"])
async def test_the_api_never_accepts_an_actor_or_source_field(client, compliance_token, field):
    resp = await client.post(
        f"{BASE}/verifications",
        json=_body(await make_company(), evidence_note="x", **{field: "someone"}),
        headers=auth_header(compliance_token),
    )
    assert resp.status_code == 422, resp.text
