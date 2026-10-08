"""Who holds a background-check review, and who may approve it.

What is proved here, against a real database:

* **Claim, assign, release.** A started check waits unassigned; a COMPLIANCE or ADMIN
  user claims it once; a holder of ``compliance:assign`` (a custom lead role) or ADMIN
  assigns and reassigns, with a reason when taking it from someone; plain COMPLIANCE
  cannot; the RM never reviews; a reviewer with an open proposal cannot release.
* **The reviewer's moves.** Requesting information and proposing are the reviewer's: an
  unassigned review is claimed by whoever makes one, another person's is refused. A
  proposal never names a checker, and ON_HOLD is not a review outcome.
* **Independence.** The proposer, the review's reviewer and the company's RM never
  approve; a HIGH or CRITICAL CLEAR is approved only by ADMIN or a holder of
  ``compliance:approve_high_risk``, in one step.
* **After a decision.** The review ends (and the database refuses a reviewer on a
  decided company); a rejection keeps the reviewer and counts; a lead withdraws for an
  absent proposer; a reassessment hands the review to whoever makes it.
* **The worklists**: Awaiting review, My reviews, the lead views, information requests,
  counts for the badges, recent decisions, the approval queue's eligibility, and the
  DEVELOPER refusal. And a claim racing an assignment leaves one winner.
"""

from __future__ import annotations

import asyncio
import uuid

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_worklists import ComplianceWorklists
from app.modules.onboarding.domain.assignment import APPROVE_HIGH_RISK, ASSIGN_REVIEWS
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycleKind
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    BackgroundCheckConflictOfInterestError,
    BackgroundCheckMoveNotAllowedError,
    BackgroundCheckProposalNotYoursError,
    BackgroundCheckProposalOpenError,
    HighRiskApprovalRequiredError,
    ReviewAlreadyAssignedError,
    ReviewAssignedToOtherError,
    ReviewAssignNotAllowedError,
    ReviewerIsRelationshipManagerError,
    ReviewerNotEligibleError,
    ReviewReasonRequiredError,
)
from app.modules.onboarding.tests.fixtures.auth import (
    auth_header,
    deactivate,
    user_with_permissions,
    user_with_role,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import record_required_checks
from app.modules.onboarding.tests.integration._compliance_support import (
    answer_screening,
    gauge,
    start_review,
)
from app.modules.onboarding.tests.integration._verification_support import BASE, pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState
C, A = UserRole.COMPLIANCE, UserRole.ADMIN
SENIOR = frozenset({APPROVE_HIGH_RISK})
LEAD = frozenset({ASSIGN_REVIEWS})


@pytest.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, tuple[str, str]]:
    return {
        "a": await user_with_role(client, C, email_prefix="rv-a"),
        "b": await user_with_role(client, C, email_prefix="rv-b"),
        "c": await user_with_role(client, C, email_prefix="rv-c"),
        "lead": await user_with_permissions(client, C, ("compliance", "assign"), email_prefix="rv-lead"),
        "senior": await user_with_permissions(
            client, C, ("compliance", "approve_high_risk"), email_prefix="rv-senior"
        ),
        "admin": await user_with_role(client, A, email_prefix="rv-admin"),
        "rm": await user_with_role(client, UserRole.OPERATIONS, email_prefix="rv-rm"),
        "developer": await user_with_role(client, UserRole.DEVELOPER, email_prefix="rv-dev"),
    }


def svc(db) -> BackgroundCheckService:
    return BackgroundCheckService(db)


async def ready(company_id: uuid.UUID | None = None) -> uuid.UUID:
    company_id = company_id or await make_company()
    await answer_screening(company_id)
    await record_required_checks(company_id, actor_id="rv-checks")
    await start_review(company_id)
    return company_id


async def reviewer_of(company_id: uuid.UUID) -> tuple[str | None, object]:
    async with db_services.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(
                    ExporterProfile.background_check_reviewer_id,
                    ExporterProfile.background_check_reviewer_assigned_at,
                ).where(ExporterProfile.customer_id == company_id)
            )
        ).one()
    return row[0], row[1]


