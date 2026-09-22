"""ANER-4.3-S5T2, detection half only: `CaseSlaMonitoringService.
list_breached_cases` and `.list_cases_approaching_auto_escalation`.

See `case_sla_monitoring_service.py`'s module docstring for the full
scoping rationale (no auto-escalation performed, no alerts emitted, live
computation rather than the never-written `sla_breached` stored column).
This suite proves the two detection queries themselves: breach detection
respects the same terminal-status exemption `SlaCalculationService.
is_sla_breached` already enforces per-case, auto-escalation-threshold
detection matches the doc's 75%/45-minutes acceptance criterion and the
"already escalated is not re-flagged" idempotency rule, and both queries
categorically exclude `ONBOARDING_INTAKE` cases (null `sla_deadline`).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cases.application.case_sla_monitoring_service import CaseSlaMonitoringService
from app.modules.cases.infrastructure.sla_config_loader import build_sla_calculation_service
from app.modules.cases.tests.fixtures.case_sql import insert_case
from app.platform.database import services as database


@pytest.fixture(scope="module")
def sla_service():
    return build_sla_calculation_service()


@pytest.fixture
def service(sla_service) -> CaseSlaMonitoringService:
    return CaseSlaMonitoringService(sla_service)


# ── list_breached_cases ──────────────────────────────────────────────────────


async def test_open_case_past_deadline_is_breached(service):
    deadline = datetime.now(UTC) - timedelta(minutes=30)
    case = insert_case(case_status="OPEN", sla_deadline=deadline.isoformat())

    async with database.AsyncSessionLocal() as session:
        breached = await service.list_breached_cases(session)

    assert case["id"] in {str(c.id) for c in breached}


async def test_open_case_before_deadline_is_not_breached(service):
    deadline = datetime.now(UTC) + timedelta(hours=1)
    case = insert_case(case_status="OPEN", sla_deadline=deadline.isoformat())

    async with database.AsyncSessionLocal() as session:
        breached = await service.list_breached_cases(session)

    assert case["id"] not in {str(c.id) for c in breached}


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "CLOSED_WITHOUT_ACTION"])
async def test_resolved_or_closed_case_past_old_deadline_is_not_breached(service, terminal_status):
    """The exact case the task calls out: a resolved case past its old
    deadline must NOT show as breached — matching
    `SlaCalculationService.is_sla_breached`'s own terminal-status exemption."""
    deadline = datetime.now(UTC) - timedelta(hours=5)
    case = insert_case(
        case_status=terminal_status,
        sla_deadline=deadline.isoformat(),
        resolution_action="NO_ACTION_REQUIRED" if terminal_status == "RESOLVED" else None,
        resolution_note=(
            "Resolved before the deadline check would have flagged it." if terminal_status == "RESOLVED" else None
        ),
        resolved_at=datetime.now(UTC).isoformat() if terminal_status == "RESOLVED" else None,
        resolved_by="compliance.officer" if terminal_status == "RESOLVED" else None,
    )

    async with database.AsyncSessionLocal() as session:
        breached = await service.list_breached_cases(session)

    assert case["id"] not in {str(c.id) for c in breached}


async def test_onboarding_intake_case_never_appears_as_breached(service):
    """ONBOARDING_INTAKE cases carry no sla_deadline at all
    (ck_compliance_case_intake_has_no_sla_deadline) — proven explicitly here
    even though the filter (sla_deadline IS NOT NULL) makes it fall out
    naturally, per the task's own instruction not to rely on that being
    accidental."""
    case = insert_case(case_type="ONBOARDING_INTAKE", case_status="OPEN", sla_deadline=None)

    async with database.AsyncSessionLocal() as session:
        breached = await service.list_breached_cases(session)

    assert case["id"] not in {str(c.id) for c in breached}


