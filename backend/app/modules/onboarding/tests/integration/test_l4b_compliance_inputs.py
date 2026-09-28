"""``ComplianceInputsService`` against real rows — the 4A ↔ 4B seam (4B-0).

``docs/dev4/4b-task.md`` §6. What is proved here:

* the empty value, the screening and verification shapes, and their ordering;
* "latest" is deterministic, including on a timestamp tie;
* company scope is ``EXPORTER`` + the company id, so buyer checks and checks on
  unlinked subjects never reach ``company_inputs``;
* the two not-found errors;
* the reader writes, flushes, commits and locks nothing;
* Dev4B's writers of company-scoped inputs take ``FOR SHARE`` on the company row,
  so they wait behind Developer 4A's ``FOR UPDATE`` and nothing else.

Follows ``test_e9_screening_review_service.py``: real Postgres, no per-test
rollback, each test mints its own company. Rows the service has no way to write
(timestamp ties, unlinked subjects, placeholder rows, keys outside the catalogue)
go in through ``psycopg2``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import psycopg2.extras
import pytest
from sqlalchemy import event, select

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    ScreeningReviewService,
)
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ScreeningItemInput,
    VerificationInput,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.exceptions import (
    ComplianceInputsBuyerNotFoundError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

#: How long a writer is given to finish before it counts as waiting on a lock.
#: Each writer here finishes in well under this when nothing blocks it.
_BLOCKED_AFTER_SECONDS = 1.5


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _insert_result(
    cursor,
    *,
    entity_type: str,
    entity_reference: uuid.UUID,
    verification_type: str = "BANK_ACCOUNT",
    status: str = "PASSED",
    provider: str = "manual",
    provider_reference: str | None = "ref-1",
    performed_at: datetime | None = None,
    normalized_result: dict | None = None,
    result_id: uuid.UUID | None = None,
) -> uuid.UUID:
    result_id = result_id or uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.verification_result "
        "(id, verification_type, entity_type, entity_reference, provider, provider_reference, "
        " status, performed_at, raw_result, normalized_result) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            str(result_id),
            verification_type,
            entity_type,
            str(entity_reference),
            provider,
            provider_reference,
            status,
            performed_at or datetime.now(UTC),
            psycopg2.extras.Json({}),
            psycopg2.extras.Json(normalized_result or {}),
        ),
    )
    return result_id


def _insert_screening_row(
    cursor, company_id: uuid.UUID, item_key: str, status: str, *, created_at: datetime, row_id=None
) -> uuid.UUID:
    row_id = row_id or uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.screening_review_item "
        "(id, customer_id, item_key, status, reviewed_by, reviewed_at, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, 'reviewer', %s, %s, %s)",
        (str(row_id), str(company_id), item_key, status, created_at, created_at, created_at),
    )
    return row_id


async def _company_inputs(company_id: uuid.UUID) -> CompanyComplianceInputs:
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceInputsService(db).company_inputs(company_id)


async def _buyer_checks(deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]:
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceInputsService(db).buyer_checks(deal_buyer_id)


async def _manual_exporter_result(company_id: uuid.UUID, status: str = "PASSED"):
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).trigger_verification(
            VerificationType.BANK_ACCOUNT,
            VerificationEntityType.EXPORTER,
            company_id,
            provider="manual",
            payload={"status": status, "risk_level": "LOW", "provider_reference": "bank-1"},
            actor_id="tester",
        )


async def _deal_buyer(company_id: uuid.UUID) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        deal = await DealService(db).open_deal(
            company_id, reference="Rotterdam shipment", actor_id="tester"
        )
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).set_buyer(
            deal.id, actor_id="tester", name="Rotterdam Trading BV", country="NL"
        )
    return view.buyer.id


# ── Empty and shape ──────────────────────────────────────────────────────────


async def test_a_company_with_no_inputs_is_a_valid_empty_value():
    company_id = await make_company()

    inputs = await _company_inputs(company_id)

    assert inputs == CompanyComplianceInputs(
        company_id=company_id,
        screening_catalogue=SCREENING_CATALOGUE,
        screening_items=tuple(
            ScreeningItemInput(
                item_key=key,
                screening_review_item_id=None,
                status=None,
                reviewed_by=None,
                reviewed_at=None,
            )
            for key in SCREENING_CATALOGUE
        ),
        verifications=(),
    )


async def test_screening_items_are_one_per_catalogue_key_in_catalogue_order_with_the_latest_row():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        service = ScreeningReviewService(db)
        await service.upsert_review_item(
            company_id, item_key="payment-purpose", status="FAILED", comment=None, actor_id="a"
        )
        latest = await service.upsert_review_item(
            company_id, item_key="payment-purpose", status="PASSED", comment=None, actor_id="b"
        )
        exempt = await service.upsert_review_item(
            company_id, item_key="exception-approval", status="EXEMPT", comment=None, actor_id="c"
        )

    inputs = await _company_inputs(company_id)

    assert inputs.screening_catalogue == SCREENING_CATALOGUE
    assert [item.item_key for item in inputs.screening_items] == list(SCREENING_CATALOGUE)
    by_key = {item.item_key: item for item in inputs.screening_items}
    assert by_key["payment-purpose"] == ScreeningItemInput(
        item_key="payment-purpose",
        screening_review_item_id=latest.id,
        status="PASSED",
        reviewed_by="b",
        reviewed_at=latest.reviewed_at,
    )
    assert by_key["exception-approval"].screening_review_item_id == exempt.id
    assert by_key["exception-approval"].status == "EXEMPT"
    assert sum(item.status is None for item in inputs.screening_items) == 6


async def test_a_row_under_a_key_outside_the_catalogue_is_not_returned():
    company_id = await make_company()
    with _connect() as conn, conn.cursor() as cur:
        _insert_screening_row(
            cur, company_id, "retired-item", "FAILED", created_at=datetime.now(UTC)
        )

    inputs = await _company_inputs(company_id)

    assert len(inputs.screening_items) == 8
    assert all(item.status is None for item in inputs.screening_items)


async def test_verifications_have_the_contract_shape():
    company_id = await make_company()
    result = await _manual_exporter_result(company_id)

    inputs = await _company_inputs(company_id)

    assert inputs.verifications == (
        VerificationInput(
            verification_result_id=result.id,
            verification_type="BANK_ACCOUNT",
            entity_type="EXPORTER",
            provider="manual",
            status="PASSED",
            risk_level="LOW",
            performed_at=result.performed_at,
            is_placeholder=False,
            latest_review_id=None,
            latest_review_status=None,
            latest_reviewed_at=None,
            evidence_document_ids=(),
        ),
    )


async def test_a_placeholder_row_is_reported_and_flagged_not_filtered():
    """The rows `VerificationSection.tsx`'s dev generator made: `stub` and no provider reference."""
    company_id = await make_company()
    with _connect() as conn, conn.cursor() as cur:
        placeholder = _insert_result(
            cur,
            entity_type="EXPORTER",
            entity_reference=company_id,
            status="PENDING",
            provider_reference=None,
            normalized_result={"stub": True},
        )
        stub_with_reference = _insert_result(
            cur,
            entity_type="EXPORTER",
            entity_reference=company_id,
            provider_reference="real-ref",
            normalized_result={"stub": True},
            performed_at=datetime.now(UTC) - timedelta(hours=1),
        )

    inputs = await _company_inputs(company_id)
    flags = {v.verification_result_id: v.is_placeholder for v in inputs.verifications}

    assert flags == {placeholder: True, stub_with_reference: False}


