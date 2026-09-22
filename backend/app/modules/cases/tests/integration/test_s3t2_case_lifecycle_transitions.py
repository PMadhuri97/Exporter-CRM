"""ANER-4.3-S3T2: `CaseLifecycleService`'s general `case_status` transition
graph against a real database.

`PERMITTED_TRANSITIONS`'s shape is pinned by
`test_s3t2_permitted_transitions_table.py` (unit, no DB); this suite proves
each edge actually executes end-to-end through `begin_investigation` /
`mark_pending_external` / `escalate_case` / `close_case_without_action`, and
that out-of-graph attempts are rejected with `InvalidCaseStatusTransitionError`.
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.case_lifecycle_service import (
    MIN_SUBSTANTIVE_NOTE_LENGTH,
    CaseLifecycleService,
)
from app.modules.cases.domain.entities.enums import ActorType, CaseStatus
from app.modules.cases.exceptions import CaseNotFoundError, InvalidCaseStatusTransitionError
from app.modules.cases.tests.fixtures.case_sql import fetchone, insert_case
from app.platform.database import services as database
from app.shared.exceptions import ValidationError

LONG_REASON = "x" * MIN_SUBSTANTIVE_NOTE_LENGTH


@pytest.fixture
def service() -> CaseLifecycleService:
    return CaseLifecycleService()


# ── valid edges ──────────────────────────────────────────────────────────


async def test_begin_investigation_from_assigned(service):
    case = insert_case(case_status="ASSIGNED")
    async with database.AsyncSessionLocal() as session:
        updated = await service.begin_investigation(
            session, uuid.UUID(case["id"]), actor_id="officer.1", actor_type=ActorType.COMPLIANCE_OFFICER
        )
    assert updated.case_status == CaseStatus.UNDER_INVESTIGATION


async def test_begin_investigation_from_pending_external(service):
    case = insert_case(case_status="PENDING_EXTERNAL")
    async with database.AsyncSessionLocal() as session:
        updated = await service.begin_investigation(
            session, uuid.UUID(case["id"]), actor_id="officer.1", actor_type=ActorType.COMPLIANCE_OFFICER
        )
    assert updated.case_status == CaseStatus.UNDER_INVESTIGATION


async def test_begin_investigation_from_escalated(service):
    case = insert_case(case_status="ESCALATED")
    async with database.AsyncSessionLocal() as session:
        updated = await service.begin_investigation(
            session, uuid.UUID(case["id"]), actor_id="senior.officer", actor_type=ActorType.COMPLIANCE_OFFICER
        )
    assert updated.case_status == CaseStatus.UNDER_INVESTIGATION


async def test_mark_pending_external_from_under_investigation(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    async with database.AsyncSessionLocal() as session:
        updated = await service.mark_pending_external(
            session,
            uuid.UUID(case["id"]),
            actor_id="officer.1",
            actor_type=ActorType.COMPLIANCE_OFFICER,
            reason="Waiting on customer documents.",
        )
    assert updated.case_status == CaseStatus.PENDING_EXTERNAL


async def test_escalate_case_from_under_investigation(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    async with database.AsyncSessionLocal() as session:
        updated = await service.escalate_case(
            session,
            uuid.UUID(case["id"]),
            actor_id="officer.1",
            actor_type=ActorType.COMPLIANCE_OFFICER,
            reason="Needs senior review.",
        )
    assert updated.case_status == CaseStatus.ESCALATED

    row = fetchone(
        "SELECT event_type, note, payload FROM cases.case_timeline_event WHERE case_id = %s",
        (case["id"],),
    )
    event_type, note, payload = row
    assert event_type == "ESCALATED"
    assert note == "Needs senior review."
    assert payload["reason"] == "Needs senior review."


async def test_close_case_without_action_from_under_investigation(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    async with database.AsyncSessionLocal() as session:
        updated = await service.close_case_without_action(
            session,
            uuid.UUID(case["id"]),
            actor_id="officer.1",
            actor_type=ActorType.COMPLIANCE_OFFICER,
            reason=LONG_REASON,
        )
    assert updated.case_status == CaseStatus.CLOSED_WITHOUT_ACTION
    assert updated.resolution_action is None
    assert updated.resolution_note is None

    row = fetchone(
        "SELECT resolution_action, resolution_note FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row == (None, None)


# ── invalid edges / terminal enforcement ─────────────────────────────────


async def test_invalid_transition_resolved_to_under_investigation_is_rejected(service):
    """AC (doc, S3T2): 'An invalid transition (resolved -> under_investigation)
    is rejected with the specific error identifying the invalid transition.'"""
    case = insert_case(case_status="RESOLVED")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError) as exc:
            await service.begin_investigation(
                session, uuid.UUID(case["id"]), actor_id="officer.1", actor_type=ActorType.COMPLIANCE_OFFICER
            )
    assert exc.value.from_status == CaseStatus.RESOLVED
    assert exc.value.to_status == CaseStatus.UNDER_INVESTIGATION


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "CLOSED_WITHOUT_ACTION"])
async def test_no_valid_transition_out_of_a_terminal_status(service, terminal_status):
    """AC (doc, S3T2): 'A case in a terminal state (resolved,
    closed_without_action) cannot be further transitioned — the attempt is
    rejected.'"""
    case = insert_case(case_status=terminal_status)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError):
            await service.escalate_case(
                session,
                uuid.UUID(case["id"]),
                actor_id="officer.1",
                actor_type=ActorType.COMPLIANCE_OFFICER,
                reason="Attempted after close.",
            )


async def test_close_without_action_rejects_a_case_that_is_only_assigned(service):
    """The doc's table has exactly one row into closed_without_action —
    under_investigation only, not "any non-terminal status" (see
    case_lifecycle_service.py's module docstring)."""
    case = insert_case(case_status="ASSIGNED")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError):
            await service.close_case_without_action(
                session,
                uuid.UUID(case["id"]),
                actor_id="officer.1",
                actor_type=ActorType.COMPLIANCE_OFFICER,
                reason=LONG_REASON,
            )


async def test_close_without_action_rejects_a_short_reason(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.close_case_without_action(
                session,
                uuid.UUID(case["id"]),
                actor_id="officer.1",
                actor_type=ActorType.COMPLIANCE_OFFICER,
                reason="too short",
            )


async def test_escalate_rejects_an_empty_reason(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.escalate_case(
                session,
                uuid.UUID(case["id"]),
                actor_id="officer.1",
                actor_type=ActorType.COMPLIANCE_OFFICER,
                reason="   ",
            )


@pytest.mark.parametrize("status", ["OPEN", "ASSIGNED"])
async def test_escalate_rejects_out_of_scope_sla_auto_escalation_edges(service, status):
    """The doc's table also lists open->escalated and assigned->escalated,
    both SLA-auto-escalation-triggered (S5T2, not built here) — escalate_case
    is documented as manual-only and must reject both."""
    case = insert_case(case_status=status)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError):
            await service.escalate_case(
                session,
                uuid.UUID(case["id"]),
                actor_id="officer.1",
                actor_type=ActorType.COMPLIANCE_OFFICER,
                reason="Should not be permitted from here.",
            )


async def test_transition_on_unknown_case_raises_case_not_found(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.begin_investigation(
                session, uuid.uuid4(), actor_id="officer.1", actor_type=ActorType.COMPLIANCE_OFFICER
            )
