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
only OPERATIONS, COMPLIANCE and ADMIN. Whether DEVELOPER may read the gauge, the
decision reasons and the evidence ids is **D8, open**; the recorded default until it
is answered is no widening (``4a-task.md`` §13). A decision's reason is free text a
compliance officer typed about a company, which is exactly the kind of thing D8 exists
to decide rather than assume.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.background_check import (
    BackgroundCheckDecisionListResponse,
    BackgroundCheckDecisionResponse,
    BackgroundCheckMoveResponse,
    BackgroundCheckResponse,
    EvidenceItemResponse,
    RecordBackgroundCheckDecisionRequest,
)
from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.domain.background_check_views import EvidenceItemView
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckEvidenceKind,
    BackgroundCheckState,
)
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

#: Compliance work by internal staff (architecture §3.7). DEVELOPER is absent — D8.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)


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
                "current value; or `BACKGROUND_CHECK_PREREQUISITES_UNMET` — CLEAR "
                "with prerequisites outstanding, naming each"
            )
        },
        422: {
            "description": (
                "`BACKGROUND_CHECK_REASON_REQUIRED`, "
                "`BACKGROUND_CHECK_RISK_REQUIRED`, or an unknown field in the body"
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
        # From the session, never the body (contract §5.1).
        actor_id=str(user.id),
        actor_role=user.role,
    )
    return BackgroundCheckDecisionResponse.from_view(view)


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

    return BackgroundCheckDecisionListResponse(
        decisions=[
            BackgroundCheckDecisionResponse(
                id=row.id,
                company_id=row.company_id,
                from_value=row.from_value,
                to_value=row.to_value,
                decided_by=row.decided_by,
                decided_by_kind=row.decided_by_kind.value,
                source=row.source.value,
                decided_at=row.decided_at,
                reason=row.reason,
                risk_rating=row.risk_rating,
                supersedes_decision_id=row.supersedes_decision_id,
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
