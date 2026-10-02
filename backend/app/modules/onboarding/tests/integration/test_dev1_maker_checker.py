"""Maker-checker — Developer 1, plans P3-1a–d (decision A, IQ-1, IQ-17).

What is proved here, against a real database:

* **P3-1a, the schema.** Proposals and resolutions are append-only; the database itself
  refuses self-approval (in the resolution row and in the decision row), a resolution
  whose proposer copy lies, a second resolution, a proposal for a move that needs no
  approval, and a decision that claims another company's proposal.
* **P3-1b, the service.** CLEAR, FLAGGED and ON_HOLD are proposed, not made; a
  *different* COMPLIANCE or ADMIN user approves (decision ``decided_by`` = proposer,
  ``approved_by`` = approver), rejects with a reason, or the proposer withdraws. No path
  lets one user take a company there. One open proposal per company, and nothing else
  moves the check while it is open. A proposal whose inputs changed cannot be approved.
* **Concurrency** (allocation §6, final integration): approve vs reject, approve vs a
  new input, approve vs a new cycle — each serialises on the company lock.
* **P3-1c, the API.** ``POST …/decisions`` answers 202 with the proposal; the standing
  serves "awaiting approval" and what *this* user may do; the cross-company queue
  (``GET /background-check/proposals?status=open``) and its ``awaiting=me``; D8 and
  masking.
* **P3-1d.** The sample data's Clear is approved by a second seeded officer.
"""

from __future__ import annotations

import asyncio
import uuid

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.background_check_proposal import (
    BackgroundCheckProposalResolution,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    BackgroundCheckApprovalRequiredError,
    BackgroundCheckApproverRoleNotAllowedError,
    BackgroundCheckPrerequisitesUnmetError,
    BackgroundCheckProposalNotFoundError,
    BackgroundCheckProposalNotYoursError,
    BackgroundCheckProposalOpenError,
    BackgroundCheckProposalResolvedError,
    BackgroundCheckProposalStaleError,
    BackgroundCheckRoleNotAllowedError,
    BackgroundCheckSelfApprovalError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.modules.onboarding.tests.fixtures.compliance import (
    ComplianceUser,
    approve_as,
    propose_and_approve,
    record_required_checks,
)
from app.modules.onboarding.tests.integration._dev1_support import (
    CHECKER,
    MAKER,
    answer_screening,
    clear,
    flag,
    gauge,
    move,
    propose,
    ready_to_clear,
    start_cycle,
)
from app.modules.onboarding.tests.integration._l4b_support import BASE, pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState
ADMIN = ComplianceUser(user_id="dev1-admin", role=UserRole.ADMIN)
THIRD = ComplianceUser(user_id="dev1-third-officer", role=UserRole.COMPLIANCE)


async def _approve(company_id, proposal_id, who: ComplianceUser = CHECKER):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).approve(
            company_id, proposal_id, actor_id=who.user_id, actor_role=who.role
        )


async def _reject(company_id, proposal_id, who: ComplianceUser = CHECKER, reason="not yet"):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).reject(
            company_id, proposal_id, reason=reason, actor_id=who.user_id, actor_role=who.role
        )


async def _withdraw(company_id, proposal_id, who: ComplianceUser = MAKER, reason=None):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).withdraw(
            company_id, proposal_id, reason=reason, actor_id=who.user_id, actor_role=who.role
        )


async def _decisions(company_id) -> list[BackgroundCheckDecision]:
    async with db_services.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(BackgroundCheckDecision)
            .where(BackgroundCheckDecision.company_id == company_id)
            .order_by(BackgroundCheckDecision.decided_at)
        )
        return list(rows.scalars())


async def _resolutions(proposal_id) -> list[BackgroundCheckProposalResolution]:
    async with db_services.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(BackgroundCheckProposalResolution).where(
                BackgroundCheckProposalResolution.proposal_id == proposal_id
            )
        )
        return list(rows.scalars())


def _approval_history(cursor, company_id) -> list:
    cursor.execute(
        "SELECT event_type, from_status, to_status, actor_id, reason, event_metadata "
        "FROM onboarding.exporter_lifecycle_history "
        "WHERE customer_id = %s AND dimension = 'background_check_approval' "
        "ORDER BY created_at, id",
        (str(company_id),),
    )
    return cursor.fetchall()


# ── P3-1a: the schema ────────────────────────────────────────────────────────


