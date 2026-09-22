"""OnboardingQueryService — the S7T2 read-only query interface (Epic 4.1, S7).

Per the doc, this is explicitly a read-only interface *other Epics call into
this module* — Epic 4.3 (Case Management Console) and Epic 5.6 (Continuous
Control Monitoring Dashboard) consume it. That is the correct dependency
direction (onboarding exposing data outward) and does not violate the
isolation constraint scoping this Story to `app.modules.onboarding`,
`app.modules.kyb`, and `app.platform.*` — nothing here calls into Epic 4.3 or
5.6, and nothing here needs to: they would call *this* module.

**Epic 3.2 is the one documented exception, and it is scoped out.** The doc's
evidence-package operation explicitly names a call outward: "the Epic 3.2
screening evidence package (fetched from Epic 3.2's get screening result
API)". Epic 3.2 does not exist in this codebase, and even if it did, importing
it here would violate this Story's isolation constraint (no calls into any
`app.modules.*` outside `onboarding`/`kyb`). `get_onboarding_evidence_package`
therefore returns `screening_evidence=None` with a docstring/field comment
explaining why, rather than faking the call or the module.

All operations here are pure reads against `onboarding`'s own tables — no
row is created, updated, or deleted by this service.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import groupby

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.onboarding_request_service import (
    OnboardingRequestService,
)
from app.modules.onboarding.domain.entities.orchestration_enums import OnboardingRequestStatus
from app.modules.onboarding.domain.onboarding_request_views import (
    EvidencePackage,
    OnboardingStatistics,
    PendingApprovalEntry,
    TimeInStateMetric,
    UnderReviewEntry,
)
from app.modules.onboarding.infrastructure.repositories import (
    OnboardingEventRepository,
    OnboardingRequestRepository,
)
from app.platform.authentication.models import UserRole

logger = structlog.get_logger(__name__)


class OnboardingQueryService:
    """Read-only queries against `onboarding_request` and its children (S7T2)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._requests = OnboardingRequestRepository(db)
        self._events = OnboardingEventRepository(db)
        # Reused for evidence-package assembly only — get_onboarding_detail is
        # itself a pure read; no write path of OnboardingRequestService is
        # exercised from here.
        self._detail_service = OnboardingRequestService(db)

    # ── Pending approvals ────────────────────────────────────────────────────

    async def get_pending_approvals(self) -> list[PendingApprovalEntry]:
        """Onboardings in PENDING_COMPLIANCE_APPROVAL, sorted by time waiting (longest first)."""
        requests = await self._requests.list_by_status(
            OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL
        )
        now = datetime.now(UTC)
        entries: list[PendingApprovalEntry] = []
        for request in requests:
            entered_at = await self._entered_state_at(
                request.id, OnboardingRequestStatus.PENDING_COMPLIANCE_APPROVAL
            )
            anchor = entered_at or request.last_activity_at or request.initiated_at or now
            entries.append(
                PendingApprovalEntry(
                    onboarding_id=request.id,
                    customer_id=request.customer_id,
                    legal_name=request.legal_name,
                    risk_rating=request.risk_rating,
                    edd_reason=_edd_reason(request),
                    time_waiting_seconds=(now - anchor).total_seconds(),
                )
            )
        entries.sort(key=lambda e: e.time_waiting_seconds, reverse=True)
        return entries

    # ── Under review ─────────────────────────────────────────────────────────

    async def get_under_review_onboardings(self) -> list[UnderReviewEntry]:
        """Onboardings in UNDER_REVIEW, with reason and time in review."""
        requests = await self._requests.list_by_status(OnboardingRequestStatus.UNDER_REVIEW)
        now = datetime.now(UTC)
        entries: list[UnderReviewEntry] = []
        for request in requests:
            entered_at = await self._entered_state_at(
                request.id, OnboardingRequestStatus.UNDER_REVIEW
            )
            anchor = entered_at or request.last_activity_at or request.initiated_at or now
            entries.append(
                UnderReviewEntry(
                    onboarding_id=request.id,
                    customer_id=request.customer_id,
                    legal_name=request.legal_name,
                    reason=_edd_reason(request),
                    time_in_review_seconds=(now - anchor).total_seconds(),
                )
            )
        entries.sort(key=lambda e: e.time_in_review_seconds, reverse=True)
        return entries

    async def _entered_state_at(
        self, onboarding_id: uuid.UUID, status: OnboardingRequestStatus
    ) -> datetime | None:
        """The `created_at` of the most recent event that moved the request into `status`.

        Falls back to `None` (caller uses `last_activity_at`/`initiated_at`
        instead) when no `onboarding_event` row records the transition — e.g.
        a row seeded directly rather than through `OnboardingRequestService`.
        """
        events = await self._events.list_by_request(onboarding_id)
        for event in reversed(events):
            if event.to_status == status.value:
                return event.created_at
        return None

    # ── Evidence package ─────────────────────────────────────────────────────

    async def get_onboarding_evidence_package(self, onboarding_id: uuid.UUID) -> EvidencePackage:
        """The full aggregated onboarding record, for compliance/regulatory use.

        Unredacted: an evidence package is inherently a compliance-officer
        artifact, so the underlying detail is assembled with
        `UserRole.COMPLIANCE` regardless of caller — restricting the
        *evidence package operation itself* to compliance-officer callers is a
        router/access-control concern one layer up (out of scope here; no
        router exists in this Story).
        """
        detail = await self._detail_service.get_onboarding_detail(
            onboarding_id, requesting_role=UserRole.COMPLIANCE
        )
        return EvidencePackage(detail=detail, screening_evidence=None)

    # ── Statistics ───────────────────────────────────────────────────────────

    async def get_onboarding_statistics(
        self, date_from: datetime, date_to: datetime
    ) -> OnboardingStatistics:
        """Aggregate counts by status, risk_rating, sector, and country for a date range.

        "Sector" and "country" are `industry_code` / `incorporation_country`
        on the actual S1 schema (the doc calls them `sector_code` /
        `registration_country` — see the S7 build report's field-naming
        reconciliation).
        """
        requests = await self._requests.list_initiated_between(date_from, date_to)
        return OnboardingStatistics(
            date_from=date_from,
            date_to=date_to,
            total=len(requests),
            by_status=dict(Counter(r.status.value for r in requests)),
            by_risk_rating=dict(
                Counter(r.risk_rating.value for r in requests if r.risk_rating is not None)
            ),
            by_sector=dict(Counter(r.industry_code for r in requests if r.industry_code)),
            by_country=dict(
                Counter(r.incorporation_country for r in requests if r.incorporation_country)
            ),
        )

    # ── Time-in-state metrics ────────────────────────────────────────────────

    async def get_time_in_state_metrics(self) -> list[TimeInStateMetric]:
        """Average and p95 time spent in each onboarding status.

        Computed from consecutive `onboarding_event` rows per request: an
        event with `to_status = X` marks entry into `X`; the *next* event for
        that same request marks the exit, and the duration between the two is
        one completed sample of "time spent in X". A request's *current*
        status (the last event in its sequence) has no exit yet and is
        excluded — only completed intervals are averaged, so an onboarding
        that has been sitting in a state for a long time does not silently
        vanish from the metric only once it moves; it is counted once it
        does.
        """
        events = await self._events.list_all_ordered()
        durations: dict[str, list[float]] = defaultdict(list)

        for _, group in groupby(events, key=lambda e: e.onboarding_request_id):
            sequence = list(group)
            for current, following in zip(sequence, sequence[1:], strict=False):
                if current.to_status is None:
                    continue
                elapsed = (following.created_at - current.created_at).total_seconds()
                durations[current.to_status].append(elapsed)

        metrics: list[TimeInStateMetric] = []
        for status in OnboardingRequestStatus:
            samples = durations.get(status.value, [])
            if not samples:
                metrics.append(
                    TimeInStateMetric(
                        status=status, sample_count=0, average_seconds=None, p95_seconds=None
                    )
                )
                continue
            metrics.append(
                TimeInStateMetric(
                    status=status,
                    sample_count=len(samples),
                    average_seconds=sum(samples) / len(samples),
                    p95_seconds=_percentile(samples, 0.95),
                )
            )
        return metrics


def _edd_reason(request: object) -> str | None:
    """Best-effort EDD/review reason from the fields the schema has.

    `onboarding_request.edd_reason` (the dedicated column added alongside the
    screening_result rename) is checked first. `risk_rating_factors['edd_reason']`
    is checked next for backward compatibility with any row that predates that
    column, or a caller that only ever set the JSON copy directly (e.g. a test
    fixture); `rejection_reason` is the fallback for a request already flagged
    for manual disposition.
    """
    edd_reason = getattr(request, "edd_reason", None)
    if edd_reason:
        return str(edd_reason)
    factors = getattr(request, "risk_rating_factors", None)
    if isinstance(factors, dict) and factors.get("edd_reason"):
        return str(factors["edd_reason"])
    return getattr(request, "rejection_reason", None)


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (matches numpy's default `interpolation='linear'`)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


__all__ = ["OnboardingQueryService"]
