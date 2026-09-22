"""S5T1 — process_screening_result integration tests.

All tests run against a real database. Unlike test_s1t4_kyb_vendor_registry.py
(whose table is ordinarily mutable), these tests do **not** wipe rows before
or after each test: ``onboarding_event`` is append-only and its
``public.prevent_mutation()`` trigger rejects DELETE as well as UPDATE (see
migration ``a0b1c2d3e4f5_shared_immutability_function``), and
``onboarding_event.onboarding_request_id`` is a ``ON DELETE RESTRICT`` foreign
key, so an ``onboarding_request`` row that has ever had an event written
against it cannot be deleted either. Every row this suite creates therefore
carries a fresh random UUID and a unique ``idempotency_key`` (prefixed
``s5t1_`` for identification only), which is enough for order-independence
without ever needing a delete.

Acceptance criteria covered:
  AC1  A clear result transitions the onboarding to Screening Complete with
       screening_reference_id stored.
  AC2  A hard_block result transitions directly to Rejected with the
       rejection reason and rejection_category populated.
  AC3  A review_required result transitions to Under Review.
  AC4  Every transition writes an onboarding_event row.
  AC5  A call from any status other than Screening In Progress is rejected
       rather than silently guessing a transition.
  AC6  The write-once screening_result column's DB-level immutability is translated
       into a clear domain exception rather than a raw DBAPIError escaping.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.modules.onboarding.application.screening_result_service import (
    process_screening_result,
)
from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
    OnboardingScreeningResult,
)
from app.modules.onboarding.exceptions import (
    IllegalOnboardingTransitionError,
    OnboardingFieldAlreadySetError,
)
from app.platform.database import services as db_services
from app.shared.exceptions import NotFoundError

_PREFIX = "s5t1_"


def _key() -> str:
    return f"{_PREFIX}{uuid.uuid4().hex[:12]}"


async def _make_request(status: OnboardingRequestStatus = OnboardingRequestStatus.SCREENING_IN_PROGRESS) -> uuid.UUID:
    """Insert a throwaway onboarding_request in the given status and return its id."""
    request_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            OnboardingRequest(
                id=request_id,
                tenant_id=uuid.uuid4(),
                idempotency_key=_key(),
                customer_id=uuid.uuid4(),
                status=status,
                entity_type=OnboardingEntityType.CORPORATION,
                legal_name="S5T1 Test Corp",
                registration_number="REG-S5T1",
                incorporation_country="US",
                registered_address={"country": "US"},
                initial_user_id="user_1",
            )
        )
        await db.commit()
    return request_id


async def _fetch(request_id: uuid.UUID) -> OnboardingRequest:
    async with db_services.AsyncSessionLocal() as db:
        result = await db.execute(select(OnboardingRequest).where(OnboardingRequest.id == request_id))
        return result.scalar_one()


async def _events_for(request_id: uuid.UUID) -> list[OnboardingEvent]:
    async with db_services.AsyncSessionLocal() as db:
        result = await db.execute(
            select(OnboardingEvent).where(OnboardingEvent.onboarding_request_id == request_id)
        )
        return list(result.scalars().all())


# ── AC1 — clear -> Screening Complete ────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear_transitions_to_screening_complete():
    request_id = await _make_request()
    ref_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        updated = await process_screening_result(
            db, request_id, OnboardingScreeningResult.CLEAR, ref_id
        )

    assert updated.status == OnboardingRequestStatus.SCREENING_COMPLETE
    assert updated.screening_reference_id == ref_id
    assert updated.screening_result == OnboardingScreeningResult.CLEAR
    assert updated.rejection_category is None
    assert updated.rejection_reason is None

    events = await _events_for(request_id)
    assert len(events) == 1
    assert events[0].event_type == "screening_result_received"
    assert events[0].from_status == OnboardingRequestStatus.SCREENING_IN_PROGRESS.value
    assert events[0].to_status == OnboardingRequestStatus.SCREENING_COMPLETE.value


@pytest.mark.asyncio
async def test_clear_accepts_lowercase_string_result():
    request_id = await _make_request()
    ref_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        updated = await process_screening_result(db, request_id, "clear", str(ref_id))

    assert updated.status == OnboardingRequestStatus.SCREENING_COMPLETE


# ── AC2 — hard_block -> Rejected directly ────────────────────────────────────


@pytest.mark.asyncio
async def test_hard_block_transitions_directly_to_rejected():
    request_id = await _make_request()
    ref_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        updated = await process_screening_result(
            db,
            request_id,
            OnboardingScreeningResult.HARD_BLOCK,
            ref_id,
            rejection_reason="Primary finding: OFAC SDN match on entity.",
        )

    assert updated.status == OnboardingRequestStatus.REJECTED
    assert updated.rejection_category == OnboardingRejectionCategory.SCREENING_BLOCK
    assert updated.rejection_reason == "Primary finding: OFAC SDN match on entity."
    assert updated.completed_at is not None
    assert updated.screening_result == OnboardingScreeningResult.HARD_BLOCK

    events = await _events_for(request_id)
    assert events[0].to_status == OnboardingRequestStatus.REJECTED.value


@pytest.mark.asyncio
async def test_hard_block_without_explicit_reason_uses_default():
    request_id = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        updated = await process_screening_result(
            db, request_id, OnboardingScreeningResult.HARD_BLOCK, uuid.uuid4()
        )

    assert updated.rejection_reason  # non-empty default message
    assert updated.rejection_category == OnboardingRejectionCategory.SCREENING_BLOCK


# ── AC3 — review_required -> Under Review ────────────────────────────────────


@pytest.mark.asyncio
async def test_review_required_transitions_to_under_review():
    request_id = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        updated = await process_screening_result(
            db, request_id, OnboardingScreeningResult.REVIEW_REQUIRED, uuid.uuid4()
        )

    assert updated.status == OnboardingRequestStatus.UNDER_REVIEW
    assert updated.rejection_category is None
    events = await _events_for(request_id)
    assert events[0].to_status == OnboardingRequestStatus.UNDER_REVIEW.value


# ── AC5 — illegal precondition ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_from_wrong_status_raises_illegal_transition():
    request_id = await _make_request(status=OnboardingRequestStatus.DRAFT)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(IllegalOnboardingTransitionError):
            await process_screening_result(
                db, request_id, OnboardingScreeningResult.CLEAR, uuid.uuid4()
            )


@pytest.mark.asyncio
async def test_second_call_after_success_raises_illegal_transition():
    request_id = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        await process_screening_result(db, request_id, OnboardingScreeningResult.CLEAR, uuid.uuid4())

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(IllegalOnboardingTransitionError):
            await process_screening_result(db, request_id, OnboardingScreeningResult.CLEAR, uuid.uuid4())


@pytest.mark.asyncio
async def test_unknown_onboarding_id_raises_not_found():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(NotFoundError):
            await process_screening_result(
                db, uuid.uuid4(), OnboardingScreeningResult.CLEAR, uuid.uuid4()
            )


# ── AC6 — write-once screening_result: DB trigger translated to a domain error ────


@pytest.mark.asyncio
async def test_immutable_screening_result_guard_is_translated_to_domain_error():
    """Defense-in-depth: even if status were reset out-of-band, the DB-level
    write-once trigger on screening_result still protects the column, and this
    service surfaces that as OnboardingFieldAlreadySetError, not a raw
    DBAPIError.
    """
    request_id = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        await process_screening_result(db, request_id, OnboardingScreeningResult.CLEAR, uuid.uuid4())

    # Reset status only (not protected by the immutability trigger) to bypass
    # the higher-level precondition and reach the DB trigger directly.
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE onboarding.onboarding_request SET status = 'SCREENING_IN_PROGRESS' WHERE id = :id"
            ),
            {"id": str(request_id)},
        )
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(OnboardingFieldAlreadySetError) as exc_info:
            await process_screening_result(
                db, request_id, OnboardingScreeningResult.REVIEW_REQUIRED, uuid.uuid4()
            )
    assert exc_info.value.field == "screening_result"