async def test_proposals_and_resolutions_cannot_be_updated_or_deleted():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    await _reject(company_id, proposal.id)
    with pg() as cursor:
        for table, column in (
            ("background_check_proposal", "id"),
            ("background_check_proposal_resolution", "proposal_id"),
        ):
            for statement in (
                f"UPDATE onboarding.{table} SET source = 'x' WHERE {column} = %s",
                f"DELETE FROM onboarding.{table} WHERE {column} = %s",
            ):
                with pytest.raises(psycopg2.Error):
                    cursor.execute(statement, (str(proposal.id),))


async def test_the_database_refuses_self_approval_in_the_resolution_and_in_the_decision():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    [head] = [d for d in await _decisions(company_id)]
    with pg() as cursor:
        # The proposer cannot reject (or approve) their own proposal …
        with pytest.raises(psycopg2.errors.CheckViolation, match="resolution_who"):
            cursor.execute(
                "INSERT INTO onboarding.background_check_proposal_resolution (id, proposal_id, "
                " proposed_by, outcome, reason, created_by, source) "
                "VALUES (%s, %s, %s, 'REJECTED', 'no', %s, 'sql')",
                (str(uuid.uuid4()), str(proposal.id), MAKER.user_id, MAKER.user_id),
            )
        # … and a decision cannot be approved by the person who decided it.
        with pytest.raises(psycopg2.errors.CheckViolation, match="maker_checker"):
            cursor.execute(
                "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
                " to_value, decided_by, decided_by_kind, source, reason, risk_rating, "
                " supersedes_decision_id, proposal_id, approved_by, approved_at) "
                "VALUES (%s, %s, 'IN_REVIEW', 'CLEAR', %s, 'MANUAL', 'MANUAL', 'r', 'LOW', %s, "
                " %s, %s, now())",
                (str(uuid.uuid4()), str(company_id), MAKER.user_id, str(head.id),
                 str(proposal.id), MAKER.user_id),
            )


async def test_a_resolution_cannot_lie_about_the_proposer_and_only_one_is_allowed():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    with pg() as cursor:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                "INSERT INTO onboarding.background_check_proposal_resolution (id, proposal_id, "
                " proposed_by, outcome, reason, created_by, source) "
                "VALUES (%s, %s, 'someone-else', 'WITHDRAWN', NULL, 'someone-else', 'sql')",
                (str(uuid.uuid4()), str(proposal.id)),
            )
    await _reject(company_id, proposal.id)
    with pg() as cursor, pytest.raises(psycopg2.errors.UniqueViolation):
        cursor.execute(
            "INSERT INTO onboarding.background_check_proposal_resolution (id, proposal_id, "
            " proposed_by, outcome, reason, created_by, source) "
            "VALUES (%s, %s, %s, 'WITHDRAWN', NULL, %s, 'sql')",
            (str(uuid.uuid4()), str(proposal.id), MAKER.user_id, MAKER.user_id),
        )


async def test_a_proposal_is_only_for_a_move_that_needs_approval():
    company_id = await ready_to_clear(await make_company())
    [head] = await _decisions(company_id)
    with pg() as cursor:
        cursor.execute(
            "SELECT id FROM onboarding.check_cycle WHERE company_id = %s", (str(company_id),)
        )
        [(cycle_id,)] = cursor.fetchall()
        with pytest.raises(psycopg2.errors.CheckViolation, match="proposal_move"):
            cursor.execute(
                "INSERT INTO onboarding.background_check_proposal (id, company_id, "
                " based_on_decision_id, from_value, to_value, reason, inputs_fingerprint, "
                " evidence_count, cycle_id, rules_version, created_by, source) "
                "VALUES (%s, %s, %s, 'IN_REVIEW', 'MORE_INFO', 'r', %s, 0, %s, 'v', 'm', 'sql')",
                (str(uuid.uuid4()), str(company_id), str(head.id), "a" * 64, cycle_id),
            )


async def test_a_decision_cannot_claim_another_companys_proposal():
    first = await ready_to_clear(await make_company())
    second = await ready_to_clear(await make_company())
    proposal = await propose(first)
    [head] = await _decisions(second)
    with pg() as cursor, pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cursor.execute(
            "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
            " to_value, decided_by, decided_by_kind, source, reason, risk_rating, "
            " supersedes_decision_id, proposal_id, approved_by, approved_at) "
            "VALUES (%s, %s, 'IN_REVIEW', 'CLEAR', %s, 'MANUAL', 'MANUAL', 'r', 'LOW', %s, "
            " %s, %s, now())",
            (str(uuid.uuid4()), str(second), MAKER.user_id, str(head.id), str(proposal.id),
             CHECKER.user_id),
        )


# ── P3-1b: propose, approve, reject, withdraw ────────────────────────────────