async def test_verifications_are_newest_first_and_ties_are_deterministic():
    company_id = await make_company()
    now = datetime.now(UTC)
    tie_low, tie_high = sorted([uuid.uuid4(), uuid.uuid4()])
    with _connect() as conn, conn.cursor() as cur:
        oldest = _insert_result(
            cur, entity_type="EXPORTER", entity_reference=company_id,
            performed_at=now - timedelta(days=2),
        )
        newest = _insert_result(
            cur, entity_type="EXPORTER", entity_reference=company_id, performed_at=now,
        )
        # Same performed_at and — same transaction — same created_at: the id decides.
        for result_id in (tie_low, tie_high):
            _insert_result(
                cur, entity_type="EXPORTER", entity_reference=company_id,
                performed_at=now - timedelta(days=1), result_id=result_id,
            )

    first = [v.verification_result_id for v in (await _company_inputs(company_id)).verifications]
    second = [v.verification_result_id for v in (await _company_inputs(company_id)).verifications]

    assert first == [newest, tie_high, tie_low, oldest]
    assert second == first


# ── Deterministic latest ─────────────────────────────────────────────────────


async def test_the_latest_screening_row_on_a_timestamp_tie_is_decided_by_id():
    """§6.2 invariant 5: `created_at DESC, id DESC`, every time."""
    company_id = await make_company()
    at = datetime.now(UTC)
    low, high = sorted([uuid.uuid4(), uuid.uuid4()])
    with _connect() as conn, conn.cursor() as cur:
        for row_id, status in ((high, "FAILED"), (low, "PASSED")):
            _insert_screening_row(
                cur, company_id, "website-reviewed", status, created_at=at, row_id=row_id
            )
        _insert_screening_row(
            cur, company_id, "website-reviewed", "EXEMPT",
            created_at=at - timedelta(minutes=5),
        )

    reads = [await _company_inputs(company_id) for _ in range(3)]

    picked = {inputs.screening_items[0].screening_review_item_id for inputs in reads}
    assert picked == {high}
    assert reads[0].screening_items[0].status == "FAILED"