async def assignment_rows(company_id: uuid.UUID) -> list[ExporterLifecycleHistory]:
    async with db_services.AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ExporterLifecycleHistory)
                    .where(
                        ExporterLifecycleHistory.customer_id == company_id,
                        ExporterLifecycleHistory.dimension == "background_check_assignment",
                    )
                    .order_by(ExporterLifecycleHistory.created_at)
                )
            ).all()
        )


async def set_rm(company_id: uuid.UUID, user_id: str) -> None:
    """Scaffolding: make someone the company's RM directly (e.g. a user whose role
    changed after they were assigned)."""
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .values(relationship_manager_user_id=uuid.UUID(user_id))
        )
        await db.commit()


async def propose(company_id, actor, *, to=State.CLEAR, risk=BackgroundCheckRisk.LOW):
    async with db_services.AsyncSessionLocal() as db:
        return await svc(db).propose(
            company_id,
            to_value=to,
            reason="ready",
            risk=risk if to is State.CLEAR else None,
            actor_id=actor,
            actor_role=C,
        )


async def approve(company_id, proposal_id, actor, *, role=C, perms=frozenset()):
    async with db_services.AsyncSessionLocal() as db:
        return await svc(db).approve(
            company_id, proposal_id, actor_id=actor, actor_role=role, actor_permissions=perms
        )


# ── Claim, assign, release ──────────────────────────────────────────────────


async def test_a_started_check_waits_unassigned_and_is_claimed_once(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    assert (await reviewer_of(company_id))[0] is None
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).claim_review(company_id, actor_id=a, actor_role=C)
    reviewer, since = await reviewer_of(company_id)
    assert reviewer == a and since is not None
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewAlreadyAssignedError):
            await svc(db).claim_review(company_id, actor_id=b, actor_role=C)
    # Claiming one's own review again is harmless.
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).claim_review(company_id, actor_id=a, actor_role=C)
    [row] = await assignment_rows(company_id)
    assert row.event_type == "review_claimed" and row.actor_id == a


async def test_operations_cannot_claim_and_the_rm_never_reviews(people):
    a, _ = people["a"]
    company_id = await ready()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewerNotEligibleError):
            await svc(db).claim_review(company_id, actor_id="ops", actor_role=UserRole.OPERATIONS)
    await set_rm(company_id, a)  # someone who was an RM and is now in compliance
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewerIsRelationshipManagerError):
            await svc(db).claim_review(company_id, actor_id=a, actor_role=C)


async def test_a_lead_assigns_and_reassigns_with_a_reason(people):
    a, _ = people["a"]
    b, _ = people["b"]
    lead, _ = people["lead"]
    company_id = await ready()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewAssignNotAllowedError):
            await svc(db).assign_review(company_id, user_id=a, reason=None, actor_id=b, actor_role=C)
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).assign_review(
            company_id, user_id=a, reason=None, actor_id=lead, actor_role=C, actor_permissions=LEAD
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewReasonRequiredError):
            await svc(db).assign_review(
                company_id, user_id=b, reason=" ", actor_id=lead, actor_role=C, actor_permissions=LEAD
            )
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).assign_review(
            company_id, user_id=b, reason="A is away", actor_id=lead, actor_role=C,
            actor_permissions=LEAD,
        )
    assert (await reviewer_of(company_id))[0] == b
    rows = await assignment_rows(company_id)
    assert [r.event_type for r in rows] == ["review_assigned", "review_reassigned"]
    assert rows[1].reason == "A is away"
    assert rows[1].event_metadata["from_user_id"] == a


async def test_admin_assigns_without_a_grant_but_not_to_the_rm_or_a_non_reviewer(people):
    admin, _ = people["admin"]
    a, _ = people["a"]
    rm, _ = people["rm"]
    company_id = await ready()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewerNotEligibleError):
            await svc(db).assign_review(company_id, user_id=rm, reason=None, actor_id=admin, actor_role=A)
    await set_rm(company_id, a)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewerIsRelationshipManagerError):
            await svc(db).assign_review(company_id, user_id=a, reason=None, actor_id=admin, actor_role=A)
    other, _ = people["c"]
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).assign_review(company_id, user_id=other, reason=None, actor_id=admin, actor_role=A)
    assert (await reviewer_of(company_id))[0] == other