async def test_no_single_user_path_reaches_clear_flagged_or_on_hold():
    company_id = await ready_to_clear(await make_company())
    async with db_services.AsyncSessionLocal() as db:
        service = BackgroundCheckService(db)
        with pytest.raises(BackgroundCheckApprovalRequiredError):
            await service.clear(
                company_id, risk=BackgroundCheckRisk.LOW, reason="r",
                actor_id=MAKER.user_id, actor_role=UserRole.ADMIN,
            )
        with pytest.raises(BackgroundCheckApprovalRequiredError):
            await service.flag(
                company_id, reason="r", actor_id=MAKER.user_id, actor_role=UserRole.ADMIN
            )
        with pytest.raises(BackgroundCheckApprovalRequiredError):
            await service.record_decision(
                company_id, to_value=State.CLEAR, reason="r", risk=BackgroundCheckRisk.LOW,
                actor_id=MAKER.user_id, actor_role=UserRole.COMPLIANCE,
            )
    assert await gauge(company_id) is State.IN_REVIEW


async def test_a_proposed_clear_leaves_the_gauge_and_records_the_proposal():
    company_id = await ready_to_clear(await make_company())
    decisions_before = len(await _decisions(company_id))
    proposal = await propose(company_id)

    assert (proposal.status, proposal.to_value, proposal.proposed_by) == (
        "OPEN", State.CLEAR, MAKER.user_id
    )
    assert proposal.risk_rating is BackgroundCheckRisk.LOW
    assert proposal.evidence_count > 0 and proposal.rules_version.endswith("kyb-aml-sanctions")
    assert await gauge(company_id) is State.IN_REVIEW
    assert len(await _decisions(company_id)) == decisions_before
    with pg() as cursor:
        [row] = _approval_history(cursor, company_id)
    assert row[0] == "background_check_proposed"
    assert (row[1], row[2], row[3]) == (None, "OPEN", MAKER.user_id)
    assert row[5]["proposal_id"] == str(proposal.id) and row[5]["to_value"] == "CLEAR"


async def test_a_second_officer_approves_and_the_decision_names_both():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    approved = await _approve(company_id, proposal.id)

    decision = approved.decision
    assert decision.to_value is State.CLEAR
    assert (decision.decided_by, decision.approved_by) == (MAKER.user_id, CHECKER.user_id)
    assert decision.proposal_id == proposal.id and decision.approved_at is not None
    assert decision.risk_rating is BackgroundCheckRisk.LOW
    assert decision.reason == proposal.reason
    assert approved.proposal.status == "APPROVED"
    assert approved.proposal.decision_id == decision.id
    assert approved.proposal.resolved_by == CHECKER.user_id
    assert await gauge(company_id) is State.CLEAR
    with pg() as cursor:
        rows = _approval_history(cursor, company_id)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("background_check_proposed", None, "OPEN", MAKER.user_id),
        ("background_check_approved", "OPEN", "APPROVED", CHECKER.user_id),
    ]
    assert rows[1][5]["decision_id"] == str(decision.id)


@pytest.mark.parametrize(
    ("maker", "checker"),
    [
        (MAKER, ADMIN),
        (ADMIN, MAKER),
    ],
    ids=["admin-approves-compliance", "compliance-approves-admin"],
)
async def test_admin_and_compliance_approve_each_other(maker, checker):
    company_id = await ready_to_clear(await make_company())
    decision = await approve_as(checker, company_id, maker=maker)
    assert (decision.decided_by, decision.approved_by) == (maker.user_id, checker.user_id)


async def test_the_proposer_cannot_approve_or_reject_their_own_proposal():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    with pytest.raises(BackgroundCheckSelfApprovalError):
        await _approve(company_id, proposal.id, who=MAKER)
    with pytest.raises(BackgroundCheckSelfApprovalError):
        await _reject(company_id, proposal.id, who=MAKER)
    assert await gauge(company_id) is State.IN_REVIEW
    assert await _resolutions(proposal.id) == []


async def test_operations_neither_proposes_nor_approves():
    company_id = await ready_to_clear(await make_company())
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(BackgroundCheckRoleNotAllowedError):
            await BackgroundCheckService(db).propose(
                company_id, to_value=State.CLEAR, reason="r", risk=BackgroundCheckRisk.LOW,
                actor_id="rm", actor_role=UserRole.OPERATIONS,
            )
    proposal = await propose(company_id)
    with pytest.raises(BackgroundCheckApproverRoleNotAllowedError):
        await _approve(company_id, proposal.id, who=ComplianceUser("rm", UserRole.OPERATIONS))
    with pytest.raises(BackgroundCheckApproverRoleNotAllowedError):
        await _reject(company_id, proposal.id, who=ComplianceUser("rm", UserRole.OPERATIONS))


