"""Evidence on a screening answer, and the retired checklist item.

An answer may carry ``{type, ref}`` references (optional), checked by the same
rule as a verification result's: a ``document`` of the company that is ``AVAILABLE``,
or an http(s) ``url``. The table stays append-only. ``website-reviewed`` left the
checklist: its rows are kept and readable, and a new answer to it is refused.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    ScreeningReviewService,
)
from app.modules.onboarding.domain.verification_evidence import EvidenceRef, VerificationEvidence
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._verification_support import BASE, insert_document, pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

ITEM = SCREENING_CATALOGUE[0]


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


def _url(company_id, item_key: str = ITEM) -> str:
    return f"{BASE}/exporters/{company_id}/screening-review/{item_key}"


async def test_a_passed_answer_with_a_document_round_trips(client: AsyncClient, tokens):
    company_id = await make_company()
    with pg() as cursor:
        document_id = insert_document(cursor, company_id=company_id)
    refs = [
        {"type": "document", "ref": str(document_id)},
        {"type": "url", "ref": "https://registry.example.com/extract/42"},
    ]
    put = await client.put(
        _url(company_id),
        json={"status": "PASSED", "comment": "Address confirmed", "evidence_refs": refs},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert put.status_code == 200, put.text
    assert put.json()["evidence_refs"] == refs
    assert put.json()["cycle_id"] is not None

    listing = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    [item] = listing.json()["items"]
    assert item["evidence_refs"] == refs

    history = await client.get(
        f"{_url(company_id)}/history", headers=auth_header(tokens[UserRole.OPERATIONS])
    )
    assert history.json()["items"][0]["evidence_refs"] == refs


async def test_evidence_is_optional(client: AsyncClient, tokens):
    """An answer without evidence is recorded as before."""
    company_id = await make_company()
    put = await client.put(
        _url(company_id), json={"status": "PASSED"}, headers=auth_header(tokens[UserRole.ADMIN])
    )
    assert put.status_code == 200, put.text
    assert put.json()["evidence_refs"] == []


@pytest.mark.parametrize(
    ("ref", "reason"),
    [
        ({"type": "url", "ref": "javascript:alert(1)"}, "http"),
        ({"type": "document", "ref": "not-a-uuid"}, "document id"),
        ({"type": "document", "ref": "00000000-0000-4000-8000-000000000000"}, "does not exist"),
    ],
)
async def test_malformed_or_missing_evidence_is_422(client, tokens, ref, reason):
    company_id = await make_company()
    resp = await client.put(
        _url(company_id),
        json={"status": "PASSED", "evidence_refs": [ref]},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 422, resp.text
    assert reason in resp.json()["detail"]


async def test_another_companys_document_is_refused():
    company_id, other = await make_company(), await make_company()
    with pg() as cursor:
        foreign = insert_document(cursor, company_id=other)
    evidence = VerificationEvidence(refs=(EvidenceRef(type="document", ref=str(foreign)),))
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="does not belong"):
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key=ITEM, status="PASSED", comment=None, actor_id="c",
                evidence=evidence,
            )


@pytest.mark.parametrize("scan_status", ["PENDING_SCAN", "QUARANTINED", "SCAN_FAILED"])
async def test_a_document_that_cannot_be_opened_is_refused(scan_status):
    company_id = await make_company()
    with pg() as cursor:
        document_id = insert_document(cursor, company_id=company_id, scan_status=scan_status)
    evidence = VerificationEvidence(refs=(EvidenceRef(type="document", ref=str(document_id)),))
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="AVAILABLE"):
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key=ITEM, status="PASSED", comment=None, actor_id="c",
                evidence=evidence,
            )


async def test_a_refused_answer_writes_nothing():
    company_id = await make_company()
    evidence = VerificationEvidence(refs=(EvidenceRef(type="url", ref="ftp://nope"),))
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key=ITEM, status="PASSED", comment=None, actor_id="c",
                evidence=evidence,
            )
    with pg() as cursor:
        cursor.execute(
            "SELECT count(*) FROM onboarding.screening_review_item WHERE customer_id = %s",
            (str(company_id),),
        )
        assert cursor.fetchone() == (0,)


async def test_an_answer_with_evidence_is_still_append_only():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        row = await ScreeningReviewService(db).upsert_review_item(
            company_id, item_key=ITEM, status="PASSED", comment=None, actor_id="c",
            evidence=VerificationEvidence(refs=(EvidenceRef(type="url", ref="https://a.example"),)),
        )
    with pg() as cursor:
        with pytest.raises(psycopg2.errors.RaiseException):
            cursor.execute(
                "UPDATE onboarding.screening_review_item SET evidence_refs = '[]'::jsonb "
                "WHERE id = %s",
                (str(row.id),),
            )
        with pytest.raises(psycopg2.errors.RaiseException):
            cursor.execute(
                "DELETE FROM onboarding.screening_review_item WHERE id = %s", (str(row.id),)
            )


async def test_evidence_refs_must_be_an_array_at_the_database():
    with pg() as cursor:
        company_id = uuid.uuid4()
        cursor.execute(
            "INSERT INTO onboarding.exporter_profile (id, customer_id, source) "
            "VALUES (%s, %s, 'SALES')",
            (str(uuid.uuid4()), str(company_id)),
        )
        with pytest.raises(psycopg2.errors.CheckViolation) as caught:
            cursor.execute(
                "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status, "
                " evidence_refs) VALUES (%s, %s, %s, 'PASSED', '{}'::jsonb)",
                (str(uuid.uuid4()), str(company_id), ITEM),
            )
        assert caught.value.diag.constraint_name == "ck_screening_review_item_evidence_refs_array"


# ── The retired item ─────────────────────────────────────────────────


async def test_the_checklist_serves_seven_items_and_hides_the_retired_one(client, tokens):
    company_id = await make_company()
    with pg() as cursor:
        cursor.execute(
            "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status) "
            "VALUES (%s, %s, 'website-reviewed', 'PASSED')",
            (str(uuid.uuid4()), str(company_id)),
        )
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [item["key"] for item in body["catalogue"]] == list(SCREENING_CATALOGUE)
    assert len(body["catalogue"]) == 7
    assert "website-reviewed" not in [item["key"] for item in body["catalogue"]]
    assert body["items"] == []  # the stored website row is kept, not listed


async def test_the_retired_item_takes_no_new_answer_but_its_history_stays(client, tokens):
    company_id = await make_company()
    with pg() as cursor:
        cursor.execute(
            "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status) "
            "VALUES (%s, %s, 'website-reviewed', 'FAILED')",
            (str(uuid.uuid4()), str(company_id)),
        )
    refused = await client.put(
        _url(company_id, "website-reviewed"),
        json={"status": "PASSED"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert refused.status_code == 422
    assert "retired" in refused.json()["detail"]

    history = await client.get(
        f"{_url(company_id, 'website-reviewed')}/history",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert history.status_code == 200
    assert [row["status"] for row in history.json()["items"]] == ["FAILED"]