async def test_the_latest_review_is_the_results_one_review_and_is_stable():
    """Today a result has at most one review, in its frozen columns (4B-0).

    The status is reported. The review id and time are `None`: today's storage has
    neither, and the reader does not invent them (4B-2's review table adds both).
    """
    company_id = await make_company()
    result = await _manual_exporter_result(company_id)
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            result.id, reviewed_by="compliance-1", review_status=VerificationReviewStatus.ACCEPTED
        )

    reads = [(await _company_inputs(company_id)).verifications[0] for _ in range(2)]

    assert reads[0] == reads[1]
    assert reads[0].latest_review_status == "ACCEPTED"
    assert reads[0].latest_review_id is None
    assert reads[0].latest_reviewed_at is None


# ── Company scope and buyer isolation ────────────────────────────────────────


@pytest.mark.parametrize(
    ("entity_type", "verification_type"),
    [
        ("DIRECTOR", "KYC"),
        ("INVOICE", "INVOICE"),
        ("VESSEL", "VESSEL"),
        ("SHIPMENT", "SHIPMENT"),
    ],
)
async def test_checks_on_unlinked_subjects_are_not_company_inputs(entity_type, verification_type):
    """§6.2 invariant 3 — even when their reference happens to equal the company id."""
    company_id = await make_company()
    with _connect() as conn, conn.cursor() as cur:
        _insert_result(
            cur, entity_type=entity_type, entity_reference=company_id,
            verification_type=verification_type,
        )

    assert (await _company_inputs(company_id)).verifications == ()


async def test_buyer_checks_never_enter_company_inputs():
    """§6.2 invariant 4, and decision 9: a buyer check is about the buyer."""
    company_id = await make_company()
    buyer_id = await _deal_buyer(company_id)
    with _connect() as conn, conn.cursor() as cur:
        on_buyer = _insert_result(
            cur, entity_type="BUYER", entity_reference=buyer_id,
            verification_type="BUYER", status="FAILED",
        )
        # A BUYER row mis-keyed to the company id is still not a company input.
        _insert_result(
            cur, entity_type="BUYER", entity_reference=company_id, verification_type="BUYER",
        )
    exporter = await _manual_exporter_result(company_id)

    company = await _company_inputs(company_id)
    buyer = await _buyer_checks(buyer_id)

    assert [v.verification_result_id for v in company.verifications] == [exporter.id]
    assert [v.verification_result_id for v in buyer] == [on_buyer]
    assert buyer[0].entity_type == "BUYER"
    assert buyer[0].status == "FAILED"


async def test_a_buyer_with_no_checks_is_an_empty_tuple():
    company_id = await make_company()
    buyer_id = await _deal_buyer(company_id)

    assert await _buyer_checks(buyer_id) == ()


# ── Errors ───────────────────────────────────────────────────────────────────


async def test_an_unknown_company_raises_the_existing_not_found_error():
    with pytest.raises(ExporterProfileNotFoundError):
        await _company_inputs(uuid.uuid4())


async def test_an_unknown_buyer_is_a_404():
    with pytest.raises(ComplianceInputsBuyerNotFoundError) as caught:
        await _buyer_checks(uuid.uuid4())
    assert caught.value.status_code == 404


async def test_a_company_id_is_not_a_buyer_id():
    company_id = await make_company()
    with pytest.raises(ComplianceInputsBuyerNotFoundError):
        await _buyer_checks(company_id)


# ── Read-only ────────────────────────────────────────────────────────────────


async def test_the_reader_does_not_flush_commit_or_touch_pending_work():
    company_id = await make_company()
    buyer_id = await _deal_buyer(company_id)
    async with db_services.AsyncSessionLocal() as db:
        flushes: list[object] = []
        commits: list[object] = []
        event.listen(db.sync_session, "after_flush", lambda *a: flushes.append(a))
        event.listen(db.sync_session, "after_commit", lambda *a: commits.append(a))
        pending = ScreeningReviewItem(
            customer_id=company_id, item_key="website-reviewed", status="PASSED"
        )
        db.add(pending)

        inputs = await ComplianceInputsService(db).company_inputs(company_id)
        await ComplianceInputsService(db).buyer_checks(buyer_id)

        assert flushes == []
        assert commits == []
        assert pending in db.new, "the caller's unflushed work must stay unflushed"
        assert inputs.screening_items[0].status is None, "only flushed state is read"
        await db.rollback()

    async with db_services.AsyncSessionLocal() as db:
        written = await db.scalar(
            select(ScreeningReviewItem.id).where(ScreeningReviewItem.customer_id == company_id)
        )
    assert written is None


