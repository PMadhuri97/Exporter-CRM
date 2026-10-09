"""Superseding verification reviews
(``docs/contracts/verification-and-screening.md`` §1).

A reviewer changes a verdict only by adding a record:

* the first review names nothing; a later one must name the current review and say
  why; a stale or missing name is 409 and writes nothing;
* concurrent reviews cannot fork the chain — one wins, the other gets 409;
* PENDING results stay unreviewable (422);
* old reviews are never edited; the legacy columns are not written;
* a legacy verdict with no review record (set outside the service after migration
  0021) is refused (409), never overruled by a new "first" review;
* every review writes a ``verification`` history row on the subject's company;
* the reviewer is the session user — a body cannot name one;
* the reader reports the chain head.

Immutability and the chain constraints are proved with direct SQL in
``test_verification_review_schema.py``.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationReviewStatus
from app.modules.onboarding.exceptions import (
    VerificationLegacyReviewUnchainedError,
    VerificationResultNotReviewableError,
    VerificationReviewStaleError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._verification_support import (
    BASE,
    exporter_result,
    history_rows,
    insert_result,
    insert_review,
    pg,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

ACCEPTED = VerificationReviewStatus.ACCEPTED
REJECTED = VerificationReviewStatus.REJECTED
ESCALATED = VerificationReviewStatus.ESCALATED


async def _review(result_id, status=ACCEPTED, *, by="c1", note=None, supersedes=None):
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).record_review(
            result_id,
            reviewed_by=by,
            review_status=status,
            note=note,
            supersedes_review_id=supersedes,
        )


async def _chain(result_id):
    async with db_services.AsyncSessionLocal() as db:
        return (await VerificationService(db).get_result_view(result_id)).reviews


# ── The chain ────────────────────────────────────────────────────────────────


async def test_reviews_form_one_chain_and_the_head_is_current():
    result = await exporter_result(await make_company())

    first = await _review(result.id, ACCEPTED, by="c1")
    second = await _review(result.id, ESCALATED, by="c2", note="UBO unclear", supersedes=first.id)
    third = await _review(result.id, REJECTED, by="c3", note="UBO confirmed PEP", supersedes=second.id)

    chain = await _chain(result.id)
    assert [r.id for r in chain] == [first.id, second.id, third.id]
    assert [r.supersedes_review_id for r in chain] == [None, first.id, second.id]
    assert [r.reviewed_by for r in chain] == ["c1", "c2", "c3"]
    # The earlier reviews are exactly as written.
    assert (chain[0].review_status, chain[0].note) == (ACCEPTED, None)
    assert (chain[1].review_status, chain[1].note) == (ESCALATED, "UBO unclear")


async def test_a_first_review_that_names_a_predecessor_is_stale():
    result = await exporter_result(await make_company())
    with pytest.raises(VerificationReviewStaleError) as stale:
        await _review(result.id, supersedes=uuid.uuid4(), note="x")
    assert stale.value.current_review_id is None
    assert await _chain(result.id) == ()


async def test_a_later_review_naming_an_old_review_is_stale_and_writes_nothing():
    result = await exporter_result(await make_company())
    first = await _review(result.id)
    second = await _review(result.id, REJECTED, note="changed", supersedes=first.id)

    with pytest.raises(VerificationReviewStaleError) as stale:
        await _review(result.id, ESCALATED, note="acting on an old screen", supersedes=first.id)
    assert stale.value.current_review_id == second.id
    assert [r.id for r in await _chain(result.id)] == [first.id, second.id]


async def test_a_superseding_review_must_say_why():
    result = await exporter_result(await make_company())
    first = await _review(result.id)
    with pytest.raises(ValidationError, match="note"):
        await _review(result.id, REJECTED, note="   ", supersedes=first.id)
    assert [r.id for r in await _chain(result.id)] == [first.id]


async def test_a_pending_result_is_unreviewable():
    with pg() as cur:
        result_id = insert_result(cur, status="PENDING")
    with pytest.raises(VerificationResultNotReviewableError) as refused:
        await _review(result_id)
    assert refused.value.status_code == 422
    assert await _chain(result_id) == ()


async def test_the_legacy_columns_are_not_written():
    result = await exporter_result(await make_company())
    await _review(result.id)
    with pg() as cur:
        cur.execute(
            "SELECT reviewed_by, review_status FROM onboarding.verification_result WHERE id = %s",
            (str(result.id),),
        )
        assert cur.fetchone() == (None, None)


def _legacy_verdict_without_a_review_row(cur, **result) -> uuid.UUID:
    """A result whose legacy columns were set by raw SQL after migration 0021 —
    the only way to have a legacy verdict and no ``verification_review`` row."""
    result_id = insert_result(cur, status="REVIEW", **result)
    cur.execute(
        "UPDATE onboarding.verification_result "
        "SET reviewed_by = 'legacy', review_status = 'ACCEPTED' WHERE id = %s",
        (str(result_id),),
    )
    return result_id


async def test_a_legacy_verdict_with_no_review_record_is_refused_not_overruled():
    company_id = await make_company()
    with pg() as cur:
        result_id = _legacy_verdict_without_a_review_row(
            cur, entity_type="EXPORTER", entity_reference=company_id
        )

    # Neither a "first" review nor one naming some review can land: there is
    # nothing to supersede, and a first review would overrule the legacy verdict
    # with no link and no reason.
    for supersedes, note in ((None, None), (uuid.uuid4(), "overrule")):
        with pytest.raises(VerificationLegacyReviewUnchainedError) as refused:
            await _review(result_id, REJECTED, note=note, supersedes=supersedes)
        assert refused.value.status_code == 409
        assert refused.value.legacy_review_status == "ACCEPTED"

    assert await _chain(result_id) == ()
    with pg() as cur:
        assert history_rows(cur, company_id) == []
        cur.execute(
            "SELECT reviewed_by, review_status FROM onboarding.verification_result WHERE id = %s",
            (str(result_id),),
        )
        assert cur.fetchone() == ("legacy", "ACCEPTED")


async def test_once_the_legacy_verdict_is_copied_into_a_review_it_can_be_superseded():
    """The repair the refusal names — what migration 0021 did for earlier verdicts."""
    with pg() as cur:
        result_id = _legacy_verdict_without_a_review_row(cur)
        copied = insert_review(cur, result_id, status="ACCEPTED")
    later = await _review(result_id, REJECTED, note="Registry mismatch", supersedes=copied)
    assert [r.id for r in await _chain(result_id)] == [copied, later.id]


# ── Concurrency ──────────────────────────────────────────────────────────────


async def test_concurrent_first_reviews_do_not_both_land():
    result = await exporter_result(await make_company())
    outcomes = await asyncio.gather(
        _review(result.id, ACCEPTED, by="a"),
        _review(result.id, REJECTED, by="b"),
        return_exceptions=True,
    )
    assert sum(isinstance(o, VerificationReviewStaleError) for o in outcomes) == 1
    assert len(await _chain(result.id)) == 1


async def test_concurrent_superseding_reviews_cannot_fork_the_chain():
    result = await exporter_result(await make_company())
    first = await _review(result.id)
    outcomes = await asyncio.gather(
        _review(result.id, REJECTED, by="a", note="a disagrees", supersedes=first.id),
        _review(result.id, ESCALATED, by="b", note="b escalates", supersedes=first.id),
        return_exceptions=True,
    )
    assert sum(isinstance(o, VerificationReviewStaleError) for o in outcomes) == 1
    chain = await _chain(result.id)
    assert len(chain) == 2
    assert chain[1].supersedes_review_id == first.id


# ── History ──────────────────────────────────────────────────────────────────


async def test_every_review_writes_a_verification_history_row():
    company_id = await make_company()
    result = await exporter_result(company_id)
    first = await _review(result.id, ACCEPTED, by="c1")
    second = await _review(result.id, REJECTED, by="c2", note="reversed", supersedes=first.id)

    with pg() as cur:
        rows = history_rows(cur, company_id)

    recorded, review_1, review_2 = rows
    assert recorded[0] == "verification_initial"  # the result itself
    assert review_1[:6] == ("verification_reviewed", None, "ACCEPTED", "c1", None, None)
    assert review_2[:6] == ("verification_reviewed", "ACCEPTED", "REJECTED", "c2", "reversed", None)
    assert review_2[6] == {
        "source": "verification_service.record_review",
        "verification_result_id": str(result.id),
        "review_id": str(second.id),
        "supersedes_review_id": str(first.id),
        "verification_type": "KYB",
    }


async def test_a_refused_review_writes_no_history_row():
    company_id = await make_company()
    result = await exporter_result(company_id)
    await _review(result.id)
    with pytest.raises(VerificationReviewStaleError):
        await _review(result.id, REJECTED, note="stale", supersedes=None)
    with pg() as cur:
        assert [row[0] for row in history_rows(cur, company_id)] == [
            "verification_initial",
            "verification_reviewed",
        ]


# ── Reader ───────────────────────────────────────────────────────────────────


async def test_the_reader_reports_the_chain_head():
    company_id = await make_company()
    result = await exporter_result(company_id)
    first = await _review(result.id)
    head = await _review(result.id, ESCALATED, note="needs a second pair of eyes", supersedes=first.id)

    async with db_services.AsyncSessionLocal() as db:
        inputs = await ComplianceInputsService(db).company_inputs(company_id)

    [read] = inputs.verifications
    assert (read.latest_review_id, read.latest_review_status, read.latest_reviewed_at) == (
        head.id,
        "ESCALATED",
        head.reviewed_at,
    )


# ── API ──────────────────────────────────────────────────────────────────────


async def _api_result(client: AsyncClient, token: str) -> str:
    company = await client.post(
        f"{BASE}/exporters", json={"source": "SALES"}, headers=auth_header(token)
    )
    assert company.status_code == 201, company.text
    resp = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "KYB",
            "entity_type": "EXPORTER",
            "entity_reference": company.json()["customer_id"],
            "payload": {"status": "REVIEW"},
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_the_api_supersedes_and_returns_the_chain(client: AsyncClient):
    reviewer_1, token_1 = await user_with_role(client, UserRole.COMPLIANCE)
    reviewer_2, token_2 = await user_with_role(client, UserRole.COMPLIANCE)
    result_id = await _api_result(client, token_1)
    url = f"{BASE}/verifications/{result_id}/review"

    first = await client.post(url, json={"review_status": "ACCEPTED"}, headers=auth_header(token_1))
    assert first.status_code == 200, first.text
    first_id = first.json()["latest_review_id"]
    assert first.json()["reviewed_by"] == reviewer_1

    stale = await client.post(
        url, json={"review_status": "REJECTED", "note": "no"}, headers=auth_header(token_2)
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error_code"] == "VERIFICATION_REVIEW_STALE"

    second = await client.post(
        url,
        json={"review_status": "REJECTED", "note": "Registry mismatch", "supersedes_review_id": first_id},
        headers=auth_header(token_2),
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert [r["reviewed_by"] for r in body["reviews"]] == [reviewer_1, reviewer_2]
    assert [r["review_status"] for r in body["reviews"]] == ["ACCEPTED", "REJECTED"]
    assert body["reviews"][1]["supersedes_review_id"] == first_id
    assert (body["review_status"], body["reviewed_by"]) == ("REJECTED", reviewer_2)
    assert body["latest_review_id"] == body["reviews"][1]["id"]

    read = await client.get(f"{BASE}/verifications/{result_id}", headers=auth_header(token_1))
    assert read.json()["reviews"] == body["reviews"]


@pytest.mark.parametrize("field", ["reviewed_by", "actor_id", "reviewed_at", "source"])
async def test_the_api_never_accepts_a_reviewer_actor_time_or_source(client, field):
    _, token = await user_with_role(client, UserRole.COMPLIANCE)
    result_id = await _api_result(client, token)
    resp = await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"review_status": "ACCEPTED", field: "someone-else"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_the_api_refuses_to_review_a_pending_result(client):
    _, token = await user_with_role(client, UserRole.COMPLIANCE)
    with pg() as cur:
        result_id = insert_result(cur, status="PENDING")
    resp = await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"review_status": "ACCEPTED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "VERIFICATION_RESULT_NOT_REVIEWABLE"


async def test_the_api_answers_409_for_a_legacy_verdict_with_no_review_record(client):
    _, token = await user_with_role(client, UserRole.COMPLIANCE)
    with pg() as cur:
        result_id = _legacy_verdict_without_a_review_row(cur)
    resp = await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"review_status": "REJECTED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "VERIFICATION_LEGACY_REVIEW_UNCHAINED"
    assert await _chain(result_id) == ()