async def test_a_rejection_needs_a_reason_and_leaves_the_check_where_it_was():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    from app.shared.exceptions import ValidationError as SharedValidationError

    with pytest.raises(SharedValidationError):
        await _reject(company_id, proposal.id, reason="   ")
    rejected = await _reject(company_id, proposal.id, reason="AML needs a second look")
    assert (rejected.status, rejected.resolution_reason) == ("REJECTED", "AML needs a second look")
    assert await gauge(company_id) is State.IN_REVIEW
    # Closed: it cannot be approved now, and a new proposal may be made.
    with pytest.raises(BackgroundCheckProposalResolvedError):
        await _approve(company_id, proposal.id)
    again = await propose(company_id)
    assert again.id != proposal.id


async def test_only_the_proposer_withdraws():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    with pytest.raises(BackgroundCheckProposalNotYoursError):
        await _withdraw(company_id, proposal.id, who=CHECKER)
    withdrawn = await _withdraw(company_id, proposal.id, reason="wrong risk")
    assert (withdrawn.status, withdrawn.resolved_by) == ("WITHDRAWN", MAKER.user_id)
    assert await gauge(company_id) is State.IN_REVIEW


async def test_a_proposal_of_another_company_is_not_found():
    first = await ready_to_clear(await make_company())
    other = await make_company()
    proposal = await propose(first)
    with pytest.raises(BackgroundCheckProposalNotFoundError):
        await _approve(other, proposal.id)


async def test_one_open_proposal_per_company_and_nothing_else_moves_the_check():
    company_id = await ready_to_clear(await make_company())
    await propose(company_id)
    with pytest.raises(BackgroundCheckProposalOpenError):
        await propose(company_id, to_value=State.FLAGGED, risk=None)
    with pytest.raises(BackgroundCheckProposalOpenError):
        await move(company_id, State.MORE_INFO)
    with pytest.raises(BackgroundCheckProposalOpenError):
        await start_cycle(company_id)
    assert await gauge(company_id) is State.IN_REVIEW


async def test_clear_is_refused_at_proposal_when_prerequisites_are_missing():
    """A proposal that could never be approved is refused when it is made, naming what
    is missing — rule B's three included."""
    company_id = await make_company()
    await answer_screening(company_id)
    from app.modules.onboarding.tests.integration._dev1_support import start_review

    await start_review(company_id)
    with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as caught:
        await propose(company_id)
    assert caught.value.extensions["unmet"] == ["kyb_passed", "aml_passed", "sanctions_passed"]


async def test_flagged_and_on_hold_are_proposed_and_approved_too():
    company_id = await ready_to_clear(await make_company())
    held = await propose(company_id, to_value=State.FLAGGED, risk=None, reason="adverse media")
    assert await gauge(company_id) is State.IN_REVIEW
    await _approve(company_id, held.id)
    assert await gauge(company_id) is State.FLAGGED

    on_hold = await propose(company_id, to_value=State.ON_HOLD, risk=None, reason="regulator")
    assert await gauge(company_id) is State.FLAGGED  # a proposed ON_HOLD leaves it FLAGGED
    decision = (await _approve(company_id, on_hold.id, who=ADMIN)).decision
    assert decision.to_value is State.ON_HOLD and decision.approved_by == ADMIN.user_id


async def test_approval_refuses_a_proposal_whose_inputs_changed():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    await record_required_checks(company_id, types=("AML",))  # a new result since

    with pytest.raises(BackgroundCheckProposalStaleError) as caught:
        await _approve(company_id, proposal.id)
    assert "inputs changed" in caught.value.extensions["why"]
    assert await gauge(company_id) is State.IN_REVIEW
    async with db_services.AsyncSessionLocal() as db:
        awaiting = await BackgroundCheckService(db).open_proposal(company_id)
    assert awaiting is not None and awaiting[1] == "its inputs changed since it was proposed"
    # It can still be rejected — that is how a stale proposal is cleared away.
    await _reject(company_id, proposal.id, reason="out of date")
    fresh = await propose(company_id)
    await _approve(company_id, fresh.id)
    assert await gauge(company_id) is State.CLEAR


