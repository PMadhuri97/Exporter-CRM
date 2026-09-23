"""Compliance case routes: a thin HTTP surface over `app.modules.cases`.

The cases module has working application services and no router of its own. It
must never import onboarding, and its tickets stay closed, so the minimum surface
lives here, in the same module as the rest of the case glue
(`application/case_bridge_service.py`):

- `GET  /compliance-cases`                    queue, filterable by status and type
- `GET  /compliance-cases/{case_id}`          detail: evidence, timeline, snapshot
- `POST /compliance-cases/{case_id}/notes`    add a note
- `POST /compliance-cases/{case_id}/decision` resolve with a mandatory rationale;
                                              the exporter's lifecycle follows

`/compliance-cases`, not `/cases`: `/onboarding/cases` is already taken by the
onboarding KYC case model (`router.py`), an unrelated entity.

Every route is COMPLIANCE or ADMIN only. An evidence package carries PII, and
every write here is a compliance decision.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases import (
    MAX_NOTE_LENGTH,
    MIN_SUBSTANTIVE_NOTE_LENGTH,
    ActorType,
    CaseSeverity,
    CaseStatus,
    CaseType,
    ResolutionAction,
    TimelineEventType,
)
from app.modules.onboarding.application.case_bridge_service import CaseBridgeService, CaseReview
from app.modules.onboarding.domain.entities.exporter_enums import ExporterLifecycleStatus
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(prefix="/compliance-cases", tags=["Compliance cases"])

_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)
_FORBIDDEN = {403: {"description": "COMPLIANCE or ADMIN role required"}}
_UNAUTHORIZED = {401: {"description": "Unauthorized"}}


def _actor_type(user: User) -> ActorType:
    # Both roles this router admits are compliance decision-makers.
    return ActorType.COMPLIANCE_OFFICER


# ── Schemas ─────────────────────────────────────────────────────────────────


class CaseSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_reference: str
    case_type: CaseType
    case_status: CaseStatus
    severity: CaseSeverity
    priority: int
    title: str
    customer_id: uuid.UUID | None
    onboarding_id: uuid.UUID | None
    assigned_to: str | None
    sla_deadline: datetime | None
    sla_breached: bool
    resolution_action: ResolutionAction | None
    resolution_note: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime
    last_updated_at: datetime


class CaseQueueResponse(BaseModel):
    cases: list[CaseSummaryResponse]
    total: int
    limit: int
    offset: int


class EvidenceItemResponse(BaseModel):
    id: uuid.UUID
    evidence_type: str
    source_epic: str
    source_reference_id: uuid.UUID
    added_at: datetime
    added_by: str
    is_key_evidence: bool
    evidence_data: dict[str, Any] | None
    in_snapshot: bool = Field(
        description="Recorded in the evidence snapshot taken when the resolution was proposed"
    )
    added_after_snapshot: bool = Field(
        description="Arrived after that snapshot; the decision did not rest on it"
    )
    changed_since_snapshot: bool = Field(
        description="Its data no longer matches the digest the snapshot recorded"
    )


class EvidenceSnapshotResponse(BaseModel):
    timeline_event_id: uuid.UUID
    taken_at: datetime
    taken_by: str
    items: list[dict[str, Any]]


class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: TimelineEventType
    from_status: str | None
    to_status: str
    actor_id: str
    actor_type: ActorType
    note: str | None
    payload: dict[str, Any]
    occurred_at: datetime


class CaseDetailResponse(BaseModel):
    case: CaseSummaryResponse
    evidence_package: dict[str, Any]
    evidence_items: list[EvidenceItemResponse]
    evidence_snapshot: EvidenceSnapshotResponse | None = Field(
        description="Null until a resolution has been proposed"
    )
    timeline: list[TimelineEventResponse]

    @classmethod
    def from_review(cls, review: CaseReview) -> CaseDetailResponse:
        detail = review.detail
        in_snapshot = (
            {uuid.UUID(e["evidence_item_id"]) for e in review.snapshot.items}
            if review.snapshot
            else set()
        )
        return cls(
            case=CaseSummaryResponse.model_validate(detail.case),
            evidence_package=detail.evidence_package,
            evidence_items=[
                EvidenceItemResponse(
                    id=item.id,
                    evidence_type=item.evidence_type,
                    source_epic=item.source_epic,
                    source_reference_id=item.source_reference_id,
                    added_at=item.added_at,
                    added_by=item.added_by,
                    is_key_evidence=item.is_key_evidence,
                    evidence_data=item.evidence_data,
                    in_snapshot=item.id in in_snapshot,
                    added_after_snapshot=item.id in review.added_after_snapshot,
                    changed_since_snapshot=item.id in review.changed_since_snapshot,
                )
                for item in detail.evidence_items
            ],
            evidence_snapshot=(
                EvidenceSnapshotResponse(
                    timeline_event_id=review.snapshot.timeline_event_id,
                    taken_at=review.snapshot.taken_at,
                    taken_by=review.snapshot.taken_by,
                    items=review.snapshot.items,
                )
                if review.snapshot
                else None
            ),
            timeline=[TimelineEventResponse.model_validate(e) for e in detail.timeline_events],
        )


class AddCaseNoteRequest(BaseModel):
    note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)


class CaseDecisionRequest(BaseModel):
    outcome: Literal["APPROVE", "REJECT"]
    rationale: str = Field(
        min_length=MIN_SUBSTANTIVE_NOTE_LENGTH,
        description=(
            f"Why. At least {MIN_SUBSTANTIVE_NOTE_LENGTH} characters; recorded as the "
            f"case's resolution_note."
        ),
    )


class CaseDecisionResponse(BaseModel):
    case: CaseSummaryResponse
    exporter_lifecycle_status: ExporterLifecycleStatus
    awaiting_second_reviewer: bool = Field(
        description=(
            "True only with the two-person rule switched on, when this call "
            "proposed and a different reviewer must still decide"
        )
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=CaseQueueResponse,
    summary="Case queue",
    description="Compliance cases, newest first, filterable by status and case type.",
    responses={200: {"model": CaseQueueResponse}, **_UNAUTHORIZED, **_FORBIDDEN},
)
async def list_compliance_cases(
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
    status: CaseStatus | None = Query(default=None),
    case_type: CaseType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CaseQueueResponse:
    cases, total = await CaseBridgeService(db).list_queue(
        status=status, case_type=case_type, limit=limit, offset=offset
    )
    return CaseQueueResponse(
        cases=[CaseSummaryResponse.model_validate(c) for c in cases],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{case_id}",
    response_model=CaseDetailResponse,
    summary="Case detail",
    description=(
        "The case with its aggregated evidence, each evidence item, and the full "
        "timeline. Once a resolution has been proposed, `evidence_snapshot` is the "
        "evidence list as it stood at that moment. Items that arrived later are "
        "flagged `added_after_snapshot`."
    ),
    responses={
        200: {"model": CaseDetailResponse},
        **_UNAUTHORIZED,
        **_FORBIDDEN,
        404: {"description": "Case not found"},
    },
)
async def get_compliance_case(
    case_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> CaseDetailResponse:
    review = await CaseBridgeService(db).get_review(case_id, actor_type=_actor_type(current_user))
    return CaseDetailResponse.from_review(review)


@router.post(
    "/{case_id}/notes",
    response_model=TimelineEventResponse,
    status_code=201,
    summary="Add a note to a case",
    responses={
        201: {"model": TimelineEventResponse},
        **_UNAUTHORIZED,
        **_FORBIDDEN,
        404: {"description": "Case not found"},
        409: {"description": "Case is resolved or closed"},
        422: {"description": "Empty or over-long note"},
    },
)
async def add_compliance_case_note(
    case_id: uuid.UUID,
    body: AddCaseNoteRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> TimelineEventResponse:
    event = await CaseBridgeService(db).add_note(
        case_id, body.note, actor_id=str(current_user.id), actor_type=_actor_type(current_user)
    )
    return TimelineEventResponse.model_validate(event)


@router.post(
    "/{case_id}/decision",
    response_model=CaseDecisionResponse,
    summary="Decide an onboarding-review case",
    description=(
        "Records the resolution (`APPROVE_ONBOARDING` or `REJECT_ONBOARDING`) with a "
        "mandatory rationale, then moves the exporter. The lifecycle transition "
        "follows the resolution: to `ONBOARDED` on approval, back to "
        "`DATA_COLLECTION` on rejection. The evidence list is snapshotted when the "
        "resolution is proposed."
    ),
    responses={
        200: {"model": CaseDecisionResponse},
        **_UNAUTHORIZED,
        **_FORBIDDEN,
        404: {"description": "Case not found"},
        409: {
            "description": (
                "Case already resolved, not an onboarding review, or the exporter is "
                "no longer in COMPLIANCE_REVIEW"
            )
        },
        422: {"description": "Rationale missing or too short"},
    },
)
async def decide_compliance_case(
    case_id: uuid.UUID,
    body: CaseDecisionRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> CaseDecisionResponse:
    result = await CaseBridgeService(db).decide(
        case_id,
        outcome=body.outcome,
        rationale=body.rationale,
        actor_id=str(current_user.id),
        actor_type=_actor_type(current_user),
    )
    return CaseDecisionResponse(
        case=CaseSummaryResponse.model_validate(result.case),
        exporter_lifecycle_status=result.lifecycle_status,
        awaiting_second_reviewer=result.awaiting_second_reviewer,
    )


__all__ = ["router"]
