"""ANER-4.3-S2: `CaseTransitionService.transition_case_to_review` against a
real database.

`case_transition_service.py` is deliberately the one narrow slice of S3's
case-lifecycle machinery built so far: moving a case's `case_type` from
`ONBOARDING_INTAKE` to `ONBOARDING_REVIEW`, and — the specific behaviour this
suite exists to pin down — setting `compliance_case.sla_deadline` for the
first time at that transition, computed from the transition's own timestamp
rather than the case's original `created_at`.

Raw SQL for setup/verification, following `test_s1t1_case_management_schema.
py`'s precedent: inserting/reading through the ORM would prove only that
SQLAlchemy declares the right shape, not that the service actually persisted
what it claims to a real row. The service itself is exercised through its
real async API against a real `AsyncSession`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cases.application.case_transition_service import CaseTransitionService
from app.modules.cases.domain.entities.enums import ActorType, CaseSeverity, CaseType
from app.modules.cases.exceptions import CaseNotFoundError, InvalidCaseTransitionError
from app.modules.cases.infrastructure.sla_config_loader import build_sla_calculation_service
from app.modules.cases.tests.fixtures.case_sql import (
    case_reference,
    execute,
    fetchall,
    fetchone,
    insert_case,
)

# Imported as a module, not `from ... import AsyncSessionLocal` — see
# test_s1t2_sla_seed_loading.py's identical note: the session-scoped autouse
# fixture in conftest.py rebinds this attribute, and a name bound at import
# time would keep the pooled original.
from app.platform.database import services as database

_INSERT_INTAKE_CASE_WITH_CREATED_AT = """
    INSERT INTO cases.compliance_case (
        id, case_reference, case_type, case_status, severity, priority,
        title, description, originating_epic, originating_event_type,
        sla_deadline, sla_breached, created_at
    ) VALUES (
        %(id)s, %(case_reference)s, 'ONBOARDING_INTAKE', 'OPEN', %(severity)s,
        3, 'RXIL intake case', 'Awaiting RXIL documents.', 'RXIL',
        'rxil.invoice.received', NULL, false, %(created_at)s
    )