async def test_approval_promotes_a_qualified_prospect_in_the_same_transaction():
    company_id = await ready_to_clear(await make_prospect())
    proposal = await propose(company_id)
    async with db_services.AsyncSessionLocal() as db:
        journey = await db.scalar(
            select(ExporterProfile.journey).where(ExporterProfile.customer_id == company_id)
        )
    assert journey is ExporterJourney.PROSPECT  # not on proposal
    await _approve(company_id, proposal.id)
    async with db_services.AsyncSessionLocal() as db:
        journey = await db.scalar(
            select(ExporterProfile.journey).where(ExporterProfile.customer_id == company_id)
        )
    assert journey is ExporterJourney.CUSTOMER


async def test_maker_checker_off_records_directly(monkeypatch):
    """IQ-17: the switch exists for local/test only (the start-up guard is unit-tested);
    with it off, a single user's CLEAR is recorded at once."""
    from app.platform.configuration import config

    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_MAKER_CHECKER", False)
    company_id = await ready_to_clear(await make_company())
    async with db_services.AsyncSessionLocal() as db:
        decision = await BackgroundCheckService(db).clear(
            company_id, risk=BackgroundCheckRisk.LOW, reason="r",
            actor_id=MAKER.user_id, actor_role=UserRole.COMPLIANCE,
        )
    assert decision.approved_by is None and decision.proposal_id is None
    assert await gauge(company_id) is State.CLEAR


# ── Concurrency (final integration, allocation §6) ───────────────────────────


async def test_approve_and_reject_at_once_resolve_the_proposal_exactly_once():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    results = await asyncio.gather(
        _approve(company_id, proposal.id),
        _reject(company_id, proposal.id, who=THIRD),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1
    assert isinstance(failures[0], BackgroundCheckProposalResolvedError)
    [resolution] = await _resolutions(proposal.id)
    expected = State.CLEAR if resolution.outcome == "APPROVED" else State.IN_REVIEW
    assert await gauge(company_id) is expected


async def test_approve_and_a_new_input_at_once_never_approve_unseen_inputs():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    approved, inputs = await asyncio.gather(
        _approve(company_id, proposal.id),
        record_required_checks(company_id, types=("SANCTIONS",)),
        return_exceptions=True,
    )
    assert not isinstance(inputs, Exception)
    [new_result] = inputs
    if isinstance(approved, Exception):
        # The input committed first: the proposal is stale, nothing was decided.
        assert isinstance(approved, BackgroundCheckProposalStaleError)
        assert await gauge(company_id) is State.IN_REVIEW
    else:
        # The approval committed first: the new result is not in what it rested on.
        async with db_services.AsyncSessionLocal() as db:
            pinned = (
                await db.execute(
                    select(BackgroundCheckEvidence.verification_result_id).where(
                        BackgroundCheckEvidence.decision_id == approved.decision.id
                    )
                )
            ).scalars().all()
        assert new_result.id not in set(pinned)
        assert await gauge(company_id) is State.CLEAR


async def test_approve_and_a_cycle_start_at_once_keep_one_unbroken_chain():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    approved, started = await asyncio.gather(
        _approve(company_id, proposal.id), start_cycle(company_id), return_exceptions=True
    )
    assert not isinstance(approved, Exception)
    decisions = await _decisions(company_id)
    successors = [d.supersedes_decision_id for d in decisions if d.supersedes_decision_id]
    assert len(successors) == len(set(successors))  # never forked
    if isinstance(started, Exception):
        # The start waited behind the open proposal and was refused.
        assert isinstance(started, BackgroundCheckProposalOpenError)
        assert await gauge(company_id) is State.CLEAR
    else:
        # The approval came first; the Re-KYC then reopened the Clear in cycle 2.
        assert started.cycle.number == 2 and started.reopen is not None
        assert await gauge(company_id) is State.IN_REVIEW


# ── P3-1c: the API ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, tuple[str, str]]:
    """``name → (user_id, token)``: two compliance officers, an admin, an RM, a
    developer."""
    return {
        "maker": await user_with_role(client, UserRole.COMPLIANCE, email_prefix="mc-maker"),
        "checker": await user_with_role(client, UserRole.COMPLIANCE, email_prefix="mc-checker"),
        "admin": await user_with_role(client, UserRole.ADMIN, email_prefix="mc-admin"),
        "rm": await user_with_role(client, UserRole.OPERATIONS, email_prefix="mc-rm"),
        "developer": await user_with_role(client, UserRole.DEVELOPER, email_prefix="mc-dev"),
    }


def _pan() -> str:
    import random
    import string

    letters = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
    return f"{letters}{random.randint(0, 9999):04d}{random.choice(string.ascii_uppercase)}"


async def _company_with_identifiers(client: AsyncClient, token: str) -> tuple[str, str]:
    pan = _pan()
    created = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": f"Maker Checker Co {uuid.uuid4().hex[:8]}", "country": "IN",
              "pan": pan, "gstins": [f"27{pan}1Z5"]},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    company_id = created.json()["customer_id"]
    await ready_to_clear(uuid.UUID(company_id))
    return company_id, pan