async def test_the_reader_takes_no_lock():
    """With a read still open in its transaction, another connection can lock everything it read."""
    company_id = await make_company()
    result = await _manual_exporter_result(company_id)
    async with db_services.AsyncSessionLocal() as db:
        await ScreeningReviewService(db).upsert_review_item(
            company_id, item_key="website-reviewed", status="PASSED", comment=None, actor_id="a"
        )

    async with db_services.AsyncSessionLocal() as db:
        await ComplianceInputsService(db).company_inputs(company_id)
        assert db.in_transaction()
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM onboarding.exporter_profile WHERE customer_id = %s "
                "FOR UPDATE NOWAIT",
                (str(company_id),),
            )
            cur.execute(
                "SELECT 1 FROM onboarding.verification_result WHERE id = %s FOR UPDATE NOWAIT",
                (str(result.id),),
            )
            cur.execute(
                "SELECT 1 FROM onboarding.screening_review_item WHERE customer_id = %s "
                "FOR UPDATE NOWAIT",
                (str(company_id),),
            )
            conn.rollback()
        await db.rollback()


# ── Writers take FOR SHARE on the company (§6.2 invariant 6) ─────────────────


async def _waits_while_company_is_locked(company_id: uuid.UUID, mode: str, write) -> None:
    """Hold the company row in `mode` on another connection; `write` must wait for it."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM onboarding.exporter_profile WHERE customer_id = %s {mode}",
                (str(company_id),),
            )
        task = asyncio.create_task(write())
        done, _ = await asyncio.wait({task}, timeout=_BLOCKED_AFTER_SECONDS)
        assert not done, f"the write finished while the company was held {mode}"
    finally:
        conn.rollback()
        conn.close()
    await asyncio.wait_for(task, timeout=30)


async def _finishes_while_company_is_locked(company_id: uuid.UUID, mode: str, write) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM onboarding.exporter_profile WHERE customer_id = %s {mode}",
                (str(company_id),),
            )
        await asyncio.wait_for(write(), timeout=_BLOCKED_AFTER_SECONDS * 4)
    finally:
        conn.rollback()
        conn.close()


async def test_a_screening_decision_waits_behind_the_background_check_lock():
    company_id = await make_company()

    async def write():
        async with db_services.AsyncSessionLocal() as db:
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key="website-reviewed", status="PASSED", comment=None,
                actor_id="a",
            )

    await _waits_while_company_is_locked(company_id, "FOR UPDATE", write)


async def test_a_screening_decision_takes_share_not_just_the_foreign_keys_key_share():
    """`FOR NO KEY UPDATE` lets the foreign key's `FOR KEY SHARE` through but not `FOR SHARE`,
    so waiting here proves the explicit share lock — not only the FK — is taken."""
    company_id = await make_company()

    async def write():
        async with db_services.AsyncSessionLocal() as db:
            await ScreeningReviewService(db).upsert_review_item(
                company_id, item_key="website-reviewed", status="PASSED", comment=None,
                actor_id="a",
            )

    await _waits_while_company_is_locked(company_id, "FOR NO KEY UPDATE", write)


async def test_an_exporter_verification_result_waits_behind_the_background_check_lock():
    company_id = await make_company()
    await _waits_while_company_is_locked(
        company_id, "FOR UPDATE", lambda: _manual_exporter_result(company_id)
    )
    assert len((await _company_inputs(company_id)).verifications) == 1


async def test_a_review_of_an_exporter_result_waits_behind_the_background_check_lock():
    company_id = await make_company()
    result = await _manual_exporter_result(company_id)

    async def write():
        async with db_services.AsyncSessionLocal() as db:
            await VerificationService(db).record_review(
                result.id, reviewed_by="c", review_status=VerificationReviewStatus.ACCEPTED
            )

    await _waits_while_company_is_locked(company_id, "FOR UPDATE", write)


async def test_writers_share_the_lock_rather_than_excluding_each_other():
    """Share locks do not conflict: a writer is never held up by another writer's lock."""
    company_id = await make_company()
    await _finishes_while_company_is_locked(
        company_id, "FOR SHARE", lambda: _manual_exporter_result(company_id)
    )


async def test_a_check_on_another_subject_takes_no_company_lock():
    """Only company-scoped inputs serialise against the background check — even a
    DIRECTOR check whose reference happens to equal the company id."""
    company_id = await make_company()

    async def write():
        async with db_services.AsyncSessionLocal() as db:
            await VerificationService(db).trigger_verification(
                VerificationType.KYC,
                VerificationEntityType.DIRECTOR,
                company_id,
                provider="manual",
                payload={"status": "PASSED"},
                actor_id="tester",
            )

    await _finishes_while_company_is_locked(company_id, "FOR UPDATE", write)
