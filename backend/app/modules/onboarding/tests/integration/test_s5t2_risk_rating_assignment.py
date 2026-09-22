"""S5T2 — assign_risk_rating application-service integration tests.

The core S5T2 deliverable (the calculation itself) is unit-tested in
tests/unit/test_s5t2_risk_rating.py without a database. These tests instead
cover the thin application wrapper that pulls inputs off a persisted
onboarding_request + ubo_records and persists the result, following the same
real-database pattern as test_s5t1_screening_result.py — including not
wiping rows before/after each test, since onboarding_event is append-only
(DELETE is rejected by public.prevent_mutation()) and RESTRICTs deletion of
its parent onboarding_request. Every row uses a fresh random UUID instead.

Acceptance criteria covered:
  AC1  The calculated risk_rating and risk_rating_factors are persisted onto
       onboarding_request, and status advances to Risk Rated.
  AC2  UBO PEP status is read from the persisted ubo_record rows, not passed
       in by the caller.
  AC3  A risk_rating_assigned onboarding_event is written.
  AC4  A call from any status other than Risk Rating In Progress is rejected.
  AC5  The write-once risk_rating_factors column's DB-level immutability is
       translated into a clear domain exception.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.modules.onboarding.application.risk_rating_assignment_service import (
    assign_risk_rating,
)
from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRequestStatus,
    OnboardingRiskRating,
    OnboardingScreeningResult,
    UboControlType,
    UboKycResult,
    UboPepStatus,
)
from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.modules.onboarding.domain.policies.risk_rating_service import RiskRatingService
from app.modules.onboarding.exceptions import (
    IllegalOnboardingTransitionError,
    OnboardingFieldAlreadySetError,
)
from app.modules.onboarding.infrastructure.risk_rating_config_loader import (
    load_risk_rating_service,
)
from app.platform.database import services as db_services
from app.shared.exceptions import NotFoundError

_PREFIX = "s5t2_"


def _key() -> str:
    return f"{_PREFIX}{uuid.uuid4().hex[:12]}"


async def _make_request(
    *,
    status: OnboardingRequestStatus = OnboardingRequestStatus.RISK_RATING_IN_PROGRESS,
    industry_code: str | None = "DNFBP",
    declared_monthly_volume_usd: int | None = 300_000,
    incorporation_country: str = "US",
    screening_result: OnboardingScreeningResult | None = OnboardingScreeningResult.CLEAR,
) -> uuid.UUID:
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
                legal_name="S5T2 Test Corp",
                registration_number="REG-S5T2",
                incorporation_country=incorporation_country,
                registered_address={"country": incorporation_country},
                industry_code=industry_code,
                declared_monthly_volume_usd=declared_monthly_volume_usd,
                initial_user_id="user_1",
                screening_result=screening_result,
            )
        )
        await db.commit()
    return request_id


async def _add_ubo(request_id: uuid.UUID, *, pep_status: UboPepStatus | None) -> None:
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            UboRecord(
                onboarding_request_id=request_id,
                first_name="Test",
                last_name="Ubo",
                control_type=UboControlType.DIRECT_OWNERSHIP,
                kyc_result=UboKycResult.VERIFIED,
                pep_status=pep_status,
            )
        )
        await db.commit()


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


@pytest.fixture()
def risk_rating_service() -> RiskRatingService:
    return load_risk_rating_service()


# ── AC1 / AC3 — persistence + event ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_risk_rating_persists_rating_and_advances_status(risk_rating_service):
    request_id = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        updated = await assign_risk_rating(db, request_id, risk_rating_service)

    assert updated.status == OnboardingRequestStatus.RISK_RATED
    assert updated.risk_rating == OnboardingRiskRating.HIGH  # DNFBP + medium country risk
    assert updated.risk_rating_factors is not None
    assert updated.risk_rating_factors["edd_required"] is True
    assert "DNFBP" in updated.risk_rating_factors["edd_reason"]
    assert updated.risk_rating_factors["risk_rating"] == "HIGH"

    # Real edd_required/edd_reason columns (added alongside this rename) are
    # populated from the same RiskRatingResult, not only embedded in the JSON.
    assert updated.edd_required is True
    assert updated.edd_reason is not None
    assert "DNFBP" in updated.edd_reason
    assert updated.edd_reason == updated.risk_rating_factors["edd_reason"]

    events = await _events_for(request_id)
    assert len(events) == 1
    assert events[0].event_type == "risk_rating_assigned"
    assert events[0].to_status == OnboardingRequestStatus.RISK_RATED.value
    assert events[0].event_metadata["edd_required"] is True


# ── AC2 — UBO PEP status read from persisted ubo_records ────────────────────


@pytest.mark.asyncio
async def test_assign_risk_rating_reads_pep_status_from_ubo_records(risk_rating_service):
    request_id = await _make_request(industry_code="PROFESSIONAL_SERVICES", declared_monthly_volume_usd=10_000)
    await _add_ubo(request_id, pep_status=UboPepStatus.NOT_PEP)
    await _add_ubo(request_id, pep_status=UboPepStatus.PEP)

    async with db_services.AsyncSessionLocal() as db:
        updated = await assign_risk_rating(db, request_id, risk_rating_service)

    factor_names = {f["factor"]: f for f in updated.risk_rating_factors["factors"]}
    assert factor_names["pep_status"]["value"] is True
    assert factor_names["ubo_count"]["value"] == 2
    assert updated.risk_rating_factors["edd_required"] is True


@pytest.mark.asyncio
async def test_assign_risk_rating_low_risk_profile(risk_rating_service):
    request_id = await _make_request(
        industry_code="PROFESSIONAL_SERVICES",
        declared_monthly_volume_usd=5_000,
    )
    await _add_ubo(request_id, pep_status=UboPepStatus.NOT_PEP)

    async with db_services.AsyncSessionLocal() as db:
        updated = await assign_risk_rating(db, request_id, risk_rating_service)

    assert updated.risk_rating == OnboardingRiskRating.LOW
    assert updated.risk_rating_factors["edd_required"] is False
    assert updated.edd_required is False
    assert updated.edd_reason is None


# ── AC4 — illegal precondition ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_from_wrong_status_raises_illegal_transition(risk_rating_service):
    request_id = await _make_request(status=OnboardingRequestStatus.SCREENING_COMPLETE)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(IllegalOnboardingTransitionError):
            await assign_risk_rating(db, request_id, risk_rating_service)


@pytest.mark.asyncio
async def test_unknown_onboarding_id_raises_not_found(risk_rating_service):
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(NotFoundError):
            await assign_risk_rating(db, uuid.uuid4(), risk_rating_service)


# ── AC5 — write-once risk_rating_factors: DB trigger translated ─────────────


@pytest.mark.asyncio
async def test_immutable_risk_rating_factors_guard_is_translated_to_domain_error(risk_rating_service):
    request_id = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        await assign_risk_rating(db, request_id, risk_rating_service)

    # Reset status only (not protected by the immutability trigger) to bypass
    # the higher-level precondition and reach the DB trigger directly. Also
    # add a UBO so the recalculated risk_rating_factors JSON is *different*
    # from what is already stored -- the trigger only fires on a genuine
    # change (`IS DISTINCT FROM`), and this calculation is deterministic, so
    # re-running it unchanged would harmlessly reproduce the same JSON.
    await _add_ubo(request_id, pep_status=UboPepStatus.PEP)
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE onboarding.onboarding_request SET status = 'RISK_RATING_IN_PROGRESS' WHERE id = :id"
            ),
            {"id": str(request_id)},
        )
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(OnboardingFieldAlreadySetError) as exc_info:
            await assign_risk_rating(db, request_id, risk_rating_service)
    assert exc_info.value.field == "risk_rating_factors"


# ── Determinism holds through the full persistence path too ─────────────────


@pytest.mark.asyncio
async def test_assignment_is_deterministic_across_two_equivalent_onboardings(risk_rating_service):
    request_id_a = await _make_request()
    request_id_b = await _make_request()

    async with db_services.AsyncSessionLocal() as db:
        result_a = await assign_risk_rating(db, request_id_a, risk_rating_service)
    async with db_services.AsyncSessionLocal() as db:
        result_b = await assign_risk_rating(db, request_id_b, risk_rating_service)

    assert result_a.risk_rating == result_b.risk_rating
    assert result_a.risk_rating_factors["score"] == result_b.risk_rating_factors["score"]