async def _standing(client, company_id, token) -> dict:
    response = await client.get(
        f"{BASE}/exporters/{company_id}/background-check", headers=auth_header(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_post_decisions_proposes_and_the_standing_serves_who_may_do_what(
    client: AsyncClient, people
):
    maker_id, maker = people["maker"]
    checker_id, checker = people["checker"]
    company_id, _ = await _company_with_identifiers(client, maker)

    before = await _standing(client, company_id, maker)
    clear = next(m for m in before["allowed_moves"] if m["to_value"] == "CLEAR")
    assert clear["approval_required"] is True
    assert before["required_checks"] == [
        {"verification_type": "KYB", "state": "PASSED"},
        {"verification_type": "AML", "state": "PASSED"},
        {"verification_type": "SANCTIONS", "state": "PASSED"},
    ]

    response = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "CLEAR", "reason": "All in order", "risk_rating": "LOW",
              "from_value": "IN_REVIEW"},
        headers=auth_header(maker),
    )
    assert response.status_code == 202, response.text
    proposal = response.json()
    assert (proposal["status"], proposal["proposed_by"]) == ("OPEN", maker_id)
    assert proposal["allowed_actions"] == ["WITHDRAW"]

    as_maker = await _standing(client, company_id, maker)
    assert as_maker["value"] == "IN_REVIEW" and as_maker["awaiting_approval"] is True
    assert as_maker["allowed_moves"] == [] and as_maker["allowed_cycle_actions"] == []
    assert as_maker["open_proposal"]["allowed_actions"] == ["WITHDRAW"]
    as_checker = await _standing(client, company_id, checker)
    assert as_checker["open_proposal"]["allowed_actions"] == ["APPROVE", "REJECT"]
    as_rm = await _standing(client, company_id, people["rm"][1])
    assert as_rm["open_proposal"]["allowed_actions"] == []

    # The maker cannot approve their own; the second officer can.
    own = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/proposals/{proposal['id']}/approve",
        headers=auth_header(maker),
    )
    assert own.status_code == 403 and own.json()["error_code"] == "BACKGROUND_CHECK_SELF_APPROVAL"
    approved = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/proposals/{proposal['id']}/approve",
        headers=auth_header(checker),
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["decision"]["decided_by"] == maker_id
    assert body["decision"]["approved_by"] == checker_id
    assert body["decision"]["approved_by_name"]
    assert body["proposal"]["status"] == "APPROVED"

    after = await _standing(client, company_id, maker)
    assert after["value"] == "CLEAR" and after["awaiting_approval"] is False
    decisions = (
        await client.get(
            f"{BASE}/exporters/{company_id}/background-check/decisions",
            headers=auth_header(maker),
        )
    ).json()["decisions"]
    assert decisions[0]["approved_by"] == checker_id and decisions[0]["expires_at"]


async def test_reject_and_withdraw_through_the_api(client: AsyncClient, people):
    maker = people["maker"][1]
    checker = people["checker"][1]
    company_id, _ = await _company_with_identifiers(client, maker)
    url = f"{BASE}/exporters/{company_id}/background-check"

    first = (await client.post(f"{url}/decisions", json={"to_value": "FLAGGED", "reason": "hit"},
                               headers=auth_header(maker))).json()
    no_reason = await client.post(f"{url}/proposals/{first['id']}/reject", json={},
                                  headers=auth_header(checker))
    assert no_reason.status_code == 422
    rejected = await client.post(f"{url}/proposals/{first['id']}/reject",
                                 json={"reason": "false positive"}, headers=auth_header(checker))
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"

    second = (await client.post(f"{url}/decisions", json={"to_value": "FLAGGED", "reason": "hit"},
                                headers=auth_header(maker))).json()
    not_mine = await client.post(f"{url}/proposals/{second['id']}/withdraw",
                                 headers=auth_header(checker))
    assert not_mine.status_code == 403
    assert not_mine.json()["error_code"] == "BACKGROUND_CHECK_PROPOSAL_NOT_YOURS"
    withdrawn = await client.post(f"{url}/proposals/{second['id']}/withdraw",
                                  headers=auth_header(maker))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "WITHDRAWN"
    again = await client.post(f"{url}/proposals/{second['id']}/approve",
                              headers=auth_header(checker))
    assert again.status_code == 409
    assert again.json()["error_code"] == "BACKGROUND_CHECK_PROPOSAL_RESOLVED"

    listing = (await client.get(f"{url}/proposals", headers=auth_header(people["rm"][1]))).json()
    assert [p["status"] for p in listing["proposals"]] == ["WITHDRAWN", "REJECTED"]