async def test_release_returns_the_review_but_not_while_the_reviewers_proposal_is_open(people):
    a, _ = people["a"]
    company_id = await ready()
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).claim_review(company_id, actor_id=a, actor_role=C)
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).release_review(company_id, note="out today", actor_id=a, actor_role=C)
    assert (await reviewer_of(company_id))[0] is None
    await propose(company_id, a)  # auto-claims
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(BackgroundCheckProposalOpenError):
            await svc(db).release_review(company_id, note=None, actor_id=a, actor_role=C)
    rows = await assignment_rows(company_id)
    assert [r.event_type for r in rows] == ["review_claimed", "review_released", "review_claimed"]
    assert rows[1].reason == "out today"


async def test_only_the_reviewer_or_a_lead_releases(people):
    a, _ = people["a"]
    b, _ = people["b"]
    lead, _ = people["lead"]
    company_id = await ready()
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).claim_review(company_id, actor_id=a, actor_role=C)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewAssignNotAllowedError):
            await svc(db).release_review(company_id, note=None, actor_id=b, actor_role=C)
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).release_review(
            company_id, note=None, actor_id=lead, actor_role=C, actor_permissions=LEAD
        )


# ── The reviewer's moves ────────────────────────────────────────────────────


async def test_proposing_auto_claims_and_a_non_reviewer_is_refused(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    proposal = await propose(company_id, a)
    assert (await reviewer_of(company_id))[0] == a
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).withdraw(company_id, proposal.id, reason=None, actor_id=a, actor_role=C)
    with pytest.raises(ReviewAssignedToOtherError):
        await propose(company_id, b)


async def test_requesting_information_is_the_reviewers_and_the_rm_answers(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).request_more_info(company_id, note="need the MoA", actor_id=a, actor_role=C)
    assert (await reviewer_of(company_id))[0] == a  # auto-claimed, kept in MORE_INFO
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).record_more_info(
            company_id, note="MoA uploaded", actor_id="ops", actor_role=UserRole.OPERATIONS
        )
    assert await gauge(company_id) is State.IN_REVIEW
    assert (await reviewer_of(company_id))[0] == a
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ReviewAssignedToOtherError):
            await svc(db).request_more_info(company_id, note="more", actor_id=b, actor_role=C)


async def test_on_hold_is_not_a_review_outcome(people):
    a, _ = people["a"]
    company_id = await ready()
    with pytest.raises(BackgroundCheckMoveNotAllowedError):
        await propose(company_id, a, to=State.ON_HOLD)


async def test_a_proposal_names_no_checker(client, people):
    _, a_token = people["a"]
    company_id = await ready()
    response = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "CLEAR", "risk_rating": "LOW", "reason": "ok", "checker_id": "x"},
        headers=auth_header(a_token),
    )
    assert response.status_code == 422


# ── Independence and the senior checker ─────────────────────────────────────


async def test_the_reviewer_and_the_rm_cannot_approve(people):
    a, _ = people["a"]
    b, _ = people["b"]
    c, _ = people["c"]
    lead, _ = people["lead"]
    company_id = await ready()
    proposal = await propose(company_id, a)
    # The review moves to B; A's proposal survives. B now holds the review.
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).assign_review(
            company_id, user_id=b, reason="handover", actor_id=lead, actor_role=C,
            actor_permissions=LEAD,
        )
    with pytest.raises(BackgroundCheckConflictOfInterestError):
        await approve(company_id, proposal.id, b)
    await set_rm(company_id, c)
    with pytest.raises(BackgroundCheckConflictOfInterestError):
        await approve(company_id, proposal.id, c)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(BackgroundCheckConflictOfInterestError):
            await svc(db).reject(company_id, proposal.id, reason="no", actor_id=c, actor_role=C)


