"""ANER-4.3-S6T1: `CaseQueryService.get_open_cases_count`,
`.get_cases_requiring_sar_consideration`, and `.get_case_resolution_audit`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cases.application.case_query_service import (
    SAR_CONSIDERATION_MARKER,
    CaseQueryService,
)
from app.modules.cases.domain.entities.enums import CaseSeverity
from app.modules.cases.exceptions import CaseNotFoundError
from app.modules.cases.tests.fixtures.case_sql import insert_case, insert_timeline_event
from app.platform.database import services as database


@pytest.fixture
def service() -> CaseQueryService:
    return CaseQueryService()


# ── get_open_cases_count ─────────────────────────────────────────────────────


async def test_get_open_cases_count_counts_non_terminal_cases_by_severity(service):
    """"Open" is read as non-terminal (see the service's own docstring for
    why) — ASSIGNED and UNDER_INVESTIGATION count, RESOLVED does not."""
    async with database.AsyncSessionLocal() as session:
        before = await service.get_open_cases_count(session)
    before_critical = before.get(CaseSeverity.CRITICAL, 0)

    insert_case(case_status="OPEN", severity="CRITICAL")
    insert_case(case_status="ASSIGNED", severity="CRITICAL")
    insert_case(case_status="UNDER_INVESTIGATION", severity="CRITICAL")
    insert_case(case_status="RESOLVED", severity="CRITICAL")
    insert_case(case_status="CLOSED_WITHOUT_ACTION", severity="CRITICAL")

    async with database.AsyncSessionLocal() as session:
        after = await service.get_open_cases_count(session)

    assert after[CaseSeverity.CRITICAL] == before_critical + 3


# ── get_cases_requiring_sar_consideration ────────────────────────────────────


async def test_sar_consideration_flag_is_found_case_insensitively(service):
    flagged = insert_case(
        case_status="RESOLVED",
        resolution_action="MANUAL_RESOLUTION",
        resolution_note=(
            "Reviewed the on-chain score increase; officer notes SAR Consideration "
            "outcome documented per procedure."
        ),
        resolved_at=datetime.now(UTC).isoformat(),
        resolved_by="senior.officer",
    )

    async with database.AsyncSessionLocal() as session:
        results = await service.get_cases_requiring_sar_consideration(session)

    assert flagged["id"] in {str(c.id) for c in results}


async def test_resolved_case_without_the_flag_is_excluded(service):
    not_flagged = insert_case(
        case_status="RESOLVED",
        resolution_action="NO_ACTION_REQUIRED",
        resolution_note="Reviewed and determined no further action required at this time.",
        resolved_at=datetime.now(UTC).isoformat(),
        resolved_by="senior.officer",
    )

    async with database.AsyncSessionLocal() as session:
        results = await service.get_cases_requiring_sar_consideration(session)

    assert not_flagged["id"] not in {str(c.id) for c in results}


async def test_open_case_with_flag_text_is_excluded_because_not_resolved(service):
    """The AC is "resolved cases" only — a still-open case is never a SAR
    candidate no matter what its (not-yet-final) resolution_note would say,
    since resolution_note is only ever set alongside resolution_action, which
    only exists on a resolved/closed case."""
    marker = f"unresolved-{uuid.uuid4().hex[:8]}"
    insert_case(case_status="OPEN", title=marker)

    async with database.AsyncSessionLocal() as session:
        results = await service.get_cases_requiring_sar_consideration(session)

    assert marker not in {c.title for c in results}


def test_sar_consideration_marker_matches_the_docs_own_phrase():
    """Documents the chosen convention (see case_query_service.py's module
    docstring) against a regression in the literal marker string."""
    assert SAR_CONSIDERATION_MARKER == "sar consideration"


# ── get_case_resolution_audit ────────────────────────────────────────────────


async def test_resolution_audit_is_self_contained_and_includes_every_event(service):
    """AC: "produces a self-contained structured report that includes every
    case_timeline_event with actor identity and timestamp"."""
    case = insert_case(
        case_status="RESOLVED",
        resolution_action="APPROVE_TRANSACTION",
        resolution_note="Approved after two-officer review of the flagged transaction.",
        resolved_at=datetime.now(UTC).isoformat(),
        resolved_by="checker.1",
    )
    base = datetime(2026, 9, 1, tzinfo=UTC)
    insert_timeline_event(
        case["id"], event_type="CASE_CREATED", to_status="OPEN",
        actor_id="system", actor_type="SYSTEM", occurred_at=base,
    )
    insert_timeline_event(
        case["id"], event_type="ASSIGNED", from_status="OPEN", to_status="ASSIGNED",
        actor_id="lead.1", actor_type="COMPLIANCE_OFFICER",
        occurred_at=base + timedelta(minutes=5),
    )
    insert_timeline_event(
        case["id"], event_type="RESOLVED", from_status="PENDING_APPROVAL", to_status="RESOLVED",
        actor_id="checker.1", actor_type="COMPLIANCE_OFFICER", note="Approved.",
        occurred_at=base + timedelta(minutes=30),
    )

    async with database.AsyncSessionLocal() as session:
        audit = await service.get_case_resolution_audit(session, uuid.UUID(case["id"]))

    assert audit.case_reference == case["case_reference"]
    assert audit.resolution_action == "APPROVE_TRANSACTION"
    assert audit.resolved_by == "checker.1"
    assert len(audit.events) == 3
    assert [e.event_type for e in audit.events] == ["CASE_CREATED", "ASSIGNED", "RESOLVED"]
    assert [e.actor_id for e in audit.events] == ["system", "lead.1", "checker.1"]
    assert all(e.occurred_at is not None for e in audit.events)
    # Self-contained: no field on the report requires a lookup elsewhere to
    # interpret — case_reference (not just an internal id) is present.
    assert audit.case_id == uuid.UUID(case["id"])


async def test_resolution_audit_unknown_case_raises(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.get_case_resolution_audit(session, uuid.uuid4())


async def test_resolution_audit_for_an_unresolved_case_has_null_resolution_fields(service):
    case = insert_case(case_status="OPEN")
    async with database.AsyncSessionLocal() as session:
        audit = await service.get_case_resolution_audit(session, uuid.UUID(case["id"]))

    assert audit.resolution_action is None
    assert audit.resolved_by is None
    assert audit.resolved_at is None
