"""ANER-4.3-S4T2: `CaseLifecycleService`'s onboarding-review maker-checker
resolution stand-in — `propose_resolution` / `decide_resolution` /
`list_pending_approvals` — against a real database.

NOT a test of Epic 5.4's Maker-Checker and SoD Engine: see
`case_lifecycle_service.py`'s module docstring for why this is an explicit,
lightweight placeholder.
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.case_lifecycle_service import (
    MIN_SUBSTANTIVE_NOTE_LENGTH,
    CaseLifecycleService,
)
from app.modules.cases.domain.entities.enums import ActorType, CaseStatus, ResolutionAction
from app.modules.cases.exceptions import (
    CaseNotFoundError,
    InvalidCaseStatusTransitionError,
    SelfApprovalNotAllowedError,
    UserNotFoundOrInactiveError,
)
from app.modules.cases.tests.fixtures.auth_fixtures import create_user
from app.modules.cases.tests.fixtures.case_sql import fetchall, fetchone, insert_case
from app.platform.database import services as database
from app.shared.exceptions import ValidationError

LONG_NOTE = "Reviewed the EDD evidence thoroughly; the onboarding may proceed as submitted."
assert len(LONG_NOTE) >= MIN_SUBSTANTIVE_NOTE_LENGTH


@pytest.fixture
def service() -> CaseLifecycleService:
    return CaseLifecycleService()


async def _propose(service: CaseLifecycleService, case_id: str, maker: str) -> None:
    async with database.AsyncSessionLocal() as session:
        await service.propose_resolution(
            session,
            uuid.UUID(case_id),
            ResolutionAction.APPROVE_ONBOARDING,
            LONG_NOTE,
            maker,
            ActorType.COMPLIANCE_OFFICER,
        )


# ── propose_resolution ───────────────────────────────────────────────────


async def test_propose_resolution_moves_case_to_pending_approval(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()

    async with database.AsyncSessionLocal() as session:
        updated = await service.propose_resolution(
            session,
            uuid.UUID(case["id"]),
            ResolutionAction.APPROVE_ONBOARDING,
            LONG_NOTE,
            maker,
            ActorType.COMPLIANCE_OFFICER,
        )

    assert updated.case_status == CaseStatus.PENDING_APPROVAL
    # resolution columns must NOT be written at proposal time
    assert updated.resolution_action is None
    assert updated.resolution_note is None

    row = fetchone(
        "SELECT event_type, payload FROM cases.case_timeline_event WHERE case_id = %s",
        (case["id"],),
    )
    event_type, payload = row
    assert event_type == "APPROVAL_REQUESTED"
    assert payload["proposed_resolution_action"] == "APPROVE_ONBOARDING"
    assert payload["proposed_resolution_note"] == LONG_NOTE
    assert payload["proposed_by"] == maker


async def test_propose_resolution_rejects_a_case_not_under_investigation(service):
    case = insert_case(case_status="ASSIGNED", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError):
            await service.propose_resolution(
                session,
                uuid.UUID(case["id"]),
                ResolutionAction.APPROVE_ONBOARDING,
                LONG_NOTE,
                maker,
                ActorType.COMPLIANCE_OFFICER,
            )


async def test_propose_resolution_rejects_a_short_note(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.propose_resolution(
                session,
                uuid.UUID(case["id"]),
                ResolutionAction.APPROVE_ONBOARDING,
                "too short",
                maker,
                ActorType.COMPLIANCE_OFFICER,
            )


async def test_propose_resolution_rejects_a_nonexistent_proposer(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.propose_resolution(
                session,
                uuid.UUID(case["id"]),
                ResolutionAction.APPROVE_ONBOARDING,
                LONG_NOTE,
                str(uuid.uuid4()),
                ActorType.COMPLIANCE_OFFICER,
            )


async def test_propose_resolution_rejects_an_inactive_proposer(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    inactive = await create_user(is_active=False)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.propose_resolution(
                session,
                uuid.UUID(case["id"]),
                ResolutionAction.APPROVE_ONBOARDING,
                LONG_NOTE,
                inactive,
                ActorType.COMPLIANCE_OFFICER,
            )


# ── decide_resolution: approve ───────────────────────────────────────────


async def test_decide_resolution_approve_writes_resolution_fields_and_resolves(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    checker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        updated = await service.decide_resolution(
            session,
            uuid.UUID(case["id"]),
            "approve",
            checker,
            ActorType.COMPLIANCE_OFFICER,
            checker_note="Confirmed, approving.",
        )

    assert updated.case_status == CaseStatus.RESOLVED
    assert updated.resolution_action == ResolutionAction.APPROVE_ONBOARDING
    assert updated.resolution_note == LONG_NOTE
    assert updated.resolved_by == checker
    assert updated.resolved_at is not None

    row = fetchone(
        "SELECT case_status, resolution_action, resolution_note, resolved_by "
        "FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row == ("RESOLVED", "APPROVE_ONBOARDING", LONG_NOTE, checker)

    events = fetchall(
        "SELECT event_type FROM cases.case_timeline_event WHERE case_id = %s ORDER BY occurred_at",
        (case["id"],),
    )
    assert [r[0] for r in events] == ["APPROVAL_REQUESTED", "APPROVAL_RECEIVED", "RESOLVED"]


# ── decide_resolution: reject ─────────────────────────────────────────────


async def test_decide_resolution_reject_leaves_resolution_columns_untouched(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    checker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        updated = await service.decide_resolution(
            session,
            uuid.UUID(case["id"]),
            "reject",
            checker,
            ActorType.COMPLIANCE_OFFICER,
            checker_note="Not enough evidence, reconsider.",
        )

    assert updated.case_status == CaseStatus.UNDER_INVESTIGATION
    assert updated.resolution_action is None
    assert updated.resolution_note is None
    assert updated.resolved_by is None
    assert updated.resolved_at is None

    row = fetchone(
        "SELECT case_status, resolution_action, resolution_note, resolved_by, resolved_at "
        "FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row == ("UNDER_INVESTIGATION", None, None, None, None)


async def test_decide_resolution_reject_can_be_followed_by_a_new_proposal(service):
    """A rejected proposal must not permanently occupy resolution_action/note
    — a second proposal round on the same case must succeed."""
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    checker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        await service.decide_resolution(
            session, uuid.UUID(case["id"]), "reject", checker, ActorType.COMPLIANCE_OFFICER
        )

    async with database.AsyncSessionLocal() as session:
        second_round = await service.propose_resolution(
            session,
            uuid.UUID(case["id"]),
            ResolutionAction.REJECT_ONBOARDING,
            LONG_NOTE,
            maker,
            ActorType.COMPLIANCE_OFFICER,
        )
    assert second_round.case_status == CaseStatus.PENDING_APPROVAL


# ── self-approval / SoD ───────────────────────────────────────────────────


async def test_decide_resolution_rejects_self_approval(service):
    """The one SoD rule this stand-in enforces: maker cannot decide their own
    proposal."""
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        with pytest.raises(SelfApprovalNotAllowedError):
            await service.decide_resolution(
                session, uuid.UUID(case["id"]), "approve", maker, ActorType.COMPLIANCE_OFFICER
            )

    # the case must remain untouched by the rejected self-approval attempt
    row = fetchone("SELECT case_status FROM cases.compliance_case WHERE id = %s", (case["id"],))
    assert row == ("PENDING_APPROVAL",)


async def test_decide_resolution_rejects_self_rejection_too(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        with pytest.raises(SelfApprovalNotAllowedError):
            await service.decide_resolution(
                session, uuid.UUID(case["id"]), "reject", maker, ActorType.COMPLIANCE_OFFICER
            )


# ── error paths ────────────────────────────────────────────────────────────


async def test_decide_resolution_rejects_a_case_not_pending_approval(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    checker = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(InvalidCaseStatusTransitionError):
            await service.decide_resolution(
                session, uuid.UUID(case["id"]), "approve", checker, ActorType.COMPLIANCE_OFFICER
            )


async def test_decide_resolution_rejects_an_invalid_decision_string(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    checker = await create_user()
    await _propose(service, case["id"], maker)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.decide_resolution(
                session, uuid.UUID(case["id"]), "maybe", checker, ActorType.COMPLIANCE_OFFICER
            )


async def test_decide_resolution_rejects_a_nonexistent_checker(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    await _propose(service, case["id"], maker)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.decide_resolution(
                session, uuid.UUID(case["id"]), "approve", str(uuid.uuid4()), ActorType.COMPLIANCE_OFFICER
            )


async def test_decide_resolution_rejects_an_inactive_checker(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    inactive = await create_user(is_active=False)
    await _propose(service, case["id"], maker)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.decide_resolution(
                session, uuid.UUID(case["id"]), "approve", inactive, ActorType.COMPLIANCE_OFFICER
            )


async def test_decide_resolution_raises_for_an_unknown_case(service):
    checker = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.decide_resolution(
                session, uuid.uuid4(), "approve", checker, ActorType.COMPLIANCE_OFFICER
            )


# ── list_pending_approvals ─────────────────────────────────────────────────


async def test_list_pending_approvals_returns_only_pending_approval_cases(service):
    pending = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    not_pending = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    await _propose(service, pending["id"], maker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_pending_approvals(session)

    ids = {str(c.id) for c in results}
    assert pending["id"] in ids
    assert not_pending["id"] not in ids


async def test_list_pending_approvals_orders_oldest_proposal_first(service):
    case_a = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    case_b = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()

    await _propose(service, case_a["id"], maker)
    await _propose(service, case_b["id"], maker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_pending_approvals(session)

    ids_in_order = [str(c.id) for c in results if str(c.id) in (case_a["id"], case_b["id"])]
    assert ids_in_order == [case_a["id"], case_b["id"]]


async def test_list_pending_approvals_excludes_the_checkers_own_proposals(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_pending_approvals(session, checker_id=maker)

    assert case["id"] not in {str(c.id) for c in results}


async def test_list_pending_approvals_with_checker_id_still_shows_others_proposals(service):
    case = insert_case(case_status="UNDER_INVESTIGATION", case_type="ONBOARDING_REVIEW")
    maker = await create_user()
    other_checker = await create_user()
    await _propose(service, case["id"], maker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_pending_approvals(session, checker_id=other_checker)

    assert case["id"] in {str(c.id) for c in results}