@pytest.mark.parametrize("risk", [BackgroundCheckRisk.HIGH, BackgroundCheckRisk.CRITICAL])
async def test_a_high_risk_clear_needs_a_senior_checker_in_one_step(people, risk):
    a, _ = people["a"]
    b, _ = people["b"]
    senior, _ = people["senior"]
    company_id = await ready()
    proposal = await propose(company_id, a, risk=risk)
    with pytest.raises(HighRiskApprovalRequiredError):
        await approve(company_id, proposal.id, b)
    approved = await approve(company_id, proposal.id, senior, perms=SENIOR)
    assert approved.decision.to_value is State.CLEAR
    assert approved.proposal.status == "APPROVED"
    assert await gauge(company_id) is State.CLEAR


async def test_admin_approves_a_high_risk_clear_and_low_needs_no_senior(people):
    a, _ = people["a"]
    b, _ = people["b"]
    admin, _ = people["admin"]
    high = await ready()
    proposal = await propose(high, a, risk=BackgroundCheckRisk.HIGH)
    await approve(high, proposal.id, admin, role=A)
    assert await gauge(high) is State.CLEAR
    medium = await ready()
    proposal = await propose(medium, a, risk=BackgroundCheckRisk.MEDIUM)
    await approve(medium, proposal.id, b)
    assert await gauge(medium) is State.CLEAR


