"""Exporter CRM API routes (EXP-1).

Kept in a sibling file rather than added directly to `router.py`: at the time
this ticket was built, `router.py` was already 277 lines covering the case
management state machine and the pre-backlog onboarding-foundation routes,
each documented with the same `summary`/`description`/`responses` verbosity
these nine new routes would need — appending them in place would have pushed
that file past 550 lines and mixed three unrelated route groups (case state
machine, onboarding foundation, exporter CRM) in one module. `router.py`
already groups its own routes with `# ── ─────` section banners rather than
splitting files, so this split is the exception, made because size crossed
the point the ticket itself flagged as worth checking, not because the
existing convention calls for one file per feature.

This module's `router` is mounted into `router.py`'s own `router` via
`include_router`, so it inherits the `/onboarding` prefix `app/api/rest/
router.py` applies to the whole module — routes are declared here with only
the `/exporters` prefix, matching the ticket's `/onboarding/exporters...`
paths once combined.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.exporter import (
    AddExporterContactRequest,
    CreateExporterProfileRequest,
    ExporterActivityListResponse,
    ExporterActivityResponse,
    ExporterContactListResponse,
    ExporterContactResponse,
    ExporterProfileDetailResponse,
    ExporterProfileListItemResponse,
    ExporterProfileResponse,
    ExporterProfileSearchResponse,
    LogExporterActivityRequest,
    PendingActivityListResponse,
    PendingActivityResponse,
    TransitionLifecycleStatusRequest,
    UpdateExporterProfileRequest,
    UpdateScreeningReviewItemRequest,
    ScreeningReviewItemResponse,
    ScreeningReviewListResponse,
    BankActivityFindingResponse,
    BankActivityResponse,
)
from app.modules.onboarding.application import (
    ExporterContactActivityService,
    ExporterProfileService,
)
from app.modules.onboarding.application.screening_review_service import ScreeningReviewService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterActivityType,
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.configuration.config import settings
from app.platform.database.services import get_db
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

# Compliance decisions (recording a screening-checklist decision) are
# compliance-owned; a plain API_USER must never be able to mark a sanctions
# check PASSED. Lifecycle moves are gated per edge in the service instead
# (`COMPLIANCE_GATED_FROM_STATUSES`), so RMs can still work the sales stages.
_COMPLIANCE_OR_ADMIN = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)
# Routine CRM reads and writes by internal staff (Relationship Managers are
# OPERATIONS, and may read every exporter). PAN/GSTIN/IEC and contact
# email/phone are masked per viewer in the response schemas.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
# Masked CRM reads. DEVELOPER may read the CRM but never sees a raw
# identifier (`can_reveal_identifiers` is always False for it), per the role
# capability matrix in docs/exporter-crm-frontend-tickets.md.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)
_COMPLIANCE_ROLES = frozenset({UserRole.COMPLIANCE, UserRole.ADMIN})


async def _relationship_manager_user_id(
    db: AsyncSession, customer_id: uuid.UUID
) -> uuid.UUID | None:
    """The exporter's owning RM, for masking routes that don't load the profile."""
    return await db.scalar(
        select(ExporterProfile.relationship_manager_user_id).where(
            ExporterProfile.customer_id == customer_id
        )
    )


# ── Profile ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ExporterProfileResponse,
    status_code=201,
    summary="Create an exporter profile",
    description=(
        "Creates the enduring exporter/customer relationship record. `source` is "
        "immutable once set. An optional `Idempotency-Key` header makes a retried "
        "create safe for an untrusted/retrying caller; without one, a repeat call "
        "for the same `customer_id` still returns the existing profile rather than "
        "erroring, via the table's own uniqueness constraint."
    ),
    responses={
        201: {"model": ExporterProfileResponse, "description": "Profile created"},
        200: {
            "model": ExporterProfileResponse,
            "description": "Idempotent replay or existing profile for this customer_id",
        },
        401: {"description": "Unauthorized"},
        403: {
            "description": (
                "OPERATIONS, COMPLIANCE or ADMIN role required; creating at "
                "ONBOARDED or any later status requires COMPLIANCE or ADMIN"
            )
        },
        422: {"description": "Invalid request body"},
    },
)
async def create_exporter_profile(
    body: CreateExporterProfileRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExporterProfileResponse:
    # EXP-3 "Add Exporter": all three lead fields present (the schema's own
    # validator guarantees "all or nothing") routes through `create_lead`,
    # which is the only path that gives the new Lead a `legal_name` at all —
    # see `CreateExporterProfileRequest`'s docstring.
    if body.legal_name is not None:
        assert body.incorporation_country is not None
        assert body.initial_user_email is not None
        if idempotency_key is None:
            raise ValidationError(
                "Creating a new exporter Lead (legal_name supplied) requires an "
                "Idempotency-Key header"
            )
        _request, profile, created = await ExporterProfileService(db).create_lead(
            tenant_id=uuid.UUID(settings.ANER_TENANT_ID),
            legal_name=body.legal_name,
            incorporation_country=body.incorporation_country,
            initial_user_email=body.initial_user_email,
            idempotency_key=idempotency_key,
            source=body.source,
            customer_id=body.customer_id,
            gstin=body.gstin,
            pan=body.pan,
            iec=body.iec,
            relationship_manager=body.relationship_manager,
            industry=body.industry,
            export_markets=body.export_markets,
            products=body.products,
            year_established=body.year_established,
            website=body.website,
            actor_id=str(current_user.id),
        )
        # `status_code=201` on the decorator is only the default — found via
        # manual end-to-end testing that neither this branch nor the one
        # below ever actually overrode it, contradicting this endpoint's own
        # documented 200-vs-201 `responses` contract above. A resubmitted
        # `Idempotency-Key` correctly returned the same resource both times;
        # it just always claimed "201 Created" while doing it.
        if not created:
            response.status_code = 200
        return ExporterProfileResponse.model_validate(profile).masked_for(current_user)

    customer_id = body.customer_id or uuid.uuid4()
    profile, created = await ExporterProfileService(db).create_or_get_profile(
        customer_id,
        source=body.source,
        lifecycle_status=body.lifecycle_status,
        gstin=body.gstin,
        pan=body.pan,
        iec=body.iec,
        relationship_manager=body.relationship_manager,
        industry=body.industry,
        export_markets=body.export_markets,
        products=body.products,
        year_established=body.year_established,
        website=body.website,
        idempotency_key=idempotency_key,
        actor_id=str(current_user.id),
        compliance_authorized=current_user.role in _COMPLIANCE_ROLES,
    )
    if not created:
        response.status_code = 200
    return ExporterProfileResponse.model_validate(profile).masked_for(current_user)


@router.get(
    "/{customer_id}",
    response_model=ExporterProfileDetailResponse,
    summary="Read an exporter profile's full detail",
    description=(
        "The profile plus its contacts, recent activities, and linked "
        "OnboardingRequest history."
    ),
    responses={
        200: {"model": ExporterProfileDetailResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
        404: {"description": "Exporter profile not found"},
    },
)
async def get_exporter_profile_detail(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileDetailResponse:
    detail = await ExporterProfileService(db).get_profile_detail(customer_id)
    return ExporterProfileDetailResponse.from_detail(detail).masked_for(current_user)


@router.patch(
    "/{customer_id}",
    response_model=ExporterProfileResponse,
    summary="Update an exporter profile's mutable CRM fields",
    description=(
        "Updates CRM fields. `source` and `lifecycle_status` are not accepted here "
        "(422 if present) — source is immutable, and lifecycle_status is owned by "
        "the transition endpoint."
    ),
    responses={
        200: {"model": ExporterProfileResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Exporter profile not found"},
        422: {"description": "Invalid request body"},
    },
)
async def update_exporter_profile(
    customer_id: uuid.UUID,
    body: UpdateExporterProfileRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileResponse:
    profile = await ExporterProfileService(db).update_profile(
        customer_id, **body.model_dump(exclude_unset=True)
    )
    return ExporterProfileResponse.model_validate(profile).masked_for(current_user)


@router.post(
    "/{customer_id}/transition",
    response_model=ExporterProfileResponse,
    summary="Transition an exporter's lifecycle_status",
    description=(
        "The only way lifecycle_status changes. Validates the move against the "
        "permitted-transition table; an illegal transition returns 409 and leaves "
        "the profile untouched."
    ),
    responses={
        200: {"model": ExporterProfileResponse},
        401: {"description": "Unauthorized"},
        403: {
            "description": (
                "OPERATIONS, COMPLIANCE or ADMIN role required; a move out of "
                "COMPLIANCE_REVIEW or any later status requires COMPLIANCE or ADMIN"
            )
        },
        404: {"description": "Exporter profile not found"},
        409: {"description": "Illegal lifecycle_status transition"},
    },
)
async def transition_exporter_lifecycle_status(
    customer_id: uuid.UUID,
    body: TransitionLifecycleStatusRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileResponse:
    profile = await ExporterProfileService(db).transition_lifecycle_status(
        customer_id,
        body.to_status,
        actor_id=str(current_user.id),
        compliance_authorized=current_user.role in _COMPLIANCE_ROLES,
    )
    return ExporterProfileResponse.model_validate(profile).masked_for(current_user)


@router.get(
    "",
    response_model=ExporterProfileSearchResponse,
    summary="Search exporter profiles",
    description=(
        "Filters by gstin, pan, iec, source, lifecycle status (exact match) and "
        "legal_name (case-insensitive partial match against the linked "
        "OnboardingRequest.legal_name)."
    ),
    responses={
        200: {"model": ExporterProfileSearchResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def search_exporter_profiles(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    gstin: str | None = Query(default=None),
    pan: str | None = Query(default=None),
    iec: str | None = Query(default=None),
    legal_name: str | None = Query(default=None),
    source: ExporterSource | None = Query(default=None),
    status: ExporterLifecycleStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ExporterProfileSearchResponse:
    items = await ExporterProfileService(db).search_profiles(
        gstin=gstin,
        pan=pan,
        iec=iec,
        legal_name_contains=legal_name,
        source=source,
        lifecycle_status=status,
        limit=limit,
        offset=offset,
    )
    return ExporterProfileSearchResponse(
        profiles=[
            ExporterProfileListItemResponse.model_validate(item).masked_for(current_user)
            for item in items
        ],
        limit=limit,
        offset=offset,
    )


# ── Contacts ──────────────────────────────────────────────────────────────


@router.post(
    "/{customer_id}/contacts",
    response_model=ExporterContactResponse,
    status_code=201,
    summary="Add a contact to an exporter relationship",
    description=(
        "Setting is_primary=true demotes any existing primary contact for this "
        "customer in the same transaction — never two primaries at once."
    ),
    responses={
        201: {"model": ExporterContactResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "Invalid request body"},
    },
)
async def add_exporter_contact(
    customer_id: uuid.UUID,
    body: AddExporterContactRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterContactResponse:
    contact = await ExporterContactActivityService(db).add_contact(
        customer_id,
        name=body.name,
        role=body.role,
        email=body.email,
        phone=body.phone,
        department=body.department,
        is_primary=body.is_primary,
    )
    owner = await _relationship_manager_user_id(db, customer_id)
    return ExporterContactResponse.model_validate(contact).masked_for(current_user, owner)


@router.get(
    "/{customer_id}/contacts",
    response_model=ExporterContactListResponse,
    summary="List an exporter's contacts",
    responses={
        200: {"model": ExporterContactListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_exporter_contacts(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> ExporterContactListResponse:
    contacts = await ExporterContactActivityService(db).list_contacts(customer_id)
    owner = await _relationship_manager_user_id(db, customer_id)
    return ExporterContactListResponse(
        customer_id=customer_id,
        contacts=[
            ExporterContactResponse.model_validate(c).masked_for(current_user, owner)
            for c in contacts
        ],
    )


# ── Activities ────────────────────────────────────────────────────────────


@router.post(
    "/{customer_id}/activities",
    response_model=ExporterActivityResponse,
    status_code=201,
    summary="Log a relationship-history activity",
    description="Append-only: once logged, an activity can never be edited or deleted.",
    responses={
        201: {"model": ExporterActivityResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        422: {"description": "Invalid request body"},
    },
)
async def log_exporter_activity(
    customer_id: uuid.UUID,
    body: LogExporterActivityRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterActivityResponse:
    activity = await ExporterContactActivityService(db).log_activity(
        customer_id,
        activity_type=body.activity_type,
        subject=body.subject,
        notes=body.notes,
        due_at=body.due_at,
        actor_id=str(current_user.id),
    )
    return ExporterActivityResponse.model_validate(activity)


@router.get(
    "/{customer_id}/activities",
    response_model=ExporterActivityListResponse,
    summary="List an exporter's relationship-history activities",
    description="Most recent first. Optionally filtered by activity_type.",
    responses={
        200: {"model": ExporterActivityListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_exporter_activities(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    activity_type: ExporterActivityType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ExporterActivityListResponse:
    activities = await ExporterContactActivityService(db).list_activities(
        customer_id, activity_type=activity_type, limit=limit, offset=offset
    )
    return ExporterActivityListResponse(
        customer_id=customer_id,
        activities=[ExporterActivityResponse.model_validate(a) for a in activities],
    )


# ── Pending activities (Piece 2: cross-exporter follow-up list) ─────────────
#
# Deliberately `/activities/pending`, not nested under `/{customer_id}` — this
# route spans every exporter, unlike every other route in this file. Two path
# segments after the `/exporters` prefix keeps it clear of every existing
# route here (`/{customer_id}`, `/{customer_id}/contacts`,
# `/{customer_id}/activities`): none of them match a two-segment path whose
# first segment is the literal `activities`, so there is no ordering hazard
# regardless of where this route is declared relative to those.


@router.get(
    "/activities/pending",
    response_model=PendingActivityListResponse,
    summary="List pending/follow-up activities across every exporter",
    description=(
        "Everything pending, across every exporter — a Follow-ups/pending-work "
        "screen's own query. Omit actor_id for a manager's team-wide view; pass it "
        "to scope to one person's own pending items. 'Pending' means the activity "
        "carries a due_at (TASK/FOLLOW_UP entries, typically); each row already "
        "carries the exporter's display name and a computed is_overdue flag."
    ),
    responses={
        200: {"model": PendingActivityListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"},
    },
)
async def list_pending_exporter_activities(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    actor_id: str | None = Query(default=None),
    activity_type: ExporterActivityType | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    due_after: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PendingActivityListResponse:
    views = await ExporterContactActivityService(db).list_pending_activities(
        actor_id=actor_id,
        activity_type=activity_type,
        due_before=due_before,
        due_after=due_after,
        limit=limit,
        offset=offset,
    )
    return PendingActivityListResponse(
        activities=[PendingActivityResponse.model_validate(v) for v in views],
        limit=limit,
        offset=offset,
    )


# ── E9 screening review workspace ─────────────────────────────────────────

@router.get(
    "/{customer_id}/screening-review",
    response_model=ScreeningReviewListResponse,
    summary="List persisted screening-review checklist decisions",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
)
async def list_screening_review(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningReviewListResponse:
    items = await ScreeningReviewService(db).list_review_items(customer_id)
    return ScreeningReviewListResponse(
        customer_id=customer_id,
        items=[ScreeningReviewItemResponse.model_validate(item) for item in items],
    )


@router.put(
    "/{customer_id}/screening-review/{item_key}",
    response_model=ScreeningReviewItemResponse,
    summary="Record or update one screening-review checklist decision",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
    },
)
async def update_screening_review(
    customer_id: uuid.UUID,
    item_key: str,
    body: UpdateScreeningReviewItemRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE_OR_ADMIN)],
    db: AsyncSession = Depends(get_db),
) -> ScreeningReviewItemResponse:
    item = await ScreeningReviewService(db).upsert_review_item(
        customer_id,
        item_key=item_key,
        status=body.status,
        comment=body.comment,
        actor_id=str(current_user.id),
    )
    return ScreeningReviewItemResponse.model_validate(item)


@router.get(
    "/{customer_id}/bank-activity",
    response_model=BankActivityResponse,
    summary="List bank-linked suspicious-activity findings",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
    },
    description=(
        "E9 establishes the stable CRM contract for Surepass/Finpass-style "
        "bank monitoring. Until a provider feed is connected, this returns an "
        "empty, valid response instead of fabricated findings."
    ),
)
async def get_bank_activity(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> BankActivityResponse:
    findings = await ScreeningReviewService(db).list_bank_findings(customer_id)
    open_findings = sum(1 for finding in findings if finding.status == "OPEN")
    last_synced_at = max((finding.detected_at for finding in findings), default=None)
    return BankActivityResponse(
        customer_id=customer_id,
        connected_accounts=0,
        last_synced_at=last_synced_at,
        open_findings=open_findings,
        findings=[BankActivityFindingResponse.model_validate(finding) for finding in findings],
    )


__all__ = ["router"]