async def test_breached_cases_are_ordered_most_overdue_first(service):
    less_overdue = insert_case(
        case_status="OPEN", sla_deadline=(datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    )
    more_overdue = insert_case(
        case_status="OPEN", sla_deadline=(datetime.now(UTC) - timedelta(hours=3)).isoformat()
    )

    async with database.AsyncSessionLocal() as session:
        breached = await service.list_breached_cases(session)

    ids_in_order = [str(c.id) for c in breached]
    assert ids_in_order.index(more_overdue["id"]) < ids_in_order.index(less_overdue["id"])


# ── list_cases_approaching_auto_escalation ───────────────────────────────────


async def test_case_past_seventy_five_percent_threshold_is_a_candidate(service):
    """AC (doc, S5T2): "A case at 75% of its critical SLA (45 minutes for a
    transaction_flag critical) is auto-escalated" — detection side: it must
    show up as a candidate once 45 minutes have elapsed since creation."""
    created_at = datetime.now(UTC) - timedelta(minutes=50)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="UNDER_INVESTIGATION",
        sla_deadline=(created_at + timedelta(hours=1)).isoformat(),
        created_at=created_at,
    )
    async with database.AsyncSessionLocal() as session:
        candidates = await service.list_cases_approaching_auto_escalation(session)

    ids = {str(c.case.id) for c in candidates}
    assert case["id"] in ids


async def test_case_before_threshold_is_not_a_candidate(service):
    created_at = datetime.now(UTC) - timedelta(minutes=10)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="UNDER_INVESTIGATION",
        sla_deadline=(created_at + timedelta(hours=1)).isoformat(),
        created_at=created_at,
    )
    async with database.AsyncSessionLocal() as session:
        candidates = await service.list_cases_approaching_auto_escalation(session)

    ids = {str(c.case.id) for c in candidates}
    assert case["id"] not in ids


async def test_already_escalated_case_is_not_a_repeat_candidate(service):
    """AC (doc, S5T2): "The job is idempotent — a case already escalated is
    not re-escalated on the next job run." Detection-side equivalent: an
    ESCALATED case, however far past its threshold, is not surfaced again."""
    created_at = datetime.now(UTC) - timedelta(hours=2)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="ESCALATED",
        sla_deadline=(created_at + timedelta(hours=1)).isoformat(),
        created_at=created_at,
    )
    async with database.AsyncSessionLocal() as session:
        candidates = await service.list_cases_approaching_auto_escalation(session)

    ids = {str(c.case.id) for c in candidates}
    assert case["id"] not in ids


async def test_terminal_case_past_threshold_is_not_a_candidate(service):
    created_at = datetime.now(UTC) - timedelta(hours=2)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="RESOLVED",
        sla_deadline=(created_at + timedelta(hours=1)).isoformat(),
        resolution_action="NO_ACTION_REQUIRED",
        resolution_note="Resolved well before any escalation would trigger.",
        resolved_at=datetime.now(UTC).isoformat(),
        resolved_by="compliance.officer",
        created_at=created_at,
    )
    async with database.AsyncSessionLocal() as session:
        candidates = await service.list_cases_approaching_auto_escalation(session)

    ids = {str(c.case.id) for c in candidates}
    assert case["id"] not in ids


async def test_onboarding_intake_case_never_appears_as_an_escalation_candidate(service):
    """Same explicit-exclusion proof as the breach-detection test above, for
    the auto-escalation-threshold query."""
    case = insert_case(case_type="ONBOARDING_INTAKE", case_status="OPEN", sla_deadline=None)

    async with database.AsyncSessionLocal() as session:
        candidates = await service.list_cases_approaching_auto_escalation(session)

    ids = {str(c.case.id) for c in candidates}
    assert case["id"] not in ids


async def test_manual_case_with_no_configured_sla_target_is_skipped_not_raised(service):
    """MANUAL has no entry in the GitOps SLA config (see
    `case_sla_monitoring_service.py`'s docstring for
    `list_cases_approaching_auto_escalation`), but nothing at the database
    level stops a MANUAL case from carrying a real, non-null sla_deadline and
    a non-terminal status. Such a row must not crash detection for every
    other case in the same query."""
    created_at = datetime.now(UTC) - timedelta(hours=10)
    case = insert_case(
        case_type="MANUAL",
        severity="HIGH",
        case_status="OPEN",
        sla_deadline=(created_at + timedelta(hours=1)).isoformat(),
        created_at=created_at,
    )
    other = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="UNDER_INVESTIGATION",
        sla_deadline=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        created_at=datetime.now(UTC) - timedelta(minutes=50),
    )

    async with database.AsyncSessionLocal() as session:
        candidates = await service.list_cases_approaching_auto_escalation(session)

    ids = {str(c.case.id) for c in candidates}
    assert case["id"] not in ids
    assert other["id"] in ids