async def test_flagging_needs_no_senior(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    proposal = await propose(company_id, a, to=State.FLAGGED)
    await approve(company_id, proposal.id, b)
    assert await gauge(company_id) is State.FLAGGED


# ── After a decision ────────────────────────────────────────────────────────


async def test_a_decision_ends_the_review(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    proposal = await propose(company_id, a)
    await approve(company_id, proposal.id, b)
    assert await reviewer_of(company_id) == (None, None)
    rows = await assignment_rows(company_id)
    assert rows[-1].event_type == "review_ended"
    assert rows[-1].event_metadata["from_user_id"] == a


async def test_the_database_refuses_a_reviewer_on_a_decided_company(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    proposal = await propose(company_id, a)
    await approve(company_id, proposal.id, b)
    with pg() as cur, pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            "UPDATE onboarding.exporter_profile SET background_check_reviewer_id = %s, "
            "background_check_reviewer_assigned_at = now() WHERE customer_id = %s",
            (a, str(company_id)),
        )
    with pg() as cur, pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            "UPDATE onboarding.exporter_profile SET background_check_reviewer_assigned_at = now() "
            "WHERE customer_id = %s",
            (str(company_id),),
        )


async def test_a_rejection_keeps_the_reviewer_and_two_need_attention(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    for _ in range(2):
        proposal = await propose(company_id, a)
        async with db_services.AsyncSessionLocal() as db:
            await svc(db).reject(company_id, proposal.id, reason="not yet", actor_id=b, actor_role=C)
        assert (await reviewer_of(company_id))[0] == a
    async with db_services.AsyncSessionLocal() as db:
        items = await ComplianceWorklists(db).items()
    item = next(i for i in items if i.company_id == company_id)
    assert item.rejection_count == 2
    assert item.needs_attention


async def test_a_lead_withdraws_an_absent_proposers_proposal(client, people):
    lead, _ = people["lead"]
    b, _ = people["b"]
    leaver, _ = await user_with_role(client, C, email_prefix="rv-leaver")
    company_id = await ready()
    proposal = await propose(company_id, leaver)
    # While the proposer is still here, a lead rejects; it does not withdraw for them.
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(BackgroundCheckProposalNotYoursError, match="Reject it instead"):
            await svc(db).withdraw(
                company_id, proposal.id, reason=None, actor_id=lead, actor_role=C,
                actor_permissions=LEAD,
            )
    deactivate(leaver)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(BackgroundCheckProposalNotYoursError):
            await svc(db).withdraw(company_id, proposal.id, reason=None, actor_id=b, actor_role=C)
    async with db_services.AsyncSessionLocal() as db:
        view = await svc(db).withdraw(
            company_id, proposal.id, reason="proposer left", actor_id=lead, actor_role=C,
            actor_permissions=LEAD,
        )
    assert view.status == "WITHDRAWN" and view.resolved_by == lead
    async with db_services.AsyncSessionLocal() as db:
        items = await ComplianceWorklists(db).items()
    item = next(i for i in items if i.company_id == company_id)
    assert item.reviewer_inactive and item.needs_attention


async def test_a_reassessment_hands_the_review_to_whoever_makes_it(people):
    a, _ = people["a"]
    b, _ = people["b"]
    c, _ = people["c"]
    company_id = await ready()
    proposal = await propose(company_id, a, to=State.FLAGGED)
    await approve(company_id, proposal.id, b)
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).reassess(company_id, reason="new facts", actor_id=c, actor_role=C)
    assert (await reviewer_of(company_id))[0] == c


async def test_a_re_kyc_on_a_clear_company_makes_its_starter_the_reviewer(people):
    a, _ = people["a"]
    b, _ = people["b"]
    c, _ = people["c"]
    company_id = await ready()
    proposal = await propose(company_id, a)
    await approve(company_id, proposal.id, b)
    assert await reviewer_of(company_id) == (None, None)
    async with db_services.AsyncSessionLocal() as db:
        started = await svc(db).start_cycle(
            company_id, kind=CheckCycleKind.RE_KYC, reason="Annual review", actor_id=c,
            actor_role=C,
        )
    assert started.reopen is not None
    assert await gauge(company_id) is State.IN_REVIEW
    reviewer, assigned_at = await reviewer_of(company_id)
    assert reviewer == c and assigned_at is not None
    rows = await assignment_rows(company_id)
    assert rows[-1].event_metadata["to_user_id"] == c


async def test_flagged_to_on_hold_stays_maker_checker(people):
    a, _ = people["a"]
    b, _ = people["b"]
    company_id = await ready()
    flagged = await propose(company_id, a, to=State.FLAGGED)
    await approve(company_id, flagged.id, b)
    hold = await propose(company_id, a, to=State.ON_HOLD)
    assert await gauge(company_id) is State.FLAGGED
    await approve(company_id, hold.id, b)
    assert await gauge(company_id) is State.ON_HOLD


async def test_a_claim_racing_an_assignment_leaves_one_holder(people):
    a, _ = people["a"]
    b, _ = people["b"]
    lead, _ = people["lead"]
    company_id = await ready()

    async def claim():
        async with db_services.AsyncSessionLocal() as db:
            await svc(db).claim_review(company_id, actor_id=a, actor_role=C)

    async def assign():
        async with db_services.AsyncSessionLocal() as db:
            await svc(db).assign_review(
                company_id, user_id=b, reason="lead's call", actor_id=lead, actor_role=C,
                actor_permissions=LEAD,
            )

    results = await asyncio.gather(claim(), assign(), return_exceptions=True)
    reviewer = (await reviewer_of(company_id))[0]
    assert reviewer in (a, b)
    rows = await assignment_rows(company_id)
    # Every change is on the record, and the last row names the holder.
    assert rows[-1].event_metadata["to_user_id"] == reviewer
    assert all(r is None or isinstance(r, ReviewAlreadyAssignedError) for r in results)


# ── Worklists, the queue and the API ────────────────────────────────────────


async def test_awaiting_review_and_my_reviews(client, people):
    a, a_token = people["a"]
    company_id = await ready()
    awaiting = (
        await client.get(f"{BASE}/background-check/reviews?view=awaiting", headers=auth_header(a_token))
    ).json()
    assert str(company_id) in {i["company_id"] for i in awaiting["items"]}
    row = next(i for i in awaiting["items"] if i["company_id"] == str(company_id))
    assert row["stage"] == "review" and row["due_at"] is None and row["reviewer_id"] is None

    standing = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/reviewer/claim", headers=auth_header(a_token)
    )
    assert standing.status_code == 200, standing.text
    body = standing.json()
    assert body["reviewer_id"] == a and body["reviewer_name"]
    assert "RELEASE" in body["review_actions"] and "CLAIM" not in body["review_actions"]

    mine = (
        await client.get(f"{BASE}/background-check/reviews?view=mine", headers=auth_header(a_token))
    ).json()
    row = next(i for i in mine["items"] if i["company_id"] == str(company_id))
    assert row["due_at"] is not None
    assert row["is_overdue"] is False
    for item in mine["items"]:
        assert set(item) >= {"company_name", "waiting_since", "due_at", "is_overdue", "stage"}
        assert "pan" not in item and "gstins" not in item


