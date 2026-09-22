"""Integration tests for S7T2: the read-only onboarding query interface
(`OnboardingQueryService`).

Same conventions as `test_s7t1_onboarding_service_api.py`: real Postgres, no
shared wipe fixture, each test isolates itself by construction rather than by
resetting shared tables — with one exception, explained below.

**Isolation strategy per operation:**

* `get_pending_approvals` / `get_under_review_onboardings` scan by *status*
  across the whole `onboarding_request` table. Nothing else in this codebase
  ever creates a row in `PENDING_COMPLIANCE_APPROVAL` or `UNDER_REVIEW`
  (`test_s1t1_orchestration_schema.py`'s direct-SQL fixtures only ever insert
  `DRAFT`/`ACTIVE`), so these tests look up their own row by id inside
  whatever the full result list contains, rather than asserting the list's
  total length.

* `get_onboarding_statistics` filters by `initiated_at` range, scoped to a
  synthetic year-2019 date window nothing else in the suite writes into.
  Since this suite runs against a real, persistent Postgres with no per-test
  rollback, re-running *this file* twice against a database that was never
  reset would double this test's own count the second time — so it deletes
  the exact `onboarding_request` rows it created in a `finally` block, via
  `_cleanup_eventless_requests`. That helper only works because this test's
  rows have no `onboarding_event` children.

* `get_time_in_state_metrics` aggregates `onboarding_event` rows
  **globally**, with no per-tenant/per-request scope (matching the doc's
  operation, which has none either) — and `onboarding_event` is genuinely
  append-only forever (a DB trigger rejects UPDATE/DELETE outright, proven by
  `test_onboarding_event_append_only` in `test_s1t1_orchestration_schema.py`),
  so its test's two synthetic requests-with-events can never be cleaned up
  and permanently add two samples to the `RISK_RATED` bucket every time this
  file runs. Rather than fight that, the test embraces it: it reads the
  metric once *before* inserting its two known intervals (100s, 300s) and
  once *after*, and asserts the exact, hand-checkable **delta** — sample
  count up by 2, total duration up by exactly 400 seconds — which holds
  regardless of how many previous runs' samples are already sitting in the
  table. The percentile *formula* itself is checked precisely and
  deterministically in a separate, DB-free unit test
  (`test_percentile_matches_numpy_style_linear_interpolation`) against the
  private `_percentile` helper.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.onboarding_query_service import (
    OnboardingQueryService,
    _percentile,
)
from app.modules.onboarding.application.onboarding_request_service import (
    OnboardingRequestService,
)
from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRequestStatus,
    OnboardingRiskRating,
)
from app.modules.onboarding.domain.onboarding_request_views import TimeInStateMetric
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.platform.database import services as db_services

# No module-level `pytestmark = pytest.mark.asyncio` here (unlike its S7T1
# sibling): this file has one synchronous unit test
# (`test_percentile_matches_numpy_style_linear_interpolation`), and
# `asyncio_mode = "auto"` (pyproject.toml) already detects every `async def
# test_*` in this file without it.


def _address() -> dict:
    return {"street": "1 Test St", "city": "Testville", "country": "US"}


def _empty_document_requirements() -> DocumentRequirementsService:
    return DocumentRequirementsService(
        {"version": "1.0", "profiles": [], "conditional_rules": [], "validity_periods": {}}
    )


async def _cleanup_eventless_requests(db: AsyncSession, request_ids: list[uuid.UUID]) -> None:
    """Delete `onboarding_request` rows that have no `onboarding_event` children,
    so re-running this file against a never-reset Postgres does not double a
    global-count assertion (e.g. `get_onboarding_statistics`'s date-range total).

    Only safe for rows with no events: `onboarding_event` is genuinely
    append-only forever (a DB trigger rejects UPDATE/DELETE outright — see
    `test_onboarding_event_append_only` in `test_s1t1_orchestration_schema.py`
    — this is correct audit-log behaviour, not a gap to work around), and a
    request row cannot be deleted while an event's `ON DELETE RESTRICT`
    foreign key still points at it. `test_get_time_in_state_metrics_...`
    below creates rows *with* events and therefore cannot use this helper —
    see its own docstring for how it stays safe to re-run instead.
    """
    if not request_ids:
        return
    await db.execute(delete(OnboardingRequest).where(OnboardingRequest.id.in_(request_ids)))
    await db.commit()


def _bare_request(
    *,
    status: OnboardingRequestStatus,
    legal_name: str,
    risk_rating: OnboardingRiskRating | None = None,
    risk_rating_factors: dict | None = None,
    rejection_reason: str | None = None,
    initiated_at: datetime | None = None,
    industry_code: str | None = None,
    incorporation_country: str = "US",
) -> OnboardingRequest:
    """A minimally-valid `OnboardingRequest` row, built directly (bypassing
    `OnboardingRequestService.initiate_onboarding`) so tests can put a row
    straight into a state the service's own state machine would never reach
    on its own (e.g. `PENDING_COMPLIANCE_APPROVAL` with no S5 risk-rating
    activity to have put it there)."""
    return OnboardingRequest(
        tenant_id=uuid.uuid4(),
        idempotency_key=str(uuid.uuid4()),
        customer_id=uuid.uuid4(),
        status=status,
        entity_type=OnboardingEntityType.CORPORATION,
        legal_name=legal_name,
        registration_number=f"REG-{uuid.uuid4().hex[:8]}",
        incorporation_country=incorporation_country,
        registered_address=_address(),
        initial_user_id="founder@example.com",
        risk_rating=risk_rating,
        risk_rating_factors=risk_rating_factors,
        rejection_reason=rejection_reason,
        industry_code=industry_code,
        initiated_at=initiated_at,
        last_activity_at=initiated_at,
    )


# ── Pending approvals ─────────────────────────────────────────────────────────


async def test_get_pending_approvals_includes_own_row_with_correct_fields():
    async with db_services.AsyncSessionLocal() as db:
        request = _bare_request(
            status=OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL,
            legal_name="Pending Approval Corp",
            risk_rating=OnboardingRiskRating.HIGH,
            risk_rating_factors={"edd_reason": "DNFBP sector"},
        )
        db.add(request)
        await db.commit()
        await db.refresh(request)

        query_svc = OnboardingQueryService(db)
        results = await query_svc.get_pending_approvals()

    entry = next(e for e in results if e.onboarding_id == request.id)
    assert entry.legal_name == "Pending Approval Corp"
    assert entry.risk_rating == OnboardingRiskRating.HIGH
    assert entry.edd_reason == "DNFBP sector"
    assert entry.time_waiting_seconds >= 0

    # Sorted by time waiting, longest first.
    waits = [e.time_waiting_seconds for e in results]
    assert waits == sorted(waits, reverse=True)


async def test_get_pending_approvals_time_waiting_uses_transition_event_when_present():
    async with db_services.AsyncSessionLocal() as db:
        request = _bare_request(
            status=OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL,
            legal_name="Long Waiting Corp",
            risk_rating=OnboardingRiskRating.CRITICAL,
        )
        db.add(request)
        await db.flush()

        entered_at = datetime.now(UTC) - timedelta(hours=5)
        db.add(
            OnboardingEvent(
                onboarding_request_id=request.id,
                event_type="state_transition",
                from_status=OnboardingRequestStatus.RISK_RATED.value,
                to_status=OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL.value,
                created_at=entered_at,
            )
        )
        await db.commit()

        query_svc = OnboardingQueryService(db)
        results = await query_svc.get_pending_approvals()

    entry = next(e for e in results if e.onboarding_id == request.id)
    # ~5 hours = 18000 seconds; allow slack for test execution time.
    assert 17_990 <= entry.time_waiting_seconds <= 18_600


# ── Under review ──────────────────────────────────────────────────────────────


async def test_get_under_review_includes_own_row_with_reason():
    async with db_services.AsyncSessionLocal() as db:
        request = _bare_request(
            status=OnboardingRequestStatus.UNDER_REVIEW,
            legal_name="Under Review Corp",
            rejection_reason="Adverse media match requires investigation",
        )
        db.add(request)
        await db.commit()
        await db.refresh(request)

        query_svc = OnboardingQueryService(db)
        results = await query_svc.get_under_review_onboardings()

    entry = next(e for e in results if e.onboarding_id == request.id)
    assert entry.legal_name == "Under Review Corp"
    assert entry.reason == "Adverse media match requires investigation"
    assert entry.time_in_review_seconds >= 0


# ── Evidence package ──────────────────────────────────────────────────────────


async def test_get_evidence_package_assembles_full_record_unredacted():
    async with db_services.AsyncSessionLocal() as db:
        onboarding_svc = OnboardingRequestService(
            db, document_requirements=_empty_document_requirements()
        )
        request, _ = await onboarding_svc.initiate_onboarding(
            tenant_id=uuid.uuid4(),
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="Evidence Corp",
            registration_number="REG-EVID-1",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_email="founder@evidence.example",
            idempotency_key=str(uuid.uuid4()),
            tax_identification_number="99-8887777",
        )
        await onboarding_svc.submit_ubo_declaration(
            request.id,
            ubo_details=[
                {
                    "first_name": "Evidence",
                    "last_name": "Owner",
                    "control_type": "DIRECT_OWNERSHIP",
                    "identification_number": "PASSPORT-EVID-1",
                }
            ],
        )

        query_svc = OnboardingQueryService(db)
        package = await query_svc.get_onboarding_evidence_package(request.id)

    assert package.detail.onboarding_id == request.id
    assert package.detail.legal_name == "Evidence Corp"
    # Evidence packages are compliance-officer artifacts: unredacted regardless
    # of who calls this operation (see OnboardingQueryService docstring).
    assert package.detail.sensitive_fields_redacted is False
    assert package.detail.tax_identification_number == "99-8887777"
    assert package.detail.ubo_records[0].identification_number == "PASSPORT-EVID-1"
    # Epic 3.2 does not exist in this codebase and is out of scope per the
    # isolation constraint — always None, never faked.
    assert package.screening_evidence is None


# ── Statistics ────────────────────────────────────────────────────────────────


async def test_get_onboarding_statistics_aggregates_correctly_for_date_range():
    window_start = datetime(2019, 6, 1, tzinfo=UTC)
    window_end = datetime(2019, 6, 30, tzinfo=UTC)
    inside = window_start + timedelta(days=10)
    outside = datetime(2019, 7, 15, tzinfo=UTC)

    rows = [
        _bare_request(
            status=OnboardingRequestStatus.ACTIVE,
            legal_name="Stats Corp US High DNFBP",
            risk_rating=OnboardingRiskRating.HIGH,
            industry_code="DNFBP",
            incorporation_country="US",
            initiated_at=inside,
        ),
        _bare_request(
            status=OnboardingRequestStatus.ACTIVE,
            legal_name="Stats Corp US Low Standard",
            risk_rating=OnboardingRiskRating.LOW,
            industry_code="STANDARD",
            incorporation_country="US",
            initiated_at=inside,
        ),
        _bare_request(
            status=OnboardingRequestStatus.REJECTED,
            legal_name="Stats Corp IN High DNFBP",
            risk_rating=OnboardingRiskRating.HIGH,
            industry_code="DNFBP",
            incorporation_country="IN",
            initiated_at=inside,
        ),
        # Outside the window — must not be counted.
        _bare_request(
            status=OnboardingRequestStatus.ACTIVE,
            legal_name="Stats Corp Outside Window",
            risk_rating=OnboardingRiskRating.LOW,
            industry_code="STANDARD",
            incorporation_country="US",
            initiated_at=outside,
        ),
    ]

    async with db_services.AsyncSessionLocal() as db:
        for row in rows:
            db.add(row)
        await db.commit()

        try:
            query_svc = OnboardingQueryService(db)
            stats = await query_svc.get_onboarding_statistics(window_start, window_end)

            assert stats.total == 3
            assert stats.by_status == {"ACTIVE": 2, "REJECTED": 1}
            assert stats.by_risk_rating == {"HIGH": 2, "LOW": 1}
            assert stats.by_sector == {"DNFBP": 2, "STANDARD": 1}
            assert stats.by_country == {"US": 2, "IN": 1}
        finally:
            # This test asserts an exact global count over a fixed date
            # window — leaving these rows behind would double the count the
            # next time this file runs against the same live database.
            await _cleanup_eventless_requests(db, [row.id for row in rows])


# ── Time-in-state metrics ─────────────────────────────────────────────────────


def test_percentile_matches_numpy_style_linear_interpolation():
    """Pure unit test of the percentile helper `get_time_in_state_metrics` uses.

    `onboarding_event` is genuinely append-only forever (a DB trigger rejects
    UPDATE/DELETE outright — see `test_onboarding_event_append_only`), so an
    integration test cannot reset the table between runs. The exact,
    hand-checkable expected value for the percentile *formula* therefore
    belongs here, against the pure function directly — no DB, no
    accumulation concern, safe to run any number of times.

    Two sorted samples [100, 300]: rank = (2-1)*0.95 = 0.95, floor=0, ceil=1,
    p95 = 100 + (300-100)*0.95 = 290.0. A single-sample list returns that
    sample verbatim for any percentile.
    """
    assert _percentile([100.0, 300.0], 0.95) == pytest.approx(290.0)
    assert _percentile([300.0, 100.0], 0.95) == pytest.approx(290.0)  # order-independent
    assert _percentile([42.0], 0.95) == pytest.approx(42.0)
    assert _percentile([], 0.95) == 0.0
    # p50 of [10, 20, 30, 40]: rank = 3*0.5 = 1.5, floor=1, ceil=2,
    # p50 = 20 + (30-20)*0.5 = 25.0
    assert _percentile([10.0, 20.0, 30.0, 40.0], 0.5) == pytest.approx(25.0)


async def test_get_time_in_state_metrics_known_checkable_average_and_p95():
    """Two fully-controlled onboarding_event sequences, giving exactly two
    completed RISK_RATED intervals: 100s and 300s — added on top of whatever
    RISK_RATED samples already exist in this permanent, append-only table.

    `onboarding_event` cannot be deleted (see
    `test_percentile_matches_numpy_style_linear_interpolation`'s docstring),
    so re-running this file against the same live database accumulates
    RISK_RATED samples across runs — exactly as a real audit log should. The
    checkable expected value here is therefore not the absolute
    average/p95/count (which grows every run) but the arithmetic *delta* a
    correct implementation must produce: `sample_count` up by exactly 2, and
    the underlying *sum* of durations (`average_seconds * sample_count`) up
    by exactly 100 + 300 = 400 seconds, computed by reading the metric once
    before and once after inserting the two known intervals.
    """
    t0 = datetime.now(UTC) - timedelta(days=1)

    async with db_services.AsyncSessionLocal() as db:
        query_svc = OnboardingQueryService(db)
        before = _risk_rated_metric(await query_svc.get_time_in_state_metrics())
        before_sum = (before.average_seconds or 0.0) * before.sample_count

        request_a = _bare_request(
            status=OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL,
            legal_name="Timing Corp A",
        )
        request_b = _bare_request(
            status=OnboardingRequestStatus.APPROVED, legal_name="Timing Corp B"
        )
        db.add_all([request_a, request_b])
        await db.flush()

        # Request A: enters RISK_RATED at t0, leaves to PENDING_COMPLIANCE_APPROVAL
        # 100 seconds later.
        db.add_all(
            [
                OnboardingEvent(
                    onboarding_request_id=request_a.id,
                    event_type="state_transition",
                    from_status=OnboardingRequestStatus.RISK_RATING_IN_PROGRESS.value,
                    to_status=OnboardingRequestStatus.RISK_RATED.value,
                    created_at=t0,
                ),
                OnboardingEvent(
                    onboarding_request_id=request_a.id,
                    event_type="state_transition",
                    from_status=OnboardingRequestStatus.RISK_RATED.value,
                    to_status=OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL.value,
                    created_at=t0 + timedelta(seconds=100),
                ),
            ]
        )

        # Request B: enters RISK_RATED at t0 + 1000s, leaves to APPROVED
        # 300 seconds later.
        t1 = t0 + timedelta(seconds=1000)
        db.add_all(
            [
                OnboardingEvent(
                    onboarding_request_id=request_b.id,
                    event_type="state_transition",
                    from_status=OnboardingRequestStatus.RISK_RATING_IN_PROGRESS.value,
                    to_status=OnboardingRequestStatus.RISK_RATED.value,
                    created_at=t1,
                ),
                OnboardingEvent(
                    onboarding_request_id=request_b.id,
                    event_type="state_transition",
                    from_status=OnboardingRequestStatus.RISK_RATED.value,
                    to_status=OnboardingRequestStatus.APPROVED.value,
                    created_at=t1 + timedelta(seconds=300),
                ),
            ]
        )
        await db.commit()

        metrics = await query_svc.get_time_in_state_metrics()
        after = _risk_rated_metric(metrics)
        after_sum = (after.average_seconds or 0.0) * after.sample_count

        assert after.sample_count == before.sample_count + 2
        assert after_sum - before_sum == pytest.approx(400.0)

        # Every OnboardingRequestStatus member is represented, even with zero samples.
        assert len(metrics) == len(OnboardingRequestStatus)
        active_metric = next(m for m in metrics if m.status == OnboardingRequestStatus.ACTIVE)
        # No test anywhere writes a `to_status=ACTIVE` event with a
        # *following* event (ACTIVE is terminal), so ACTIVE always has
        # zero completed samples.
        assert active_metric.sample_count == 0
        assert active_metric.average_seconds is None
        assert active_metric.p95_seconds is None


def _risk_rated_metric(metrics: list[TimeInStateMetric]) -> TimeInStateMetric:
    return next(m for m in metrics if m.status == OnboardingRequestStatus.RISK_RATED)
