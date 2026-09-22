"""ANER-4.3-S3T1: `CaseLifecycleService.assign_case` against a real database.

No team/queue routing is exercised — see `assign_case`'s own docstring for
why the doc's routing-config half of S3T1 is out of scope.
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.case_lifecycle_service import CaseLifecycleService
from app.modules.cases.domain.entities.enums import ActorType, CaseStatus
from app.modules.cases.exceptions import (
    CaseNotFoundError,
    InvalidCaseStatusTransitionError,
    UserNotFoundOrInactiveError,
)
from app.modules.cases.tests.fixtures.auth_fixtures import create_user
from app.modules.cases.tests.fixtures.case_sql import fetchone, insert_case
from app.platform.database import services as database


@pytest.fixture
def service() -> CaseLifecycleService:
    return CaseLifecycleService()


async def test_assign_open_case_transitions_to_assigned(service):
    case = insert_case(case_status="OPEN")
    assignee = await create_user()

    async with database.AsyncSessionLocal() as session:
        updated = await service.assign_case(
            session,
            uuid.UUID(case["id"]),
            assignee,
            actor_id="team.lead",
            actor_type=ActorType.COMPLIANCE_OFFICER,
        )

    assert updated.case_status == CaseStatus.ASSIGNED
    assert updated.assigned_to == assignee
    assert updated.assigned_at is not None

    row = fetchone(
        "SELECT case_status, assigned_to FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row == ("ASSIGNED", assignee)


async def test_assign_writes_assigned_timeline_event_with_assignee_in_payload(service):
    case = insert_case(case_status="OPEN")
    assignee = await create_user()

    async with database.AsyncSessionLocal() as session:
        await service.assign_case(
            session,
            uuid.UUID(case["id"]),
            assignee,
            actor_id="team.lead",
            actor_type=ActorType.COMPLIANCE_OFFICER,
            note="Routing to compliance.",
        )

    row = fetchone(
        "SELECT event_type, actor_id, actor_type, note, payload "
        "FROM cases.case_timeline_event WHERE case_id = %s",
        (case["id"],),
    )
    event_type, actor_id, actor_type, note, payload = row
    assert event_type == "ASSIGNED"
    assert actor_id == "team.lead"
    assert actor_type == "COMPLIANCE_OFFICER"
    assert note == "Routing to compliance."
    assert payload["assigned_to"] == assignee


async def test_reassign_an_already_assigned_case_does_not_force_a_status_jump(service):
    """AC-adjacent: a case can be re-assigned while already ASSIGNED or
    UNDER_INVESTIGATION without forcing a status change."""
    case = insert_case(case_status="UNDER_INVESTIGATION")
    first = await create_user()
    second = await create_user()

    async with database.AsyncSessionLocal() as session:
        await service.assign_case(
            session,
            uuid.UUID(case["id"]),
            first,
            actor_id="team.lead",
            actor_type=ActorType.COMPLIANCE_OFFICER,
        )

    async with database.AsyncSessionLocal() as session:
        updated = await service.assign_case(
            session,
            uuid.UUID(case["id"]),
            second,
            actor_id="team.lead",
            actor_type=ActorType.COMPLIANCE_OFFICER,
        )

    assert updated.case_status == CaseStatus.UNDER_INVESTIGATION
    assert updated.assigned_to == second

    row = fetchone(
        "SELECT COUNT(*) FROM cases.case_timeline_event WHERE case_id = %s AND event_type = 'ASSIGNED'",
        (case["id"],),
    )
    assert row == (2,)


async def test_reassign_while_pending_approval_does_not_force_a_status_jump(service):
    """Judgment call documented in assign_case's docstring: extended beyond
    ASSIGNED/UNDER_INVESTIGATION to every non-terminal status."""
    case = insert_case(case_status="PENDING_APPROVAL")
    assignee = await create_user()

    async with database.AsyncSessionLocal() as session:
        updated = await service.assign_case(
            session,
            uuid.UUID(case["id"]),
            assignee,
            actor_id="team.lead",
            actor_type=ActorType.COMPLIANCE_OFFICER,
        )

    assert updated.case_status == CaseStatus.PENDING_APPROVAL
    assert updated.assigned_to == assignee


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "CLOSED_WITHOUT_ACTION"])
async def test_assign_rejects_a_terminal_case(service, terminal_status):
    case = insert_case(case_status=terminal_status)
    assignee = await create_user()

    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError):
            await service.assign_case(
                session,
                uuid.UUID(case["id"]),
                assignee,
                actor_id="team.lead",
                actor_type=ActorType.COMPLIANCE_OFFICER,
            )


async def test_assign_raises_for_an_unknown_case(service):
    assignee = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.assign_case(
                session,
                uuid.uuid4(),
                assignee,
                actor_id="team.lead",
                actor_type=ActorType.COMPLIANCE_OFFICER,
            )


async def test_assign_rejects_a_nonexistent_assignee(service):
    case = insert_case(case_status="OPEN")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.assign_case(
                session,
                uuid.UUID(case["id"]),
                str(uuid.uuid4()),
                actor_id="team.lead",
                actor_type=ActorType.COMPLIANCE_OFFICER,
            )


async def test_assign_rejects_an_inactive_assignee(service):
    case = insert_case(case_status="OPEN")
    inactive = await create_user(is_active=False)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.assign_case(
                session,
                uuid.UUID(case["id"]),
                inactive,
                actor_id="team.lead",
                actor_type=ActorType.COMPLIANCE_OFFICER,
            )


async def test_assign_rejects_a_malformed_assignee_id(service):
    case = insert_case(case_status="OPEN")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.assign_case(
                session,
                uuid.UUID(case["id"]),
                "not-a-uuid",
                actor_id="team.lead",
                actor_type=ActorType.COMPLIANCE_OFFICER,
            )