async def test_the_lead_views_need_compliance_assign(client, people):
    _, a_token = people["a"]
    _, lead_token = people["lead"]
    _, admin_token = people["admin"]
    _, rm_token = people["rm"]
    for view in ("in_review", "overdue", "needs_attention"):
        url = f"{BASE}/background-check/reviews?view={view}"
        assert (await client.get(url, headers=auth_header(a_token))).status_code == 403
        assert (await client.get(url, headers=auth_header(lead_token))).status_code == 200
        assert (await client.get(url, headers=auth_header(admin_token))).status_code == 200
    rm_view = await client.get(f"{BASE}/background-check/reviews?view=awaiting", headers=auth_header(rm_token))
    assert rm_view.status_code == 403


async def test_the_standing_offers_reviewer_moves_only_to_the_reviewer(client, people):
    a, a_token = people["a"]
    _, b_token = people["b"]
    _, lead_token = people["lead"]
    company_id = await ready()
    await client.post(
        f"{BASE}/exporters/{company_id}/background-check/reviewer/claim", headers=auth_header(a_token)
    )
    a_view = (
        await client.get(f"{BASE}/exporters/{company_id}/background-check", headers=auth_header(a_token))
    ).json()
    b_view = (
        await client.get(f"{BASE}/exporters/{company_id}/background-check", headers=auth_header(b_token))
    ).json()
    lead_view = (
        await client.get(f"{BASE}/exporters/{company_id}/background-check", headers=auth_header(lead_token))
    ).json()
    assert {"CLEAR", "MORE_INFO", "FLAGGED"} <= {m["to_value"] for m in a_view["allowed_moves"]}
    assert not {"CLEAR", "MORE_INFO", "FLAGGED"} & {m["to_value"] for m in b_view["allowed_moves"]}
    assert b_view["review_actions"] == []
    assert set(lead_view["review_actions"]) == {"RELEASE", "ASSIGN"}

    reassigned = await client.put(
        f"{BASE}/exporters/{company_id}/background-check/reviewer",
        json={"user_id": people["b"][0], "reason": "balance"},
        headers=auth_header(lead_token),
    )
    assert reassigned.status_code == 200, reassigned.text
    plain = await client.put(
        f"{BASE}/exporters/{company_id}/background-check/reviewer",
        json={"user_id": a, "reason": "back"},
        headers=auth_header(b_token),
    )
    assert plain.status_code == 403


async def test_the_queue_serves_only_what_the_caller_may_approve(client, people):
    a, _ = people["a"]
    b, b_token = people["b"]
    _, senior_token = people["senior"]
    low = await ready()
    high = await ready()
    await propose(low, a)
    await propose(high, a, risk=BackgroundCheckRisk.HIGH)

    async def queue(token):
        response = await client.get(
            f"{BASE}/background-check/proposals?status=open&awaiting=me&limit=100",
            headers=auth_header(token),
        )
        assert response.status_code == 200, response.text
        return {p["company_id"]: p for p in response.json()["proposals"]}

    for_b = await queue(b_token)
    assert str(low) in for_b and str(high) not in for_b
    item = for_b[str(low)]
    assert item["due_at"] is not None and item["eligible_checker_count"] >= 1
    assert "APPROVE" in item["allowed_actions"]
    for_senior = await queue(senior_token)
    assert str(high) in for_senior
    assert for_senior[str(high)]["needs_senior_approval"] is True

    # B sees the high-risk one on the company page, with Approve withheld and why.
    standing = (
        await client.get(f"{BASE}/exporters/{high}/background-check", headers=auth_header(b_token))
    ).json()
    assert "APPROVE" not in standing["open_proposal"]["allowed_actions"]
    assert "REJECT" in standing["open_proposal"]["allowed_actions"]
    assert standing["open_proposal"]["approval_blocked_reason"]