async def test_the_rm_never_approves_and_developer_sees_nothing(client: AsyncClient, people):
    maker = people["maker"][1]
    company_id, _ = await _company_with_identifiers(client, maker)
    proposal = (await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "CLEAR", "reason": "ok", "risk_rating": "LOW"},
        headers=auth_header(maker),
    )).json()
    for action in ("approve", "reject", "withdraw"):
        response = await client.post(
            f"{BASE}/exporters/{company_id}/background-check/proposals/{proposal['id']}/{action}",
            json={"reason": "x"} if action == "reject" else None,
            headers=auth_header(people["rm"][1]),
        )
        assert response.status_code == 403, (action, response.text)
    for path in (
        f"/exporters/{company_id}/background-check/proposals",
        "/background-check/proposals?status=open",
    ):
        response = await client.get(f"{BASE}{path}", headers=auth_header(people["developer"][1]))
        assert response.status_code == 403
    queue = await client.get(
        f"{BASE}/background-check/proposals?status=open", headers=auth_header(people["rm"][1])
    )
    assert queue.status_code == 403
    with pg() as cursor:
        cursor.execute(
            "SELECT count(*) FROM onboarding.background_check_decision "
            "WHERE company_id = %s AND to_value = 'CLEAR'",
            (company_id,),
        )
        assert cursor.fetchone()[0] == 0


async def test_the_queue_lists_what_awaits_me_and_not_my_own(client: AsyncClient, people):
    maker_id, maker = people["maker"]
    checker = people["checker"][1]
    company_id, pan = await _company_with_identifiers(client, maker)
    proposal = (await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "CLEAR", "reason": "ok", "risk_rating": "MEDIUM"},
        headers=auth_header(maker),
    )).json()

    async def newest_page(token: str) -> dict:
        """The open queue is oldest first, and the shared test database keeps the open
        proposals of earlier runs: read the last page, where this one is."""
        url = f"{BASE}/background-check/proposals"  # status=open is the default
        first = await client.get(url, params={"awaiting": "me", "limit": 1},
                                 headers=auth_header(token))
        assert first.status_code == 200, first.text
        total = first.json()["total"]
        last = await client.get(
            url,
            params={"awaiting": "me", "limit": 100, "offset": max(total - 100, 0)},
            headers=auth_header(token),
        )
        assert last.status_code == 200
        return last.json()

    mine = await newest_page(maker)
    assert proposal["id"] not in {p["id"] for p in mine["proposals"]}
    theirs = await newest_page(checker)
    [listed] = [p for p in theirs["proposals"] if p["id"] == proposal["id"]]
    assert listed["company_name"].startswith("Maker Checker Co")
    assert listed["proposed_by"] == maker_id and listed["status"] == "OPEN"
    assert listed["allowed_actions"] == ["APPROVE", "REJECT"]
    # No identifier is served, to anyone.
    text = str(theirs)
    assert pan not in text and "'pan'" not in text and "gstin" not in text
    approved_list = await client.get(
        f"{BASE}/background-check/proposals?status=approved&limit=1", headers=auth_header(checker)
    )
    assert approved_list.status_code == 200


async def test_proposal_shapes_carry_no_identifier_for_operations(client: AsyncClient, people):
    maker = people["maker"][1]
    company_id, pan = await _company_with_identifiers(client, maker)
    await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "CLEAR", "reason": "ok", "risk_rating": "LOW"},
        headers=auth_header(maker),
    )
    rm = people["rm"][1]
    for path in (
        f"/exporters/{company_id}/background-check",
        f"/exporters/{company_id}/background-check/proposals",
    ):
        response = await client.get(f"{BASE}{path}", headers=auth_header(rm))
        assert response.status_code == 200
        for forbidden in (pan, f"27{pan}1Z5", '"pan"', '"gstin', '"iec"', '"cin"', "contact_email"):
            assert forbidden not in response.text, (path, forbidden)