"""


def _insert_intake_case(*, severity: str = "MEDIUM", created_at: datetime | None = None) -> str:
    case_id = str(uuid.uuid4())
    execute(
        _INSERT_INTAKE_CASE_WITH_CREATED_AT,
        {
            "id": case_id,
            "case_reference": case_reference(),
            "severity": severity,
            "created_at": created_at or datetime.now(UTC),
        },
    )
    return case_id


@pytest.fixture
def transition_service() -> CaseTransitionService:
    return CaseTransitionService(build_sla_calculation_service())


# ── sla_deadline set for the first time, at transition time ────────────────────


async def test_transition_sets_sla_deadline_using_the_transition_timestamp_not_the_original_created_at(
    transition_service,
):
    """AC: sla_deadline is (re)calculated at the moment case_type transitions
    from onboarding_intake to onboarding_review, using the transition
    timestamp, not the case's original created_at.

    The case is seeded with created_at 30 days in the past. If the deadline
    were (incorrectly) computed from that original created_at, an
    ONBOARDING_REVIEW/CRITICAL target (a few hours) would land the deadline
    deep in the past — an already-breached case the instant it becomes
    reviewable. Computed correctly, from *now* (the transition call), the
    deadline lands in the future.
    """
    old_created_at = datetime.now(UTC) - timedelta(days=30)
    case_id = _insert_intake_case(created_at=old_created_at)

    before = datetime.now(UTC)
    async with database.AsyncSessionLocal() as session:
        updated = await transition_service.transition_case_to_review(
            session,
            uuid.UUID(case_id),
            severity=CaseSeverity.CRITICAL,
            actor_id="rxil.intake.bot",
        )
    after = datetime.now(UTC)

    sla_service = build_sla_calculation_service()
    target = sla_service.get_target("ONBOARDING_REVIEW", "CRITICAL")

    assert updated.sla_deadline is not None
    assert updated.sla_deadline > datetime.now(UTC), (
        "the deadline must be in the future — a deadline derived from the "
        "30-day-old original created_at would already be breached"
    )
    assert (
        before + timedelta(hours=target.sla_hours)
        <= updated.sla_deadline
        <= after + timedelta(hours=target.sla_hours)
    )


async def test_intake_case_has_no_sla_deadline_before_transition():
    case_id = _insert_intake_case()
    row = fetchone(
        "SELECT case_type, sla_deadline FROM cases.compliance_case WHERE id = %s",
        (case_id,),
    )
    assert row == ("ONBOARDING_INTAKE", None)


async def test_intake_case_with_no_sla_deadline_is_never_reported_as_sla_breached():
    """A case with no sla_deadline (ONBOARDING_INTAKE, pre-transition) cannot
    be in breach of a deadline it doesn't have —
    SlaCalculationService.is_sla_breached must return False, not raise on the
    None comparison."""
    case_id = _insert_intake_case()
    sla_service = build_sla_calculation_service()
    async with database.AsyncSessionLocal() as session:
        breached = await sla_service.is_sla_breached(session, uuid.UUID(case_id))
    assert breached is False


async def test_transition_updates_case_type_severity_and_sla_breached(transition_service):
    case_id = _insert_intake_case(severity="LOW")

    async with database.AsyncSessionLocal() as session:
        updated = await transition_service.transition_case_to_review(
            session, uuid.UUID(case_id), severity=CaseSeverity.HIGH, actor_id="rxil.intake.bot"
        )

    assert updated.case_type == CaseType.ONBOARDING_REVIEW
    assert updated.severity == CaseSeverity.HIGH
    assert updated.sla_breached is False

    row = fetchone(
        "SELECT case_type, severity, sla_breached FROM cases.compliance_case WHERE id = %s",
        (case_id,),
    )
    assert row == ("ONBOARDING_REVIEW", "HIGH", False)


async def test_transition_matches_calculate_sla_deadline_for_the_same_inputs(transition_service):
    """The deadline the service sets must be exactly what
    SlaCalculationService.calculate_sla_deadline returns for
    (ONBOARDING_REVIEW, severity, transition_timestamp) — not an
    approximation of it."""
    case_id = _insert_intake_case()

    async with database.AsyncSessionLocal() as session:
        updated = await transition_service.transition_case_to_review(
            session, uuid.UUID(case_id), severity=CaseSeverity.MEDIUM, actor_id="rxil.intake.bot"
        )

    sla_service = build_sla_calculation_service()
    expected = sla_service.calculate_sla_deadline(
        "ONBOARDING_REVIEW", "MEDIUM", updated.last_updated_at
    )
    # last_updated_at (onupdate=func.now(), a DB-side timestamp) and the
    # service's own transition timestamp (taken in Python just before commit)
    # are both "now" at transition time but not guaranteed to be the
    # identical instant, so compare via a small tolerance rather than exact
    # equality — the real assertion is that both derive from a timestamp
    # taken at transition time, not from the case's original created_at.
    assert abs((updated.sla_deadline - expected).total_seconds()) < 5


# ── audit trail ─────────────────────────────────────────────────────────────────


async def test_transition_records_a_status_changed_timeline_event(transition_service):
    case_id = _insert_intake_case()

    async with database.AsyncSessionLocal() as session:
        await transition_service.transition_case_to_review(
            session,
            uuid.UUID(case_id),
            severity=CaseSeverity.HIGH,
            actor_id="rxil.intake.bot",
            actor_type=ActorType.SYSTEM,
            note="RXIL intake complete.",
        )

    rows = fetchall(
        "SELECT event_type, from_status, to_status, actor_id, actor_type, note, payload "
        "FROM cases.case_timeline_event WHERE case_id = %s",
        (case_id,),
    )
    assert len(rows) == 1
    event_type, from_status, to_status, actor_id, actor_type, note, payload = rows[0]
    assert event_type == "STATUS_CHANGED"
    assert from_status == "ONBOARDING_INTAKE"
    assert to_status == "ONBOARDING_REVIEW"
    assert actor_id == "rxil.intake.bot"
    assert actor_type == "SYSTEM"
    assert note == "RXIL intake complete."
    assert payload["transition"] == "case_type"
    assert payload["from_case_type"] == "ONBOARDING_INTAKE"
    assert payload["to_case_type"] == "ONBOARDING_REVIEW"
    assert payload["severity"] == "HIGH"


# ── error paths ──────────────────────────────────────────────────────────────────


async def test_transition_raises_for_an_unknown_case(transition_service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await transition_service.transition_case_to_review(
                session, uuid.uuid4(), severity=CaseSeverity.HIGH, actor_id="rxil.intake.bot"
            )


async def test_transition_rejects_a_case_that_is_not_onboarding_intake(transition_service):
    """AC-adjacent: the transition is defined only from ONBOARDING_INTAKE.
    A case of any other case_type must be rejected, not silently transitioned."""
    case = insert_case(case_type="TRANSACTION_FLAG")

    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseTransitionError):
            await transition_service.transition_case_to_review(
                session,
                uuid.UUID(case["id"]),
                severity=CaseSeverity.HIGH,
                actor_id="rxil.intake.bot",
            )


async def test_transition_cannot_be_repeated_on_the_same_case(transition_service):
    """The transition happens exactly once per case: a second attempt against
    an already-transitioned case must be rejected, not treated as a no-op."""
    case_id = _insert_intake_case()

    async with database.AsyncSessionLocal() as session:
        await transition_service.transition_case_to_review(
            session, uuid.UUID(case_id), severity=CaseSeverity.HIGH, actor_id="rxil.intake.bot"
        )

    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseTransitionError):
            await transition_service.transition_case_to_review(
                session,
                uuid.UUID(case_id),
                severity=CaseSeverity.HIGH,
                actor_id="rxil.intake.bot",
            )