async def test_no_eligible_checker_needs_attention(people, monkeypatch):
    a, _ = people["a"]
    company_id = await ready()
    await propose(company_id, a, risk=BackgroundCheckRisk.HIGH)

    async def pools(self):
        # The only senior approver is the reviewer herself.
        return frozenset({a, people["b"][0]}), frozenset({a})

    monkeypatch.setattr(ComplianceWorklists, "_checker_pools", pools)
    async with db_services.AsyncSessionLocal() as db:
        items = await ComplianceWorklists(db).items()
    item = next(i for i in items if i.company_id == company_id)
    assert item.stage == "approval"
    assert item.eligible_checker_count == 0
    assert item.needs_attention


async def test_info_requests_counts_and_recent_decisions(client, people):
    a, a_token = people["a"]
    b, _ = people["b"]
    rm, rm_token = people["rm"]
    _, developer = people["developer"]
    asked = await ready()
    await set_rm(asked, rm)
    async with db_services.AsyncSessionLocal() as db:
        await svc(db).request_more_info(asked, note="Board resolution please", actor_id=a, actor_role=C)

    mine = (
        await client.get(
            f"{BASE}/background-check/info-requests?relationship_manager=me", headers=auth_header(rm_token)
        )
    ).json()
    row = next(i for i in mine["items"] if i["company_id"] == str(asked))
    assert row["info_note"] == "Board resolution please"
    assert row["stage"] == "info" and row["due_at"] is not None

    counts = (await client.get(f"{BASE}/worklist/counts", headers=auth_header(rm_token))).json()
    assert counts["info_requested"] >= 1
    assert counts["awaiting_review"] is None and counts["overdue"] is None
    a_counts = (await client.get(f"{BASE}/worklist/counts", headers=auth_header(a_token))).json()
    assert a_counts["my_reviews"] >= 1 and a_counts["needs_attention"] is None
    assert set(counts) == {
        "awaiting_review", "my_reviews", "awaiting_approval", "info_requested", "overdue",
        "needs_attention",
    }

    cleared = await ready()
    await set_rm(cleared, rm)
    proposal = await propose(cleared, a)
    await approve(cleared, proposal.id, b)
    recent = (
        await client.get(f"{BASE}/background-check/recent-decisions", headers=auth_header(rm_token))
    ).json()
    decision = next(d for d in recent["decisions"] if d["company_id"] == str(cleared))
    assert decision["to_value"] == "CLEAR"
    assert "reason" not in decision

    for url in (
        "/background-check/info-requests",
        "/worklist/counts",
        "/background-check/recent-decisions",
        "/background-check/reviews",
    ):
        assert (await client.get(f"{BASE}{url}", headers=auth_header(developer))).status_code == 403


async def test_developer_does_not_receive_assignment_history(client, people):
    a, a_token = people["a"]
    _, developer = people["developer"]
    company_id = await ready()
    await client.post(
        f"{BASE}/exporters/{company_id}/background-check/reviewer/claim", headers=auth_header(a_token)
    )
    rows = (
        await client.get(f"{BASE}/exporters/{company_id}/history?limit=100", headers=auth_header(developer))
    ).json()
    dimensions = {r["dimension"] for r in rows["entries"]}
    assert "background_check_assignment" not in dimensions
    own = (
        await client.get(f"{BASE}/exporters/{company_id}/history?limit=100", headers=auth_header(a_token))
    ).json()
    assert "background_check_assignment" in {
        r["dimension"] for r in own["entries"]
    }
