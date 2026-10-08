"""Background-check routes.

Contract: ``docs/contracts/background-check.md`` §3, §13. Three routes: read the
standing, record a move, list the decisions.

**The server decides what may happen next.** The read returns ``allowed_moves`` for
*this* caller, in the shape ``ConversationService.allowed_moves`` and
``DealService.allowed_stage_moves`` already use, so the screen offers what it is told
and keeps no move table and no role list of its own (§7.5). A rule change here cannot
leave a stale button behind.

**Roles are checked twice, on purpose.** ``require_role`` keeps the wrong kind of
caller off the route; ``BackgroundCheckService`` then enforces the *per-move* roles,
because one route serves nine moves and OPERATIONS may make only two of them. The
route-level check alone would let an operations user flag a company.

**DEVELOPER is not admitted.** Unlike the deal and document reads, these routes admit
only OPERATIONS, COMPLIANCE and ADMIN: the rule settled 28 September 2026 refuses
DEVELOPER the gauge, the decision reasons and the evidence ids, reads included. A
decision's reason is free text a compliance officer typed about a real company.

**Compliance facts and cycles (1 October 2026).** The standing also serves the
company's compliance facts, its current check cycle and the cycles this caller may
start. Three routes were added, under the same DEVELOPER rule: one decision's
evidence resolved into readable items, the company's cycles, and starting a
Re-KYC / Re-KYB (COMPLIANCE and ADMIN only).

**Maker-checker, required checks and expiry.** Maker-checker: with it on, a
``POST …/decisions`` to ``CLEAR``, ``FLAGGED`` or ``ON_HOLD`` records a **proposal**
(202) instead of moving the check, and a different COMPLIANCE or ADMIN user approves or
rejects it (``…/proposals/{id}/approve`` / ``reject``); the proposer may withdraw it.
The standing serves the open proposal and what *this user* may do with it, the
verification types ``CLEAR`` requires and their state, and whether the Clear
is due for Re-KYC. Two cross-company reads feed the Home cards:
``GET /background-check/proposals?status=open`` (COMPLIANCE, ADMIN) and
``GET /background-check/due?before=…`` (staff). DEVELOPER is refused on all.

**Who is working on it.** The standing names the review's reviewer and what this
caller may do with it (claim, release, assign); three routes do those. The worklists
(``GET /background-check/reviews?view=…``, ``…/info-requests``,
``…/recent-decisions`` and ``GET /worklist/counts``) are computed on read from the
gauge, the reviewer and the proposals, with business-time deadlines — the v1
notifications are these lists and their counts. ``in_review``, ``overdue`` and
``needs_attention`` are for ADMIN and holders of ``compliance:assign``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.background_check import (
    ApproveBackgroundCheckProposalResponse,
    AssignReviewerRequest,
    BackgroundCheckCycleActionResponse,
    BackgroundCheckDecisionListResponse,
    BackgroundCheckDecisionResponse,
    BackgroundCheckMoveResponse,
    BackgroundCheckProposalListResponse,
    BackgroundCheckProposalResponse,
    BackgroundCheckResponse,
    CheckCycleListResponse,
    CheckCycleResponse,
    CompanyComplianceFactsResponse,
    ComplianceWorkItemResponse,
    ComplianceWorklistResponse,
    DecisionEvidenceDocument,
    DecisionEvidenceItemResponse,
    DecisionEvidencePinnedReview,
    DecisionEvidenceResponse,
    DecisionEvidenceScreeningItem,
    DecisionEvidenceVerification,
    EvidenceItemResponse,
    RecentDecisionListResponse,
    RecentDecisionResponse,
    RecordBackgroundCheckDecisionRequest,
    RejectBackgroundCheckProposalRequest,
    ReKycDueCompanyResponse,
    ReKycDueListResponse,
    ReleaseReviewRequest,
    RequiredCheckResponse,
    StartCheckCycleRequest,
    StartCheckCycleResponse,
    WithdrawBackgroundCheckProposalRequest,
    WorklistCountsResponse,
)
from app.modules.onboarding.api.schemas.verification import VerificationEvidenceRefOut
from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.background_check_service import (
    BackgroundCheckService,
    proposal_view,
)
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.application.compliance_settings import rekyc_due_window
from app.modules.onboarding.application.compliance_worklists import (
    LEAD_VIEWS,
    ComplianceWorklists,
    WorkItem,
)
from app.modules.onboarding.application.decision_evidence import (
    DecisionEvidenceReader,
    DecisionEvidenceView,
)
from app.modules.onboarding.application.rekyc_due import rekyc_due
from app.modules.onboarding.domain.assignment import (
    APPROVE_HIGH_RISK,
    ASSIGN_REVIEWS,
    Permission,
    checker_conflict,
    holds,
    needs_senior_checker,
)
from app.modules.onboarding.domain.background_check_views import (
    PROPOSAL_APPROVE,
    PROPOSAL_REJECT,
    PROPOSAL_WITHDRAW,
    BackgroundCheckDecisionView,
    BackgroundCheckProposalView,
    EvidenceItemView,
    proposal_actions,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckEvidenceKind,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle, CheckCycleKind
from app.modules.onboarding.domain.entities.exporter_enums import CompanyPipelineStatus
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.infrastructure.repositories.background_check_proposal_repository import (  # noqa: E501
    BackgroundCheckProposalRepository,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
    resolved_cycle_id,
)
from app.platform.authentication import staff_member
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import get_current_permissions, require_role
from app.platform.database.services import get_db
from app.shared import clock
from app.shared.exceptions import AnerBaseException, ValidationError

router = APIRouter(tags=["Exporter CRM"])

#: Compliance work by internal staff (architecture §3.7). DEVELOPER is absent.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
#: Who may start a check cycle and who proposes, approves or rejects a
#: background-check decision (never the RM). The service enforces the same
#: rule.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)
_RESOLVER_ROLES = frozenset({UserRole.COMPLIANCE, UserRole.ADMIN})
#: The signed-in user's permissions, for the "ADMIN or permission" rules.
_PERMISSIONS = Annotated[frozenset[Permission], Depends(get_current_permissions)]
#: The reviewer's moves: offered only to the reviewer, or to anyone who could claim.
_REVIEWER_DESTINATIONS = frozenset(
    {BackgroundCheckState.MORE_INFO, BackgroundCheckState.CLEAR, BackgroundCheckState.FLAGGED}
)


def _approval_eligibility(
    view: BackgroundCheckProposalView,
    *,
    viewer: User,
    permissions: frozenset[Permission],
    reviewer_id: str | None,
    relationship_manager_id: str | None,
) -> tuple[str | None, bool]:
    """Why this viewer may not approve ``view`` (``None`` if they may), and whether the
    reason also bars a rejection (the reviewer and the RM are not independent; a
    missing senior permission bars only the approval)."""
    viewer_id = str(viewer.id)
    if viewer_id == view.proposed_by:
        return None, False
    why = checker_conflict(
        checker_id=viewer_id,
        reviewer_id=reviewer_id,
        relationship_manager_id=relationship_manager_id,
    )
    if why is not None:
        return f"You cannot approve this: {why}.", True
    if needs_senior_checker(view.to_value, view.risk_rating) and not holds(
        viewer.role, permissions, APPROVE_HIGH_RISK
    ):
        return "A senior approver must approve a high-risk Clear.", False
    return None, False


def _proposal_response(
    view: BackgroundCheckProposalView,
    *,
    names: dict[str, str],
    cycle_number: int | None = None,
    company_name: str | None = None,
    stale_reason: str | None = None,
    viewer: User | None = None,
    permissions: frozenset[Permission] = frozenset(),
    reviewer_id: str | None = None,
    relationship_manager_id: str | None = None,
    facts: WorkItem | None = None,
) -> BackgroundCheckProposalResponse:
    actions: tuple[str, ...] = ()
    blocked: str | None = None
    if viewer is not None:
        actions = proposal_actions(
            view,
            viewer_id=str(viewer.id),
            viewer_may_resolve=viewer.role in _RESOLVER_ROLES,
            is_stale=stale_reason is not None,
        )
        if view.is_open:
            blocked, bars_reject = _approval_eligibility(
                view,
                viewer=viewer,
                permissions=permissions,
                reviewer_id=reviewer_id,
                relationship_manager_id=relationship_manager_id,
            )
            barred = {PROPOSAL_APPROVE, PROPOSAL_REJECT} if bars_reject else {PROPOSAL_APPROVE}
            if blocked is not None:
                actions = tuple(a for a in actions if a not in barred)
            if (
                str(viewer.id) != view.proposed_by
                and viewer.role in _RESOLVER_ROLES
                and holds(viewer.role, permissions, ASSIGN_REVIEWS)
            ):
                actions = (*actions, PROPOSAL_WITHDRAW)
    return BackgroundCheckProposalResponse(
        id=view.id,
        company_id=view.company_id,
        company_name=company_name,
        based_on_decision_id=view.based_on_decision_id,
        from_value=view.from_value,
        to_value=view.to_value,
        risk_rating=view.risk_rating,
        reason=view.reason,
        proposed_by=view.proposed_by,
        proposed_by_name=names.get(view.proposed_by),
        proposed_at=view.proposed_at,
        cycle_id=view.cycle_id,
        cycle_number=cycle_number,
        rules_version=view.rules_version,
        evidence_count=view.evidence_count,
        status=view.status,  # type: ignore[arg-type]
        resolved_by=view.resolved_by,
        resolved_by_name=names.get(view.resolved_by or ""),
        resolved_at=view.resolved_at,
        resolution_reason=view.resolution_reason,
        decision_id=view.decision_id,
        stale_reason=stale_reason if view.is_open else None,
        allowed_actions=list(actions),  # type: ignore[arg-type]
        approval_blocked_reason=blocked,
        needs_senior_approval=needs_senior_checker(view.to_value, view.risk_rating),
        due_at=facts.due_at if facts is not None and view.is_open else None,
        is_due_soon=bool(facts is not None and view.is_open and facts.is_due_soon),
        is_overdue=bool(facts is not None and view.is_open and facts.is_overdue),
        eligible_checker_count=(
            facts.eligible_checker_count if facts is not None and view.is_open else None
        ),
    )


async def _profile(db: AsyncSession, company_id: uuid.UUID) -> ExporterProfile:
    profile = await db.scalar(
        select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
    )
    if profile is None:
        raise ExporterProfileNotFoundError(company_id)
    return profile


def _rm_id(profile: ExporterProfile) -> str | None:
    return (
        str(profile.relationship_manager_user_id)
        if profile.relationship_manager_user_id is not None
        else None
    )


async def _decision_response(
    db: AsyncSession, user: User, view: BackgroundCheckDecisionView
) -> BackgroundCheckDecisionResponse:
    names = await actor_names(db, user, [view.decided_by, view.approved_by])
    cycles = await CheckCycleRepository(db).by_ids([view.cycle_id] if view.cycle_id else [])
    cycle = cycles.get(view.cycle_id) if view.cycle_id else None
    return BackgroundCheckDecisionResponse.from_view(
        view,
        decided_by_name=names.get(view.decided_by or ""),
        approved_by_name=names.get(view.approved_by or ""),
        cycle_number=cycle.number if cycle is not None else None,
    )


def _cycle_response(
    cycle: CheckCycle, *, current_id: uuid.UUID | None, names: dict[str, str]
) -> CheckCycleResponse:
    return CheckCycleResponse(
        id=cycle.id,
        company_id=cycle.company_id,
        number=cycle.number,
        kind=cycle.kind,
        reason=cycle.reason,
        started_at=cycle.started_at,
        started_by=cycle.created_by,
        started_by_name=names.get(cycle.created_by),
        source=cycle.source,
        rules_version=cycle.rules_version,
        is_current=cycle.id == current_id,
    )


@router.get(
    "/exporters/{company_id}/background-check",
    response_model=BackgroundCheckResponse,
    summary="Read a company's background check",
    description=(
        "The current value, the risk of the latest decision that set one, the "
        "latest decision, and the moves **this caller** may make next.\n\n"
        "`allowed_moves` is the rule table as data: offer exactly these and no "
        "others. Where `CLEAR` is offered but its prerequisites are unmet, "
        "`clear_blocked_reasons` names each one, so the screen can say what is "
        "outstanding rather than showing a 409 after the fact."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
    },
)
async def get_background_check(
    company_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
) -> BackgroundCheckResponse:
    standing = await BackgroundCheckReader(db).standing(company_id)
    profile = await _profile(db, company_id)
    reviewer_id = profile.background_check_reviewer_id
    current = BackgroundCheckState(standing.value)
    service = BackgroundCheckService(db)

    blocked: list[str] = []
    if current is BackgroundCheckState.IN_REVIEW:
        # Advisory: `clear` evaluates the same rule again under the row lock, which
        # is what actually decides. This is here so the screen can explain first.
        blocked = list(await service.clear_prerequisites(company_id))

    now = clock.now()
    facts = await ComplianceFactsService(db).for_company(company_id, now)
    current_cycle = await CheckCycleRepository(db).current_for_company(company_id)
    awaiting = await service.open_proposal(company_id)
    names = await actor_names(
        db,
        user,
        [
            current_cycle.created_by if current_cycle is not None else None,
            awaiting[0].proposed_by if awaiting is not None else None,
            reviewer_id,
        ],
    )
    open_proposal = None
    if awaiting is not None:
        proposal, stale_reason = awaiting
        cycle_numbers = await CheckCycleRepository(db).by_ids([proposal.cycle_id])
        open_proposal = _proposal_response(
            proposal,
            names=dict(names),
            cycle_number=(
                cycle_numbers[proposal.cycle_id].number
                if proposal.cycle_id in cycle_numbers
                else None
            ),
            stale_reason=stale_reason,
            viewer=user,
            permissions=permissions,
            reviewer_id=reviewer_id,
            relationship_manager_id=_rm_id(profile),
        )

    # A reviewer's move is offered to the reviewer, or to someone who could claim
    # the review by making it — never to the company's RM.
    viewer_id = str(user.id)
    may_make_reviewer_moves = (
        reviewer_id == viewer_id
        if reviewer_id is not None
        else _rm_id(profile) != viewer_id
    )
    moves = [
        move
        for move in service.allowed_moves(current, user.role)
        if may_make_reviewer_moves
        or current is not BackgroundCheckState.IN_REVIEW
        or move.to not in _REVIEWER_DESTINATIONS
    ]
    reviewer = await staff_member(db, reviewer_id) if reviewer_id is not None else None

    return BackgroundCheckResponse(
        company_id=standing.company_id,
        value=current,
        risk_rating=standing.risk_rating,
        latest_decision_id=standing.latest_decision_id,
        clearing_decision_id=standing.clearing_decision_id,
        decided_at=standing.decided_at,
        # While a proposal awaits approval nothing else moves the check.
        allowed_moves=(
            [] if awaiting is not None else [BackgroundCheckMoveResponse.from_view(m) for m in moves]
        ),
        clear_blocked_reasons=blocked,
        compliance=CompanyComplianceFactsResponse(
            is_clear=facts.is_clear,
            clear_expires_at=facts.clear_expires_at,
            is_clear_current=facts.is_clear_current,
            sanctions=facts.sanctions,
            aml=facts.aml,
        ),
        current_cycle=(
            _cycle_response(current_cycle, current_id=current_cycle.id, names=names)
            if current_cycle is not None
            else None
        ),
        allowed_cycle_actions=[
            BackgroundCheckCycleActionResponse.from_view(action)
            for action in await service.cycle_actions(company_id, current, user.role)
        ],
        awaiting_approval=awaiting is not None,
        open_proposal=open_proposal,
        required_checks=[
            RequiredCheckResponse(verification_type=check.verification_type, state=check.state)
            for check in await service.required_checks(company_id)
        ],
        rekyc_due=(
            facts.is_clear
            and facts.clear_expires_at is not None
            and facts.clear_expires_at <= now + rekyc_due_window()
        ),
        reviewer_id=reviewer_id,
        reviewer_name=names.get(reviewer_id or ""),
        reviewer_assigned_at=profile.background_check_reviewer_assigned_at,
        reviewer_inactive=reviewer_id is not None and (reviewer is None or not reviewer.is_active),
        review_actions=service.review_actions(  # type: ignore[arg-type]
            profile,
            viewer_id=viewer_id,
            viewer_role=user.role,
            viewer_permissions=permissions,
            open_proposal=awaiting[0] if awaiting is not None else None,
        ),
        relationship_manager_required=(
            current is BackgroundCheckState.NOT_STARTED
            and profile.pipeline_status is CompanyPipelineStatus.IN_PIPELINE
            and profile.relationship_manager_user_id is None
        ),
    )


@router.post(
    "/exporters/{company_id}/background-check/decisions",
    response_model=BackgroundCheckDecisionResponse,
    status_code=201,
    summary="Record a background-check decision (or propose one for approval)",
    description=(
        "Moves the gauge and records why, as one locked decision with the evidence "
        "it rested on, in one transaction.\n\n"
        "The request names **where the check is going** and nothing about who is "
        "deciding: the actor comes from the login session, the source and "
        "decided-by kind are the server's, and the evidence snapshot is assembled "
        "by the server. A request carrying any of them is refused (422).\n\n"
        "Send `from_value` (the value the screen showed) so that a request made from "
        "a stale screen is refused (409) rather than becoming a different act.\n\n"
        "Roles are enforced per move, not merely per route: OPERATIONS may start a "
        "check and record what arrived, and nothing else.\n\n"
        "**Maker-checker.** A move to CLEAR, FLAGGED or ON_HOLD is not recorded here: "
        "it becomes a **proposal** (202, the proposal in the body) — its rules and, for "
        "CLEAR, its prerequisites checked now — and the check does not move until a "
        "different COMPLIANCE or ADMIN user approves it. While a proposal is open no "
        "other move is accepted (409 `BACKGROUND_CHECK_PROPOSAL_OPEN`)."
    ),
    responses={
        202: {
            "model": BackgroundCheckProposalResponse,
            "description": "CLEAR, FLAGGED or ON_HOLD: proposed, awaiting a second approver",
        },
        401: {"description": "Unauthorized"},
        403: {
            "description": (
                "OPERATIONS, COMPLIANCE or ADMIN role required for the route; "
                "`BACKGROUND_CHECK_ROLE_NOT_ALLOWED` when the role may not make "
                "this particular move"
            )
        },
        404: {"description": "Company not found"},
        409: {
            "description": (
                "`BACKGROUND_CHECK_MOVE_NOT_ALLOWED` — not a legal move from the "
                "current value; `BACKGROUND_CHECK_STATE_CHANGED` — the check is no "
                "longer at `from_value`; `BACKGROUND_CHECK_PREREQUISITES_UNMET` — "
                "CLEAR with prerequisites outstanding, naming each; or "
                "`BACKGROUND_CHECK_PROPOSAL_OPEN` — a proposal awaits approval; "
                "`RELATIONSHIP_MANAGER_REQUIRED` — a start on an in-pipeline company with "
                "no RM and none given; `REVIEW_ASSIGNED_TO_OTHER` — someone else holds "
                "the review; `REVIEWER_IS_RM`"
            )
        },
        422: {
            "description": (
                "`BACKGROUND_CHECK_REASON_REQUIRED`, "
                "`BACKGROUND_CHECK_RISK_REQUIRED`, "
                "`BACKGROUND_CHECK_RISK_NOT_ALLOWED`, or an unknown field in the body"
            )
        },
    },
)
async def record_background_check_decision(
    company_id: uuid.UUID,
    payload: RecordBackgroundCheckDecisionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
) -> BackgroundCheckDecisionResponse | JSONResponse:
    service = BackgroundCheckService(db)
    if service.needs_approval(payload.to_value):
        proposal = await service.propose(
            company_id,
            to_value=payload.to_value,
            reason=payload.reason,
            risk=payload.risk_rating,
            seen_value=payload.from_value,
            actor_id=str(user.id),
            actor_role=user.role,
        )
        names = await actor_names(db, user, [proposal.proposed_by])
        cycles = await CheckCycleRepository(db).by_ids([proposal.cycle_id])
        body = _proposal_response(
            proposal,
            names=dict(names),
            cycle_number=cycles[proposal.cycle_id].number if proposal.cycle_id in cycles else None,
            viewer=user,
            permissions=permissions,
        )
        return JSONResponse(status_code=202, content=body.model_dump(mode="json"))

    view = await service.record_decision(
        company_id,
        to_value=payload.to_value,
        reason=payload.reason,
        risk=payload.risk_rating,
        seen_value=payload.from_value,
        # From the session, never the body (contract §5.1).
        actor_id=str(user.id),
        actor_role=user.role,
        actor_permissions=permissions,
        relationship_manager_user_id=payload.relationship_manager_user_id,
    )
    return await _decision_response(db, user, view)


@router.get(
    "/exporters/{company_id}/background-check/decisions",
    response_model=BackgroundCheckDecisionListResponse,
    summary="List a company's background-check decisions",
    description=(
        "Every decision on this company, newest first, each with the evidence "
        "snapshot it was recorded against.\n\n"
        "Decisions are append-only: a reopen or reassessment is a new decision that "
        "supersedes the previous one, and nothing here is ever edited. The evidence "
        "is ids only — never file contents, provider payloads or checklist comments."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
    },
)
async def list_background_check_decisions(
    company_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BackgroundCheckDecisionListResponse:
    # Raises `ExporterProfileNotFoundError` for an unknown company, so a bad id is a
    # 404 rather than an empty list that reads like "this company has no decisions".
    await BackgroundCheckReader(db).standing(company_id)

    repository = BackgroundCheckDecisionRepository(db)
    rows, total = await repository.list_for_company(company_id, limit=limit, offset=offset)
    snapshots = await repository.evidence_for([row.id for row in rows])
    names = await actor_names(
        db, user, [*(row.decided_by for row in rows), *(row.approved_by for row in rows)]
    )
    cycles = await CheckCycleRepository(db).list_for_company(company_id)
    initial = cycles[0] if cycles else None
    number_of = {cycle.id: cycle.number for cycle in cycles}

    return BackgroundCheckDecisionListResponse(
        decisions=[
            BackgroundCheckDecisionResponse(
                id=row.id,
                company_id=row.company_id,
                from_value=row.from_value,
                to_value=row.to_value,
                decided_by=row.decided_by,
                decided_by_name=names.get(row.decided_by or ""),
                decided_by_kind=row.decided_by_kind.value,
                source=row.source.value,
                decided_at=row.decided_at,
                reason=row.reason,
                risk_rating=row.risk_rating,
                supersedes_decision_id=row.supersedes_decision_id,
                rules_version=row.rules_version,
                cycle_id=resolved_cycle_id(row.cycle_id, initial),
                cycle_number=number_of.get(resolved_cycle_id(row.cycle_id, initial)),
                proposal_id=row.proposal_id,
                approved_by=row.approved_by,
                approved_by_name=names.get(row.approved_by or ""),
                approved_at=row.approved_at,
                expires_at=row.expires_at,
                evidence=[
                    EvidenceItemResponse.from_view(
                        EvidenceItemView(
                            kind=BackgroundCheckEvidenceKind(item.kind),
                            crm_document_id=item.crm_document_id,
                            verification_result_id=item.verification_result_id,
                            verification_review_id=item.verification_review_id,
                            screening_review_item_id=item.screening_review_item_id,
                        )
                    )
                    for item in snapshots.get(row.id, [])
                ],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── One decision's evidence, resolved ───────────────────────────────────────


def _evidence_response(
    view: DecisionEvidenceView, names: dict[str, str]
) -> DecisionEvidenceResponse:
    items: list[DecisionEvidenceItemResponse] = []
    for item in view.items:
        verification = item.verification
        screening = item.screening_item
        document = item.document
        items.append(
            DecisionEvidenceItemResponse(
                kind=item.kind.value,
                verification=(
                    DecisionEvidenceVerification(
                        verification_result_id=verification.verification_result_id,
                        verification_type=verification.verification_type,
                        status=verification.status,
                        risk_level=verification.risk_level,
                        provider=verification.provider,
                        provenance=verification.provenance,
                        is_placeholder=verification.is_placeholder,
                        performed_at=verification.performed_at,
                        recorded_by=verification.recorded_by,
                        recorded_by_name=names.get(verification.recorded_by or ""),
                        evidence_note=verification.evidence_note,
                        evidence_refs=[
                            VerificationEvidenceRefOut(**ref) for ref in verification.evidence_refs
                        ],
                        pinned_review=(
                            DecisionEvidencePinnedReview(
                                id=verification.pinned_review.id,
                                review_status=verification.pinned_review.review_status,
                                reviewed_by=verification.pinned_review.reviewed_by,
                                reviewed_by_name=names.get(verification.pinned_review.reviewed_by),
                                reviewed_at=verification.pinned_review.reviewed_at,
                                note=verification.pinned_review.note,
                            )
                            if verification.pinned_review is not None
                            else None
                        ),
                        review_superseded=verification.review_superseded,
                        cycle_id=verification.cycle_id,
                    )
                    if verification is not None
                    else None
                ),
                screening_item=(
                    DecisionEvidenceScreeningItem(
                        screening_review_item_id=screening.screening_review_item_id,
                        item_key=screening.item_key,
                        label=screening.label,
                        retired=screening.retired,
                        status=screening.status,
                        comment=screening.comment,
                        evidence_refs=[
                            VerificationEvidenceRefOut(**ref) for ref in screening.evidence_refs
                        ],
                        reviewed_by=screening.reviewed_by,
                        reviewed_by_name=names.get(screening.reviewed_by or ""),
                        reviewed_at=screening.reviewed_at,
                        cycle_id=screening.cycle_id,
                    )
                    if screening is not None
                    else None
                ),
                document=(
                    DecisionEvidenceDocument(
                        crm_document_id=document.crm_document_id,
                        file_name=document.file_name,
                        category=document.category,
                        document_type=document.document_type,
                        scan_status=document.scan_status,
                        is_downloadable=document.is_downloadable,
                        uploaded_by=document.uploaded_by,
                        uploaded_by_name=names.get(document.uploaded_by or ""),
                        uploaded_at=document.uploaded_at,
                    )
                    if document is not None
                    else None
                ),
            )
        )
    return DecisionEvidenceResponse(
        decision_id=view.decision.id,
        company_id=view.decision.company_id,
        to_value=view.decision.to_value,
        rules_version=view.rules_version,
        cycle_id=view.cycle.id if view.cycle is not None else None,
        cycle_number=view.cycle.number if view.cycle is not None else None,
        items=items,
    )


def _evidence_actor_ids(view: DecisionEvidenceView) -> list[str | None]:
    ids: list[str | None] = []
    for item in view.items:
        if item.verification is not None:
            ids.append(item.verification.recorded_by)
            if item.verification.pinned_review is not None:
                ids.append(item.verification.pinned_review.reviewed_by)
        if item.screening_item is not None:
            ids.append(item.screening_item.reviewed_by)
        if item.document is not None:
            ids.append(item.document.uploaded_by)
    return ids


@router.get(
    "/exporters/{company_id}/background-check/decisions/{decision_id}/evidence",
    response_model=DecisionEvidenceResponse,
    summary="Read what one background-check decision rested on",
    description=(
        "Resolves each id the decision pinned into a readable item: a verification "
        "result (type, status, provenance, who recorded it and when, its evidence and "
        "the review the decision rested on), a screening answer (the item, its status, "
        "comment, evidence and who answered it) or a document (name, category, scan "
        "status and whether it can be opened).\n\n"
        "What is shown is what the decision rested on: every pinned row is append-only "
        "or frozen. A screening item since retired from the checklist keeps its label "
        "(`retired: true`). No identifier (PAN, GSTIN, IEC, CIN, tax id or contact) is "
        "carried. DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {
            "description": (
                "Company not found, or `BACKGROUND_CHECK_DECISION_NOT_FOUND` — no such "
                "decision on this company"
            )
        },
    },
)
async def get_background_check_decision_evidence(
    company_id: uuid.UUID,
    decision_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
) -> DecisionEvidenceResponse:
    await BackgroundCheckReader(db).standing(company_id)  # 404 for an unknown company
    view = await DecisionEvidenceReader(db).for_decision(company_id, decision_id)
    names = await actor_names(db, user, _evidence_actor_ids(view))
    return _evidence_response(view, dict(names))


# ── Check cycles ────────────────────────────────────────────────────────────


@router.get(
    "/exporters/{company_id}/background-check/cycles",
    response_model=CheckCycleListResponse,
    summary="List a company's check cycles",
    description=(
        "Every KYC/KYB round of this company's background check, cycle 1 first. The "
        "check decides on the current cycle (the highest number); earlier cycles stay "
        "readable exactly as they were. Inputs and decisions recorded before cycles "
        "existed belong to cycle 1. DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
    },
)
async def list_check_cycles(
    company_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
) -> CheckCycleListResponse:
    await BackgroundCheckReader(db).standing(company_id)  # 404 for an unknown company
    cycles = await CheckCycleRepository(db).list_for_company(company_id)
    current_id = cycles[-1].id if cycles else None
    names = await actor_names(db, user, (cycle.created_by for cycle in cycles))
    return CheckCycleListResponse(
        cycles=[
            _cycle_response(cycle, current_id=current_id, names=dict(names)) for cycle in cycles
        ],
        current_cycle_id=current_id,
    )


@router.post(
    "/exporters/{company_id}/background-check/cycles",
    response_model=StartCheckCycleResponse,
    status_code=201,
    summary="Start a new check cycle (Re-KYC or Re-KYB)",
    description=(
        "Starts the next KYC/KYB round. Every checklist item starts unanswered and no "
        "result carries over; the previous cycle stays readable.\n\n"
        "On a CLEAR company the same request also records the reopen "
        "(CLEAR → IN_REVIEW, reason \"Re-KYC: …\"), so handovers pause until the new "
        "cycle is cleared. On NOT_STARTED, IN_REVIEW or MORE_INFO the gauge does not "
        "move. A FLAGGED or ON_HOLD company is reassessed first (409). A cycle with "
        "nothing recorded in it yet cannot be followed by another (409), which is also "
        "why two simultaneous starts make one cycle.\n\n"
        "COMPLIANCE and ADMIN only; the actor comes from the session."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
        409: {
            "description": (
                "`CHECK_CYCLE_NOT_ALLOWED` — the company is FLAGGED or ON_HOLD; "
                "`CHECK_CYCLE_EMPTY` — the current cycle has nothing recorded yet"
            )
        },
        422: {"description": "An unknown kind, a missing reason, or an unknown field"},
    },
)
async def start_check_cycle(
    company_id: uuid.UUID,
    payload: StartCheckCycleRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
) -> StartCheckCycleResponse:
    started = await BackgroundCheckService(db).start_cycle(
        company_id,
        kind=CheckCycleKind(payload.kind),
        reason=payload.reason,
        # From the session, never the body.
        actor_id=str(user.id),
        actor_role=user.role,
    )
    names = await actor_names(db, user, [started.cycle.created_by])
    reopen = started.reopen
    return StartCheckCycleResponse(
        cycle=_cycle_response(started.cycle, current_id=started.cycle.id, names=dict(names)),
        reopen_decision=(
            BackgroundCheckDecisionResponse.from_view(
                reopen,
                decided_by_name=names.get(reopen.decided_by or ""),
                cycle_number=started.cycle.number,
            )
            if reopen is not None
            else None
        ),
    )


# ── Maker-checker ───────────────────────────────────────────────────────────


@router.get(
    "/exporters/{company_id}/background-check/proposals",
    response_model=BackgroundCheckProposalListResponse,
    summary="List a company's background-check proposals",
    description=(
        "Every proposed CLEAR, FLAGGED or ON_HOLD on this company, newest first, with "
        "how each ended: approved (and the decision it wrote), rejected (and why) or "
        "withdrawn. An open one carries what **this caller** may do with it. Proposals "
        "and their resolutions are append-only. DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
    },
)
async def list_background_check_proposals(
    company_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BackgroundCheckProposalListResponse:
    await BackgroundCheckReader(db).standing(company_id)  # 404 for an unknown company
    rows, total = await BackgroundCheckProposalRepository(db).list_for_company(
        company_id, limit=limit, offset=offset
    )
    views = [proposal_view(proposal, resolution) for proposal, resolution in rows]
    names = await actor_names(
        db, user, [*(v.proposed_by for v in views), *(v.resolved_by for v in views)]
    )
    cycles = await CheckCycleRepository(db).by_ids([v.cycle_id for v in views])
    awaiting = await BackgroundCheckService(db).open_proposal(company_id)
    stale_reason = awaiting[1] if awaiting is not None else None
    profile = await _profile(db, company_id)
    return BackgroundCheckProposalListResponse(
        proposals=[
            _proposal_response(
                view,
                names=dict(names),
                cycle_number=cycles[view.cycle_id].number if view.cycle_id in cycles else None,
                stale_reason=stale_reason if view.is_open else None,
                viewer=user,
                permissions=permissions,
                reviewer_id=profile.background_check_reviewer_id,
                relationship_manager_id=_rm_id(profile),
            )
            for view in views
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


_RESOLVE_RESPONSES: dict[int | str, dict] = {
    401: {"description": "Unauthorized"},
    403: {
        "description": (
            "COMPLIANCE or ADMIN role required; `BACKGROUND_CHECK_SELF_APPROVAL` — the "
            "proposer cannot approve or reject their own proposal; "
            "`BACKGROUND_CHECK_PROPOSAL_NOT_YOURS` — only the proposer (or ADMIN or "
            "compliance:assign) withdraws; `BACKGROUND_CHECK_CONFLICT_OF_INTEREST` — you "
            "are the review's reviewer or the company's RM; `HIGH_RISK_APPROVAL_REQUIRED`"
            " — a HIGH or CRITICAL CLEAR needs a senior approver"
        )
    },
    404: {"description": "Company not found, or `BACKGROUND_CHECK_PROPOSAL_NOT_FOUND`"},
    409: {
        "description": (
            "`BACKGROUND_CHECK_PROPOSAL_RESOLVED` — already approved, rejected or "
            "withdrawn; `BACKGROUND_CHECK_PROPOSAL_STALE` — the check or its inputs moved "
            "since it was proposed (approve only); `BACKGROUND_CHECK_PREREQUISITES_UNMET`"
        )
    },
}


@router.post(
    "/exporters/{company_id}/background-check/proposals/{proposal_id}/approve",
    response_model=ApproveBackgroundCheckProposalResponse,
    summary="Approve a proposed background-check decision",
    description=(
        "The second person in maker-checker. Under the company's lock: refuses the "
        "proposer and a proposal that is resolved or stale (the check, its latest "
        "decision or its inputs changed since), re-evaluates the Clear rules, then "
        "writes the decision — `decided_by` the proposer, `approved_by` you — pins its "
        "evidence, sets a CLEAR's expiry and makes a qualified PROSPECT a CUSTOMER, in "
        "one transaction. COMPLIANCE or ADMIN; the RM never approves."
    ),
    responses=_RESOLVE_RESPONSES,
)
async def approve_background_check_proposal(
    company_id: uuid.UUID,
    proposal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
) -> ApproveBackgroundCheckProposalResponse:
    approved = await BackgroundCheckService(db).approve(
        company_id,
        proposal_id,
        actor_id=str(user.id),
        actor_role=user.role,
        actor_permissions=permissions,
    )
    decision = await _decision_response(db, user, approved.decision)
    names = await actor_names(db, user, [approved.proposal.proposed_by, str(user.id)])
    return ApproveBackgroundCheckProposalResponse(
        decision=decision,
        proposal=_proposal_response(
            approved.proposal, names=dict(names), cycle_number=decision.cycle_number
        ),
    )


@router.post(
    "/exporters/{company_id}/background-check/proposals/{proposal_id}/reject",
    response_model=BackgroundCheckProposalResponse,
    summary="Reject a proposed background-check decision",
    description=(
        "Closes the proposal with a reason; the check does not move. Anyone but the "
        "proposer, COMPLIANCE or ADMIN. A stale proposal can be rejected."
    ),
    responses={**_RESOLVE_RESPONSES, 422: {"description": "No reason, or an unknown field"}},
)
async def reject_background_check_proposal(
    company_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: RejectBackgroundCheckProposalRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
) -> BackgroundCheckProposalResponse:
    view = await BackgroundCheckService(db).reject(
        company_id,
        proposal_id,
        reason=payload.reason,
        actor_id=str(user.id),
        actor_role=user.role,
    )
    names = await actor_names(db, user, [view.proposed_by, view.resolved_by])
    return _proposal_response(view, names=dict(names))


@router.post(
    "/exporters/{company_id}/background-check/proposals/{proposal_id}/withdraw",
    response_model=BackgroundCheckProposalResponse,
    summary="Withdraw your own background-check proposal",
    description=(
        "The proposer closes their own proposal (the reason is optional); the check does "
        "not move. ADMIN or a holder of compliance:assign may withdraw someone else's — "
        "for a proposer who has left."
    ),
    responses={**_RESOLVE_RESPONSES, 422: {"description": "An unknown field"}},
)
async def withdraw_background_check_proposal(
    company_id: uuid.UUID,
    proposal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
    payload: WithdrawBackgroundCheckProposalRequest | None = None,
) -> BackgroundCheckProposalResponse:
    view = await BackgroundCheckService(db).withdraw(
        company_id,
        proposal_id,
        reason=payload.reason if payload is not None else None,
        actor_id=str(user.id),
        actor_role=user.role,
        actor_permissions=permissions,
    )
    names = await actor_names(db, user, [view.proposed_by])
    return _proposal_response(view, names=dict(names))


@router.get(
    "/background-check/proposals",
    response_model=BackgroundCheckProposalListResponse,
    summary="Background-check proposals across companies (the approval queue)",
    description=(
        "`status=open` (the default) lists every proposal awaiting approval, the "
        "longest-waiting first — the Home card \"Proposals awaiting me\" adds "
        "`awaiting=me`, which keeps only what the caller may approve: not their own, "
        "not one whose review they hold, not a company they are RM of, and a HIGH or "
        "CRITICAL CLEAR only for a senior approver. `approved`, `rejected` and "
        "`withdrawn` list resolved ones, newest first. Each carries the company's name "
        "(never an identifier), what this caller may do with it and, while open, when "
        "it is due and how many people could approve it. COMPLIANCE and ADMIN only: "
        "they are the ones who approve."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
    },
)
async def list_proposals_across_companies(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
    status: Literal["open", "approved", "rejected", "withdrawn"] = "open",
    awaiting: Annotated[
        Literal["me"] | None,
        Query(description="`me`: leave out the caller's own proposals (open queue)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BackgroundCheckProposalListResponse:
    repository = BackgroundCheckProposalRepository(db)
    facts: dict[uuid.UUID, WorkItem] = {}
    if awaiting == "me":
        # Eligibility is the worklist's rule (proposer, reviewer, RM, senior): the
        # worklist chooses and pages the proposals, and only that page is read in full.
        mine = await ComplianceWorklists(db).approvable_by(str(user.id))
        page = mine[offset : offset + limit]
        facts = {item.company_id: item for item in page}
        rows = []
        if page:
            found, _ = await repository.list_across_companies(
                status="OPEN",
                proposal_ids=[item.proposal_id for item in page if item.proposal_id],
                limit=len(page),
            )
            rows = [row for row in found if row[0].company_id in facts]
        total = len(mine)
    else:
        rows, total = await repository.list_across_companies(
            status=status.upper(), limit=limit, offset=offset
        )
        if status == "open":
            facts = await ComplianceWorklists(db).approval_facts([p.company_id for p, _, _ in rows])
    views = [(proposal_view(p, r), name) for p, r, name in rows]
    names = await actor_names(
        db, user, [*(v.proposed_by for v, _ in views), *(v.resolved_by for v, _ in views)]
    )
    cycles = await CheckCycleRepository(db).by_ids([v.cycle_id for v, _ in views])
    return BackgroundCheckProposalListResponse(
        proposals=[
            _proposal_response(
                view,
                names=dict(names),
                cycle_number=cycles[view.cycle_id].number if view.cycle_id in cycles else None,
                company_name=name,
                viewer=user,
                permissions=permissions,
                reviewer_id=facts[view.company_id].reviewer_id if view.company_id in facts else None,
                relationship_manager_id=(
                    facts[view.company_id].relationship_manager_id
                    if view.company_id in facts
                    else None
                ),
                facts=facts.get(view.company_id) if view.is_open else None,
            )
            for view, name in views
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Re-KYC due ──────────────────────────────────────────────────────────────


@router.get(
    "/background-check/due",
    response_model=ReKycDueListResponse,
    summary="Companies due for Re-KYC",
    description=(
        "CLEAR companies whose Clear has expired or expires before `before` (default: "
        "now + the Re-KYC window, 30 days unless configured) — the expired first, then "
        "the soonest. An expired Clear still reads CLEAR (nothing moves the gauge "
        "automatically) but no longer promotes the company or lets its deals be handed "
        "over. A company whose Re-KYC has started is not listed: starting it reopens the "
        "check. Names only, never an identifier. Staff; DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "`before` is not a date-time with a time zone"},
    },
)
async def list_rekyc_due(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    before: Annotated[
        datetime | None,
        Query(description="List Clears expiring before this (ISO 8601, with a time zone)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReKycDueListResponse:
    now = clock.now()
    if before is not None and (before.tzinfo is None or before.utcoffset() is None):
        raise ValidationError("`before` needs a time zone, e.g. 2026-11-01T00:00:00Z")
    cutoff = before if before is not None else now + rekyc_due_window()
    companies, total = await rekyc_due(db, before=cutoff, now=now, limit=limit, offset=offset)
    return ReKycDueListResponse(
        companies=[
            ReKycDueCompanyResponse(
                company_id=item.company_id,
                company_name=item.company_name,
                journey=item.journey,
                background_check=item.background_check,
                expires_at=item.expires_at,
                is_expired=item.is_expired,
                current_cycle_number=item.current_cycle_number,
                pipeline_status=item.pipeline_status,
            )
            for item in companies
        ],
        total=total,
        limit=limit,
        offset=offset,
        before=cutoff,
    )


# ── Who holds the review ────────────────────────────────────────────────────

_REVIEW_RESPONSES: dict[int | str, dict] = {
    401: {"description": "Unauthorized"},
    403: {"description": "`REVIEW_ASSIGN_NOT_ALLOWED`, or the route's role"},
    404: {"description": "Company not found"},
    409: {
        "description": (
            "`REVIEW_NOT_ASSIGNABLE` — not under review; `REVIEW_ALREADY_ASSIGNED`; "
            "`REVIEWER_IS_RM`; `BACKGROUND_CHECK_PROPOSAL_OPEN` (release)"
        )
    },
    422: {"description": "`REVIEWER_NOT_ELIGIBLE`, `REVIEW_REASON_REQUIRED`, an unknown field"},
}


@router.post(
    "/exporters/{company_id}/background-check/reviewer/claim",
    response_model=BackgroundCheckResponse,
    summary="Take an unassigned review (Assign to me)",
    description=(
        "A COMPLIANCE or ADMIN user takes the review of a check that is IN_REVIEW or "
        "MORE_INFO and that nobody holds. Never the company's RM. Returns the standing."
    ),
    responses=_REVIEW_RESPONSES,
)
async def claim_background_check_review(
    company_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
) -> BackgroundCheckResponse:
    await BackgroundCheckService(db).claim_review(
        company_id, actor_id=str(user.id), actor_role=user.role
    )
    return await get_background_check(company_id, db, user, permissions)


@router.put(
    "/exporters/{company_id}/background-check/reviewer",
    response_model=BackgroundCheckResponse,
    summary="Assign or reassign a review",
    description=(
        "ADMIN or `compliance:assign`. The target is an active COMPLIANCE or ADMIN user "
        "who is not the company's RM. Taking a review from someone needs a reason. A "
        "proposal already open survives the change. Returns the standing."
    ),
    responses=_REVIEW_RESPONSES,
)
async def assign_background_check_review(
    company_id: uuid.UUID,
    payload: AssignReviewerRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
) -> BackgroundCheckResponse:
    await BackgroundCheckService(db).assign_review(
        company_id,
        user_id=payload.user_id,
        reason=payload.reason,
        actor_id=str(user.id),
        actor_role=user.role,
        actor_permissions=permissions,
    )
    return await get_background_check(company_id, db, user, permissions)


@router.post(
    "/exporters/{company_id}/background-check/reviewer/release",
    response_model=BackgroundCheckResponse,
    summary="Hand a review back to Awaiting review",
    description=(
        "The reviewer, or ADMIN or `compliance:assign`. Refused while the reviewer's own "
        "proposal is open: withdraw it first. The note is optional. Returns the standing."
    ),
    responses=_REVIEW_RESPONSES,
)
async def release_background_check_review(
    company_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
    payload: ReleaseReviewRequest | None = None,
) -> BackgroundCheckResponse:
    await BackgroundCheckService(db).release_review(
        company_id,
        note=payload.note if payload is not None else None,
        actor_id=str(user.id),
        actor_role=user.role,
        actor_permissions=permissions,
    )
    return await get_background_check(company_id, db, user, permissions)


# ── Worklists ───────────────────────────────────────────────────────────────


async def _work_item_responses(
    db: AsyncSession, user: User, items: list[WorkItem], *, with_notes: bool = False
) -> list[ComplianceWorkItemResponse]:
    names = await actor_names(
        db,
        user,
        [
            *(i.reviewer_id for i in items),
            *(i.relationship_manager_id for i in items),
            *(i.proposed_by for i in items),
        ],
    )
    return [
        ComplianceWorkItemResponse(
            company_id=i.company_id,
            company_name=i.company_name,
            journey=i.journey.value,
            pipeline_status=i.pipeline_status,
            background_check=i.background_check,
            stage=i.stage,
            relationship_manager_id=i.relationship_manager_id,
            relationship_manager_name=names.get(i.relationship_manager_id or ""),
            relationship_manager_inactive=i.relationship_manager_inactive,
            reviewer_id=i.reviewer_id,
            reviewer_name=names.get(i.reviewer_id or ""),
            reviewer_inactive=i.reviewer_inactive,
            waiting_since=i.waiting_since,
            due_at=i.due_at,
            is_due_soon=i.is_due_soon,
            is_overdue=i.is_overdue,
            rejection_count=i.rejection_count,
            proposal_id=i.proposal_id,
            proposed_by_name=names.get(i.proposed_by or ""),
            proposal_to_value=i.proposal_to_value,
            risk_rating=i.risk_rating,
            needs_senior_approval=i.needs_senior_approval,
            eligible_checker_count=i.eligible_checker_count,
            needs_attention=i.needs_attention,
            info_note=i.info_note if with_notes else None,
        )
        for i in items
    ]


@router.get(
    "/background-check/reviews",
    response_model=ComplianceWorklistResponse,
    summary="Compliance worklists",
    description=(
        "`awaiting` — reviews nobody has picked up; `mine` — reviews you hold (under "
        "review, waiting on information, or with your proposal awaiting approval); and, "
        "for ADMIN and holders of compliance:assign only, `in_review` (everyone's), "
        "`overdue` and `needs_attention` (no eligible checker, returned twice, or a "
        "deactivated reviewer). Oldest wait first, each with its business-time "
        "deadline. Computed on read; names only, never an identifier or a reason."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN; the lead views need compliance:assign"},
    },
)
async def list_compliance_worklist(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    permissions: _PERMISSIONS,
    view: Literal["awaiting", "mine", "in_review", "overdue", "needs_attention"] = "awaiting",
) -> ComplianceWorklistResponse:
    if view in LEAD_VIEWS and not holds(user.role, permissions, ASSIGN_REVIEWS):
        raise AnerBaseException(
            detail="Required permission: compliance:assign",
            error_code="FORBIDDEN",
            status_code=403,
        )
    worklists = ComplianceWorklists(db)
    items = worklists.view(await worklists.items(), view, viewer_id=str(user.id))
    return ComplianceWorklistResponse(
        view=view, items=await _work_item_responses(db, user, items), total=len(items)
    )


@router.get(
    "/background-check/info-requests",
    response_model=ComplianceWorklistResponse,
    summary="Companies waiting on information",
    description=(
        "Checks at MORE_INFO, with what was asked for: `relationship_manager=me` — your "
        "companies; `none` — companies with no RM (buyer-only companies above all), the "
        "shared Unowned list; omitted — all. Staff; DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def list_info_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    relationship_manager: Literal["me", "none"] | None = None,
) -> ComplianceWorklistResponse:
    items = ComplianceWorklists.info_requests(
        await ComplianceWorklists(db).items(include_info_notes=True),
        relationship_manager=str(user.id) if relationship_manager == "me" else None,
        unowned=relationship_manager == "none",
    )
    return ComplianceWorklistResponse(
        view=f"info_requests:{relationship_manager or 'all'}",
        items=await _work_item_responses(db, user, items, with_notes=True),
        total=len(items),
    )


@router.get(
    "/worklist/counts",
    response_model=WorklistCountsResponse,
    summary="Counts for the navigation badges",
    description=(
        "One call for the nav: how many items each list this caller may see holds. A "
        "list they may not see is null. Numbers only — no names, identifiers or text. "
        "Staff; DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def get_worklist_counts(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
) -> WorklistCountsResponse:
    worklists = ComplianceWorklists(db)
    counts = worklists.counts(
        await worklists.items(),
        viewer_id=str(user.id),
        viewer_role=user.role,
        viewer_permissions=permissions,
    )
    return WorklistCountsResponse(**counts.__dict__)


@router.get(
    "/background-check/recent-decisions",
    response_model=RecentDecisionListResponse,
    summary="Decisions on my companies",
    description=(
        "CLEAR, FLAGGED and ON_HOLD decisions of the last `days` (default 14) on "
        "companies you are RM of or whose outcome you proposed, newest first. The Home "
        "card. No reason text. Staff; DEVELOPER is refused."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def list_recent_decisions(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_STAFF)],
    days: Annotated[int, Query(ge=1, le=90)] = 14,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecentDecisionListResponse:
    decisions = await ComplianceWorklists(db).recent_decisions(
        viewer_id=str(user.id), days=days, limit=limit
    )
    names = await actor_names(
        db, user, [*(d.decided_by for d in decisions), *(d.approved_by for d in decisions)]
    )
    return RecentDecisionListResponse(
        decisions=[
            RecentDecisionResponse(
                company_id=d.company_id,
                company_name=d.company_name,
                decision_id=d.decision_id,
                to_value=d.to_value,
                risk_rating=d.risk_rating,
                decided_at=d.decided_at,
                decided_by_name=names.get(d.decided_by or ""),
                approved_by_name=names.get(d.approved_by or ""),
            )
            for d in decisions
        ],
        days=days,
    )
