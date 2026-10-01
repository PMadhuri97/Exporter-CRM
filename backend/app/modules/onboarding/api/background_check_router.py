"""Background-check routes — **owner: Developer 4A** (L4-03, L4-13).

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
only OPERATIONS, COMPLIANCE and ADMIN: **D8**, settled 28 September 2026, refuses
DEVELOPER the gauge, the decision reasons and the evidence ids, reads included. A
decision's reason is free text a compliance officer typed about a real company.

**Developer 1 (compliance engine), 1 October 2026.** The standing also serves the
company's compliance facts (F1), its current check cycle and the cycles this caller may
start (P2-3c/d). Three routes were added, under the same D8 rule: one decision's
evidence resolved into readable items (P2-1a), the company's cycles, and starting a
Re-KYC / Re-KYB (COMPLIANCE and ADMIN only).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.background_check import (
    BackgroundCheckCycleActionResponse,
    BackgroundCheckDecisionListResponse,
    BackgroundCheckDecisionResponse,
    BackgroundCheckMoveResponse,
    BackgroundCheckResponse,
    CheckCycleListResponse,
    CheckCycleResponse,
    CompanyComplianceFactsResponse,
    DecisionEvidenceDocument,
    DecisionEvidenceItemResponse,
    DecisionEvidencePinnedReview,
    DecisionEvidenceResponse,
    DecisionEvidenceScreeningItem,
    DecisionEvidenceVerification,
    EvidenceItemResponse,
    RecordBackgroundCheckDecisionRequest,
    StartCheckCycleRequest,
    StartCheckCycleResponse,
)
from app.modules.onboarding.api.schemas.verification import VerificationEvidenceRefOut
from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.application.decision_evidence import (
    DecisionEvidenceReader,
    DecisionEvidenceView,
)
from app.modules.onboarding.domain.background_check_views import EvidenceItemView
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckEvidenceKind,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle, CheckCycleKind
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
    resolved_cycle_id,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db
from app.shared import clock

router = APIRouter(tags=["Exporter CRM"])

#: Compliance work by internal staff (architecture §3.7). DEVELOPER is absent (D8).
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
#: Who may start a check cycle (IQ-3). The service enforces the same rule.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)


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
) -> BackgroundCheckResponse:
    standing = await BackgroundCheckReader(db).standing(company_id)
    current = BackgroundCheckState(standing.value)
    service = BackgroundCheckService(db)

    blocked: list[str] = []
    if current is BackgroundCheckState.IN_REVIEW:
        # Advisory: `clear` evaluates the same rule again under the row lock, which
        # is what actually decides. This is here so the screen can explain first.
        blocked = list(await service.clear_prerequisites(company_id))

    facts = await ComplianceFactsService(db).for_company(company_id, clock.now())
    current_cycle = await CheckCycleRepository(db).current_for_company(company_id)
    names = await actor_names(
        db, user, [current_cycle.created_by] if current_cycle is not None else []
    )

    return BackgroundCheckResponse(
        company_id=standing.company_id,
        value=current,
        risk_rating=standing.risk_rating,
        latest_decision_id=standing.latest_decision_id,
        clearing_decision_id=standing.clearing_decision_id,
        decided_at=standing.decided_at,
        allowed_moves=[
            BackgroundCheckMoveResponse.from_view(move)
            for move in service.allowed_moves(current, user.role)
        ],
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
    )


@router.post(
    "/exporters/{company_id}/background-check/decisions",
    response_model=BackgroundCheckDecisionResponse,
    status_code=201,
    summary="Record a background-check decision",
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
        "check and record what arrived, and nothing else."
    ),
    responses={
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
                "longer at `from_value`; or `BACKGROUND_CHECK_PREREQUISITES_UNMET` — "
                "CLEAR with prerequisites outstanding, naming each"
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
) -> BackgroundCheckDecisionResponse:
    view = await BackgroundCheckService(db).record_decision(
        company_id,
        to_value=payload.to_value,
        reason=payload.reason,
        risk=payload.risk_rating,
        seen_value=payload.from_value,
        # From the session, never the body (contract §5.1).
        actor_id=str(user.id),
        actor_role=user.role,
    )
    names = await actor_names(db, user, [view.decided_by])
    cycles = await CheckCycleRepository(db).by_ids([view.cycle_id] if view.cycle_id else [])
    cycle = cycles.get(view.cycle_id) if view.cycle_id else None
    return BackgroundCheckDecisionResponse.from_view(
        view,
        decided_by_name=names.get(view.decided_by or ""),
        cycle_number=cycle.number if cycle is not None else None,
    )


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
    names = await actor_names(db, user, (row.decided_by for row in rows))
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


# ── One decision's evidence, resolved (Developer 1, P2-1a) ──────────────────


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
        "carried. DEVELOPER is refused (D8)."
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


# ── Check cycles (Developer 1, P2-3c/d) ─────────────────────────────────────


@router.get(
    "/exporters/{company_id}/background-check/cycles",
    response_model=CheckCycleListResponse,
    summary="List a company's check cycles",
    description=(
        "Every KYC/KYB round of this company's background check, cycle 1 first. The "
        "check decides on the current cycle (the highest number); earlier cycles stay "
        "readable exactly as they were. Inputs and decisions recorded before cycles "
        "existed belong to cycle 1. DEVELOPER is refused (D8)."
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