async def test_developer_does_not_receive_approval_history(client: AsyncClient, people):
    maker = people["maker"][1]
    company_id, _ = await _company_with_identifiers(client, maker)
    await propose_and_approve(
        client, company_id, maker_token=maker, checker_token=people["checker"][1]
    )
    staff = (await client.get(f"{BASE}/exporters/{company_id}/history",
                              params={"limit": 200}, headers=auth_header(maker))).json()
    assert "background_check_approval" in {e["dimension"] for e in staff["entries"]}
    developer = await client.get(f"{BASE}/exporters/{company_id}/history",
                                 params={"limit": 200}, headers=auth_header(people["developer"][1]))
    assert developer.status_code == 200
    assert "background_check_approval" not in {e["dimension"] for e in developer.json()["entries"]}


# ── P3-1d: sample data and the shared helper ─────────────────────────────────


async def test_the_sample_seeder_clears_with_two_officers_and_rule_b_checks():
    """The seeder's own path, on a fresh company: the sample actor proposes, the second
    seeded officer approves, after recording KYB, AML and sanctions."""
    from app.modules.onboarding.sample_data import SAMPLE_DATA_ACTOR
    from app.modules.onboarding.sample_data_background_check import (
        SAMPLE_CHECKS,
        SAMPLE_DATA_CHECKER,
        _ensure_gauge,
        _ensure_screening,
    )

    company_id = await make_company()
    sample = SAMPLE_CHECKS["company-b"]
    await _ensure_screening(company_id, sample, actor_id=SAMPLE_DATA_ACTOR)
    assert await _ensure_gauge(company_id, sample, actor_id=SAMPLE_DATA_ACTOR) == 2
    clearing = (await _decisions(company_id))[-1]
    assert clearing.to_value is State.CLEAR
    assert (clearing.decided_by, clearing.approved_by) == (SAMPLE_DATA_ACTOR, SAMPLE_DATA_CHECKER)
    async with db_services.AsyncSessionLocal() as db:
        inputs = await ComplianceInputsService(db).company_inputs(company_id)
    assert {v.verification_type for v in inputs.verifications} >= {"KYB", "AML", "SANCTIONS"}
    # Converges: a second run decides nothing.
    assert await _ensure_gauge(company_id, sample, actor_id=SAMPLE_DATA_ACTOR) == 0

    flagged = await make_company()
    await _ensure_screening(flagged, SAMPLE_CHECKS["company-c"], actor_id=SAMPLE_DATA_ACTOR)
    await _ensure_gauge(flagged, SAMPLE_CHECKS["company-c"], actor_id=SAMPLE_DATA_ACTOR)
    flag_decision = (await _decisions(flagged))[-1]
    assert flag_decision.to_value is State.FLAGGED
    assert flag_decision.approved_by == SAMPLE_DATA_CHECKER


async def test_the_dev1_helpers_use_two_people():
    company_id = await ready_to_clear(await make_company())
    decision = await clear(company_id)
    assert (decision.decided_by, decision.approved_by) == (MAKER.user_id, CHECKER.user_id)
    other = await ready_to_clear(await make_company())
    flagged = await flag(other)
    assert flagged.approved_by == CHECKER.user_id



# ── P3-2: rule B through the service ─────────────────────────────────────────


async def test_rule_b_counts_only_the_companys_own_current_cycle_results():
    """Company association: another company's results, and a deal buyer's, do not
    count towards this company's KYB, AML and sanctions."""
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
        VerificationType,
    )
    from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
    from app.modules.onboarding.tests.integration._dev1_support import start_review
    from app.modules.onboarding.tests.integration._l4b_support import deal_buyer

    seller, _deal_id, buyer_id = await deal_buyer()
    await answer_screening(seller)
    await start_review(seller)
    other = await make_company()
    await record_required_checks(other)  # someone else's KYB, AML, sanctions
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.SANCTIONS,
            VerificationEntityType.BUYER,
            buyer_id,
            provider="manual",
            payload={"status": "PASSED"},
            actor_id="tester",
            evidence=VerificationEvidence(note="buyer screened"),
        )
    with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as caught:
        await propose(seller)
    assert caught.value.extensions["unmet"] == ["kyb_passed", "aml_passed", "sanctions_passed"]

    await record_required_checks(seller)
    assert (await approve_as(CHECKER, seller, maker=MAKER)).to_value is State.CLEAR


async def test_a_failed_check_after_a_proposal_stops_its_approval_and_names_the_type():
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    await record_required_checks(company_id, types=("SANCTIONS",), status="FAILED")

    with pytest.raises(BackgroundCheckProposalStaleError):
        await _approve(company_id, proposal.id)
    await _reject(company_id, proposal.id, reason="sanctions failed")
    with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as caught:
        await propose(company_id)
    assert caught.value.extensions["unmet"] == ["sanctions_passed"]
    assert await gauge(company_id) is State.IN_REVIEW
