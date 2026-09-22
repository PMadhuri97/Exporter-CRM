"""
OnboardingTransitionService against PostgreSQL.

Every assertion reads back through a fresh session, so it checks what was committed
rather than what one session believes. The test database is shared and never reset:
each test creates its own onboarding request and asserts only on that request's rows.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.modules.onboarding.application.onboarding_transition_service import (
    STATUS_CHANGED_EVENT_TYPE,
    OnboardingTransitionService,
)
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
from app.modules.onboarding.exceptions import (
    OnboardingRequestNotFoundError,
    OnboardingStatusConflictError,
    OnboardingTransitionNotPermittedError,
)
from app.modules.onboarding.infrastructure.repositories.onboarding_event_repository import (
    OnboardingEventRepository,
)
from app.platform.database import services as database

S = OnboardingRequestStatus
ACTOR = "onboarding-transition-test"
T0 = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)

FORWARD_PATH = [
    S.DRAFT,
    S.ENTITY_VERIFICATION_IN_PROGRESS,
    S.ENTITY_VERIFIED,
    S.UBO_MAPPING_IN_PROGRESS,
    S.UBO_MAPPING_COMPLETE,
    S.DOCUMENT_COLLECTION_IN_PROGRESS,
    S.DOCUMENT_COLLECTION_COMPLETE,
    S.SCREENING_IN_PROGRESS,
    S.SCREENING_COMPLETE,
    S.RISK_RATING_IN_PROGRESS,
    S.RISK_RATED,
    S.PENDING_COMPLIANCE_APPROVAL,
    S.APPROVED,
    S.ACCOUNT_CREATION_IN_PROGRESS,
    S.ACTIVE,
]


# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_request(status: OnboardingRequestStatus = S.DRAFT) -> uuid.UUID:
    async with database.AsyncSessionLocal() as session:
        request = OnboardingRequest(
            tenant_id=uuid.uuid4(),
            idempotency_key=f"transition-test-{uuid.uuid4().hex}",
            customer_id=uuid.uuid4(),
            status=status,
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name="Transition Test Corp",
            registration_number="REG-0001",
            incorporation_country="US",
            registered_address={"country": "US"},
            initial_user_id="initial-user",
        )
        session.add(request)
        await session.commit()
        return request.id


async def _transition(request_id: uuid.UUID, from_status, to_status, **kwargs):
    async with database.AsyncSessionLocal() as session:
        return await OnboardingTransitionService(session).transition(
            request_id,
            expected_status=from_status,
            to_status=to_status,
            actor_id=ACTOR,
            **kwargs,
        )


async def _walk(request_id: uuid.UUID, path: list[OnboardingRequestStatus]) -> None:
    for from_status, to_status in pairwise(path):
        await _transition(request_id, from_status, to_status)


async def _read_request(request_id: uuid.UUID) -> OnboardingRequest:
    async with database.AsyncSessionLocal() as session:
        request = await session.get(OnboardingRequest, request_id)
        assert request is not None
        return request


async def _read_events(request_id: uuid.UUID):
    async with database.AsyncSessionLocal() as session:
        return list(await OnboardingEventRepository(session).list_by_request(request_id))


# ── valid transition and atomic event persistence ─────────────────────────────


async def test_valid_transition_updates_status_and_records_one_event():
    request_id = await _create_request()

    result = await _transition(
        request_id,
        S.DRAFT,
        S.ENTITY_VERIFICATION_IN_PROGRESS,
        occurred_at=T0,
        metadata={"step": "entity_verification"},
    )

    assert result.already_applied is False
    assert result.from_status == S.DRAFT
    assert result.to_status == S.ENTITY_VERIFICATION_IN_PROGRESS

    request = await _read_request(request_id)
    assert request.status == S.ENTITY_VERIFICATION_IN_PROGRESS
    assert request.last_activity_at == T0
    assert request.initiated_at == T0
    assert request.completed_at is None

    events = await _read_events(request_id)
    assert len(events) == 1
    event = events[0]
    assert event.id == result.event_id
    assert event.event_type == STATUS_CHANGED_EVENT_TYPE
    assert event.from_status == S.DRAFT.value
    assert event.to_status == S.ENTITY_VERIFICATION_IN_PROGRESS.value
    assert event.actor_id == ACTOR
    assert event.event_metadata == {"step": "entity_verification"}


async def test_full_forward_path_records_one_event_per_transition():
    request_id = await _create_request()

    for index, (from_status, to_status) in enumerate(pairwise(FORWARD_PATH)):
        await _transition(
            request_id, from_status, to_status, occurred_at=T0 + timedelta(minutes=index)
        )

    request = await _read_request(request_id)
    last_at = T0 + timedelta(minutes=len(FORWARD_PATH) - 2)
    assert request.status == S.ACTIVE
    assert request.initiated_at == T0
    assert request.completed_at == last_at
    assert request.last_activity_at == last_at

    events = await _read_events(request_id)
    assert [(e.from_status, e.to_status) for e in events] == [
        (a.value, b.value) for a, b in pairwise(FORWARD_PATH)
    ]


async def test_rejection_records_category_reason_and_completion():
    request_id = await _create_request()
    await _walk(request_id, [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS])

    await _transition(
        request_id,
        S.ENTITY_VERIFICATION_IN_PROGRESS,
        S.REJECTED,
        occurred_at=T0,
        rejection_category=OnboardingRejectionCategory.KYB_FAILURE,
        rejection_reason="entity not found in registry",
    )

    request = await _read_request(request_id)
    assert request.status == S.REJECTED
    assert request.rejection_category == OnboardingRejectionCategory.KYB_FAILURE
    assert request.rejection_reason == "entity not found in registry"
    assert request.completed_at == T0

    event = (await _read_events(request_id))[-1]
    assert event.to_status == S.REJECTED.value
    assert event.event_metadata == {
        "rejection_category": "KYB_FAILURE",
        "rejection_reason": "entity not found in registry",
    }


# ── invalid transition and expected-state mismatch ────────────────────────────


async def test_invalid_transition_is_refused_before_any_write():
    request_id = await _create_request()

    with pytest.raises(OnboardingTransitionNotPermittedError):
        await _transition(request_id, S.DRAFT, S.ACTIVE)

    assert (await _read_request(request_id)).status == S.DRAFT
    assert await _read_events(request_id) == []


async def test_expected_status_mismatch_raises_conflict_and_writes_nothing():
    request_id = await _create_request()

    with pytest.raises(OnboardingStatusConflictError) as exc:
        await _transition(request_id, S.ENTITY_VERIFIED, S.UBO_MAPPING_IN_PROGRESS)

    assert exc.value.current_status == S.DRAFT.value
    assert exc.value.expected_status == S.ENTITY_VERIFIED.value
    assert exc.value.status_code == 409
    assert (await _read_request(request_id)).status == S.DRAFT
    assert await _read_events(request_id) == []


async def test_repeating_a_transition_the_request_has_moved_past_is_a_conflict():
    request_id = await _create_request()
    await _walk(request_id, [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.ENTITY_VERIFIED])

    with pytest.raises(OnboardingStatusConflictError):
        await _transition(request_id, S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS)

    assert len(await _read_events(request_id)) == 2


async def test_reaching_the_target_by_another_route_is_a_conflict_not_a_repeat():
    """ENTITY_VERIFIED reached through manual review is not the direct transition."""
    request_id = await _create_request()
    await _walk(
        request_id,
        [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, S.UNDER_REVIEW, S.ENTITY_VERIFIED],
    )

    with pytest.raises(OnboardingStatusConflictError):
        await _transition(request_id, S.ENTITY_VERIFICATION_IN_PROGRESS, S.ENTITY_VERIFIED)


async def test_unknown_request_is_not_found():
    with pytest.raises(OnboardingRequestNotFoundError):
        await _transition(uuid.uuid4(), S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS)


# ── repeated identical transition and duplicate event protection ──────────────


async def test_repeated_identical_transition_is_idempotent():
    request_id = await _create_request()

    first = await _transition(
        request_id, S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, occurred_at=T0
    )
    second = await _transition(
        request_id,
        S.DRAFT,
        S.ENTITY_VERIFICATION_IN_PROGRESS,
        occurred_at=T0 + timedelta(hours=1),
    )

    assert first.already_applied is False
    assert second.already_applied is True
    assert second.event_id == first.event_id

    request = await _read_request(request_id)
    assert request.last_activity_at == T0
    assert len(await _read_events(request_id)) == 1


async def test_concurrent_identical_transitions_record_exactly_one_event():
    """Two attempts racing the same transition — as overlapping retries of one
    activity would — produce one status change and one event."""
    for _ in range(5):
        request_id = await _create_request()

        results = await asyncio.gather(
            _transition(request_id, S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS),
            _transition(request_id, S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS),
        )

        assert sorted(r.already_applied for r in results) == [False, True]
        assert results[0].event_id == results[1].event_id
        assert (await _read_request(request_id)).status == S.ENTITY_VERIFICATION_IN_PROGRESS
        assert len(await _read_events(request_id)) == 1


async def test_concurrent_conflicting_transitions_apply_only_one():
    request_id = await _create_request()
    await _walk(request_id, [S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS])

    outcomes = await asyncio.gather(
        _transition(request_id, S.ENTITY_VERIFICATION_IN_PROGRESS, S.ENTITY_VERIFIED),
        _transition(request_id, S.ENTITY_VERIFICATION_IN_PROGRESS, S.UNDER_REVIEW),
        return_exceptions=True,
    )

    applied = [o for o in outcomes if not isinstance(o, BaseException)]
    conflicts = [o for o in outcomes if isinstance(o, OnboardingStatusConflictError)]
    assert len(applied) == 1
    assert len(conflicts) == 1
    assert (await _read_request(request_id)).status == applied[0].to_status
    assert len(await _read_events(request_id)) == 2


# ── rollback ──────────────────────────────────────────────────────────────────


async def test_event_write_failure_rolls_back_the_status_change(monkeypatch):
    request_id = await _create_request()

    async def _fail(self, instance):
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(OnboardingEventRepository, "create", _fail)

    with pytest.raises(RuntimeError, match="event store unavailable"):
        await _transition(
            request_id, S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS, occurred_at=T0
        )

    monkeypatch.undo()

    request = await _read_request(request_id)
    assert request.status == S.DRAFT
    assert request.last_activity_at is None
    assert request.initiated_at is None
    assert await _read_events(request_id) == []

    # Nothing was left half-applied: the same transition still succeeds afterwards.
    result = await _transition(request_id, S.DRAFT, S.ENTITY_VERIFICATION_IN_PROGRESS)
    assert result.already_applied is False
    assert len(await _read_events(request_id)) == 1
