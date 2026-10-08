"""Exporter CRM API routes.

Kept in a sibling file rather than added directly to `router.py`: at the time
these routes were built, `router.py` was already 277 lines covering the case
management state machine and the pre-backlog onboarding-foundation routes,
each documented with the same `summary`/`description`/`responses` verbosity
these nine new routes would need — appending them in place would have pushed
that file past 550 lines and mixed three unrelated route groups (case state
machine, onboarding foundation, exporter CRM) in one module. `router.py`
already groups its own routes with `# ── ─────` section banners rather than
splitting files, so this split is the exception, made because size crossed
the point worth checking, not because the
existing convention calls for one file per feature.

This module's `router` is mounted into `router.py`'s own `router` via
`include_router`, so it inherits the `/onboarding` prefix `app/api/rest/
router.py` applies to the whole module — routes are declared here with only
the `/exporters` prefix, matching the documented `/onboarding/exporters...`
paths once combined.

**Split by area.** This file now carries only the company routes. The contact and
activity routes moved to `engagement_router.py` and the screening-review and
bank-activity routes to `screening_router.py`. All three share the `/exporters` prefix
and the `Exporter CRM` tag and are mounted side by side in `router.py`, so no
path, operation or schema changed.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.actor_names import actor_names
from app.modules.onboarding.api.schemas.exporter import (
    AssignRelationshipManagerRequest,
    BringIntoPipelineRequest,
    CreateExporterProfileRequest,
    DuplicateGstinWarningResponse,
    ExporterProfileDetailResponse,
    ExporterProfileListItemResponse,
    ExporterProfileResponse,
    ExporterProfileSearchResponse,
    MarkerMoveResponse,
    SetMarkerRequest,
    UpdateExporterProfileRequest,
)
from app.modules.onboarding.api.schemas.masking import can_reveal_identifiers
from app.modules.onboarding.application import ExporterProfileService
from app.modules.onboarding.domain.assignment import (
    ASSIGN_RM,
    RM_ROLES,
    Permission,
    holds,
    may_set_relationship_manager,
)
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    CompanyTradeRole,
    ExporterJourney,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.exceptions import (
    IdentifierSearchNotPermittedError,
    RelationshipManagerAssignNotAllowedError,
)
from app.platform.authentication import staff_members
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import get_current_permissions, require_role
from app.platform.database.services import get_db
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

# Routine CRM reads and writes by internal staff (Relationship Managers are
# OPERATIONS, and may read every exporter). PAN/GSTIN/IEC and contact
# email/phone are masked per viewer in the response schemas.
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
#: Who may set or clear a marker — the roles `_STAFF` admits.
_MARKER_ROLES = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN})
# Masked CRM reads. DEVELOPER may read the CRM but never sees a raw
# identifier (`can_reveal_identifiers` is always False for it), per the role
# matrix in docs/architecture.md, "Roles and masking" (architecture §3.7).
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)
#: The signed-in user's permissions, for the "ADMIN or permission" rules.
_PERMISSIONS = Annotated[frozenset[Permission], Depends(get_current_permissions)]


def _reject_identifier_search(viewer: User, **filters: str | None) -> None:
    """Refuse an exact tax-identifier search filter from a role that may not
    see a raw identifier.

    Masking the response body is not enough on its own. `?pan=<full PAN>`
    matches exactly, so whether a row comes back answers "does a company with
    this PAN exist, and which one" however the bodies are rendered. DEVELOPER
    is read-only and never permitted to reveal an identifier, so it must not be
    able to ask the question either.

    The refusal is explicit and names every filter used, rather than silently
    returning nothing: an empty result is still an answer ("no such company"),
    and it would send anyone debugging a search looking for missing data.

    Callers pass the filters as keywords, so the parameter names in the error
    are the query-string names the caller actually sent.
    """
    if can_reveal_identifiers(viewer):
        return
    used = sorted(name for name, value in filters.items() if value is not None)
    if used:
        raise IdentifierSearchNotPermittedError(role=viewer.role.value, parameters=used)


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
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        409: {"description": "The PAN is already held by another company"},
        422: {"description": "Invalid request body"},
    },
)
async def create_exporter_profile(
    body: CreateExporterProfileRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
    response: Response,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExporterProfileResponse:
    # An RM named on create is checked before anything is written, so a refusal
    # leaves no company behind; it is set once the company exists.
    rm_user_id = body.relationship_manager_user_id
    if rm_user_id is not None:
        if not may_set_relationship_manager(
            actor_id=str(current_user.id),
            actor_role=current_user.role,
            actor_permissions=permissions,
            current=None,
            target=str(rm_user_id),
        ):
            raise RelationshipManagerAssignNotAllowedError("(new)")
        await ExporterProfileService(db).require_eligible_relationship_manager(rm_user_id)

    # "Add Exporter": a name and country (the schema guarantees both or
    # neither) create a named company through `create_lead`, with the
    # signed-in user as the actor — never a field the caller supplies.
    if body.name is not None and body.country is not None:
        if idempotency_key is None:
            raise ValidationError(
                "Creating a named company (name supplied) requires an "
                "Idempotency-Key header"
            )
        service = ExporterProfileService(db)
        profile, created = await service.create_lead(
            name=body.name,
            country=body.country,
            idempotency_key=idempotency_key,
            source=body.source,
            customer_id=body.customer_id,
            cin=body.cin,
            gstins=body.gstins,
            pan=body.pan,
            iec=body.iec,
            industry=body.industry,
            export_markets=body.export_markets,
            products=body.products,
            year_established=body.year_established,
            registration_number=body.registration_number,
            actor_id=str(current_user.id),
        )
        if created and rm_user_id is not None:
            profile = await _claim_on_create(service, profile, rm_user_id, current_user, permissions)
        # `status_code=201` on the decorator is only the default — found via
        # manual end-to-end testing that neither this branch nor the one
        # below ever actually overrode it, contradicting this endpoint's own
        # documented 200-vs-201 `responses` contract above. A resubmitted
        # `Idempotency-Key` correctly returned the same resource both times;
        # it just always claimed "201 Created" while doing it.
        if not created:
            response.status_code = 200
        return await _company_response(db, service, profile, current_user, permissions)

    customer_id = body.customer_id or uuid.uuid4()
    service = ExporterProfileService(db)
    profile, created = await service.create_or_get_profile(
        customer_id,
        source=body.source,
        cin=body.cin,
        gstins=body.gstins,
        pan=body.pan,
        iec=body.iec,
        industry=body.industry,
        export_markets=body.export_markets,
        products=body.products,
        year_established=body.year_established,
        registration_number=body.registration_number,
        idempotency_key=idempotency_key,
        actor_id=str(current_user.id),
    )
    if created and rm_user_id is not None:
        profile = await _claim_on_create(service, profile, rm_user_id, current_user, permissions)
    if not created:
        response.status_code = 200
    return await _company_response(db, service, profile, current_user, permissions)


@router.get(
    "/{customer_id}",
    response_model=ExporterProfileDetailResponse,
    summary="Read an exporter profile's full detail",
    description=(
        "The company record with its name and country, plus its contacts and "
        "recent activities."
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
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileDetailResponse:
    detail = await ExporterProfileService(db).get_profile_detail(customer_id)
    response = ExporterProfileDetailResponse.from_detail(detail).masked_for(current_user)
    response.allowed_marker_moves = _marker_moves(detail.marker, current_user)
    await _name_relationship_managers(db, current_user, [response])
    response.relationship_manager_actions = _rm_actions(
        current_user, permissions, detail.relationship_manager_user_id
    )
    names = await actor_names(db, current_user, (a.actor_id for a in response.recent_activities))
    response.recent_activities = [a.named(names) for a in response.recent_activities]
    return response


@router.patch(
    "/{customer_id}",
    response_model=ExporterProfileResponse,
    summary="Update an exporter profile's mutable CRM fields",
    description=(
        "Updates CRM fields. A field left out of the body is unchanged; a field "
        "sent as null (or an empty string or list) is cleared. Each change is "
        "recorded in the company's history with the signed-in user as the actor. "
        "`source`, `journey`, `qualification` and the marker are not accepted "
        "here (422 if present): source is immutable, and each of the others has "
        "its own write path. The relationship manager is not either: it has its "
        "own route.\n\n"
        "Send `seen` — each edited field's value as the screen showed it — and an "
        "edit to a field someone else has changed since is refused (409 "
        "`COMPANY_FIELD_CHANGED`, naming who and when) instead of overwriting it. "
        "A masked identifier is compared masked."
    ),
    responses={
        200: {"model": ExporterProfileResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Exporter profile not found"},
        409: {"description": "`COMPANY_FIELD_CHANGED` — a field changed since it was loaded"},
        422: {"description": "Invalid request body"},
    },
)
async def update_exporter_profile(
    customer_id: uuid.UUID,
    body: UpdateExporterProfileRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileResponse:
    # `exclude_unset` is what separates "left out" (no change) from "sent as
    # null" (clear). The actor is the session's, never the body's.
    changes = body.model_dump(exclude_unset=True)
    seen = changes.pop("seen", None)
    service = ExporterProfileService(db)
    profile = await service.update_profile(
        customer_id,
        changes,
        actor_id=str(current_user.id),
        seen=seen,
        viewer_can_reveal=can_reveal_identifiers(current_user),
    )
    return await _company_response(db, service, profile, current_user, permissions)


@router.get(
    "",
    response_model=ExporterProfileSearchResponse,
    summary="Search exporter profiles",
    description=(
        "Filters by gstin, pan, iec, source, journey, qualification, marker, "
        "pipeline_status (exact match) and name (case-insensitive partial match "
        "on the company's name). ENDED companies are left out of the default "
        "working list: with no marker filter and no search term (name, gstin, "
        "pan, iec) they are excluded; any search term includes them; "
        "marker=ENDED lists only them. Companies that are NOT_IN_PIPELINE — a "
        "company that exists only because it was somebody's buyer — follow the "
        "same rule: excluded by default, found by any search term, and listed on "
        "their own with pipeline_status=NOT_IN_PIPELINE. The gstin/pan/iec filters are "
        "COMPLIANCE/ADMIN only: an exact match on a tax identifier reveals "
        "which company holds it even when the response body is masked.\n\n"
        "`relationship_manager` narrows the list by owner: `me` (My companies), "
        "`none` (Unassigned), `inactive` (an RM whose account is deactivated) or a "
        "user id. It is a filter only: ownership never changes what a reader may see."
    ),
    responses={
        200: {"model": ExporterProfileSearchResponse},
        401: {"description": "Unauthorized"},
        403: {
            "description": (
                "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required; or the "
                "caller used a gstin/pan/iec filter and may not see raw identifiers"
            )
        },
    },
)
async def search_exporter_profiles(
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
    gstin: str | None = Query(default=None),
    pan: str | None = Query(default=None),
    iec: str | None = Query(default=None),
    name: str | None = Query(default=None),
    source: ExporterSource | None = Query(default=None),
    journey: ExporterJourney | None = Query(default=None),
    qualification: QualificationState | None = Query(default=None),
    marker: ExporterMarker | None = Query(default=None),
    pipeline_status: CompanyPipelineStatus | None = Query(default=None),
    country: str | None = Query(
        default=None, description="ISO country code; matched whole, case-insensitively."
    ),
    industry: str | None = Query(
        default=None, description="Matched as a partial, case-insensitive substring."
    ),
    background_check: BackgroundCheckState | None = Query(default=None),
    trade_role: CompanyTradeRole | None = Query(
        default=None,
        description=(
            "Which side of a trade the company has been on, by participation rather than "
            "by how the record was created. BOTH means it has been on both sides. Asking "
            "for BUYER includes buyer-only companies, which the default list hides."
        ),
    ),
    has_open_deals: bool | None = Query(
        default=None,
        description="Whether the company has a deal that is neither handed over nor withdrawn.",
    ),
    relationship_manager: str | None = Query(
        default=None, description="`me`, `none`, `inactive` or a user id"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ExporterProfileSearchResponse:
    _reject_identifier_search(current_user, gstin=gstin, pan=pan, iec=iec)
    rm_user_id: uuid.UUID | None = None
    rm_filter = (relationship_manager or "").strip().lower() or None
    if rm_filter == "me":
        rm_user_id = current_user.id
    elif rm_filter not in (None, "none", "inactive"):
        try:
            rm_user_id = uuid.UUID(rm_filter)
        except ValueError as exc:
            raise ValidationError(
                "relationship_manager must be `me`, `none`, `inactive` or a user id"
            ) from exc

    items = await ExporterProfileService(db).search_profiles(
        gstin=gstin,
        pan=pan,
        iec=iec,
        name_contains=name,
        source=source,
        journey=journey,
        qualification=qualification,
        marker=marker,
        pipeline_status=pipeline_status,
        country=country,
        industry=industry,
        background_check=background_check,
        trade_role=trade_role,
        has_open_deals=has_open_deals,
        relationship_manager_user_id=rm_user_id,
        relationship_manager_unassigned=rm_filter == "none",
        relationship_manager_inactive=rm_filter == "inactive",
        limit=limit,
        offset=offset,
    )
    profiles = [
        ExporterProfileListItemResponse.model_validate(item).masked_for(current_user)
        for item in items
    ]
    await _name_relationship_managers(db, current_user, profiles)
    # The number behind the page, so a screen can say "185" rather than counting the
    # rows it happens to hold.
    total = await ExporterProfileService(db).count_profiles(
        gstin=gstin,
        pan=pan,
        iec=iec,
        name_contains=name,
        source=source,
        journey=journey,
        qualification=qualification,
        marker=marker,
        pipeline_status=pipeline_status,
        country=country,
        industry=industry,
        background_check=background_check,
        trade_role=trade_role,
        has_open_deals=has_open_deals,
        relationship_manager_user_id=rm_user_id,
        relationship_manager_unassigned=rm_filter == "none",
        relationship_manager_inactive=rm_filter == "inactive",
    )
    return ExporterProfileSearchResponse(
        profiles=profiles, limit=limit, offset=offset, total=total
    )


# ── Marker (PAUSED / ENDED) ──────────────────────────────────────────────


@router.post(
    "/{customer_id}/marker",
    response_model=ExporterProfileResponse,
    summary="Set or clear a company's PAUSED / ENDED marker",
    description=(
        "A commercial pause or ending, recorded beside the journey and never "
        "instead of it: the journey does not move. PAUSED and ENDED need a "
        "reason; clearing to NONE does not. ENDED -> PAUSED is not a move "
        "(clear first), and a move to the current value is refused. Every "
        "change is recorded in the company's history with the signed-in user."
    ),
    responses={
        200: {"model": ExporterProfileResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Exporter profile not found"},
        409: {"description": "Marker move not allowed"},
        422: {"description": "Invalid request body, or a PAUSED/ENDED marker without a reason"},
    },
)
async def set_exporter_marker(
    customer_id: uuid.UUID,
    body: SetMarkerRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileResponse:
    profile = await ExporterProfileService(db).set_marker(
        customer_id, body.marker, reason=body.reason, actor_id=str(current_user.id)
    )
    response = ExporterProfileResponse.model_validate(profile).masked_for(current_user)
    response.allowed_marker_moves = _marker_moves(profile.marker, current_user)
    await _name_relationship_managers(db, current_user, [response])
    return response


# ── Into the sales pipeline ──────────────────────────────────────────────


@router.post(
    "/{customer_id}/pipeline",
    response_model=ExporterProfileResponse,
    summary="Bring a buyer-only company into the sales pipeline",
    description=(
        "A company that exists only because it was somebody's buyer is "
        "NOT_IN_PIPELINE: nobody is selling to it, so it is kept out of the "
        "working list and out of pipeline counts, and qualification and the "
        "conversation gauge refuse it. This is the one way in. It sets "
        "pipeline_status to IN_PIPELINE and starts the company's journey "
        "history at LEAD — from then on it is an ordinary lead. "
        "A reason is optional and recorded on the history row. "
        "Deciding to sell to a company is a commercial decision, so this is "
        "OPERATIONS, COMPLIANCE or ADMIN; a company already in the pipeline is "
        "a 409, because there is nothing to do."
    ),
    responses={
        200: {"model": ExporterProfileResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Exporter profile not found"},
        409: {"description": "The company is already in the sales pipeline"},
    },
)
async def bring_exporter_into_pipeline(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
    body: BringIntoPipelineRequest | None = None,
) -> ExporterProfileResponse:
    service = ExporterProfileService(db)
    profile = await service.bring_into_pipeline(
        customer_id,
        reason=body.reason if body is not None else None,
        actor_id=str(current_user.id),
    )
    return await _company_response(db, service, profile, current_user, permissions)


# ── Relationship manager ─────────────────────────────────────────────────


@router.post(
    "/{customer_id}/relationship-manager",
    response_model=ExporterProfileDetailResponse,
    summary="Set, change or clear a company's relationship manager",
    description=(
        "The RM is one active RM (OPERATIONS) user. An RM may claim a company with "
        "no RM for themselves. Naming someone else, or changing or clearing an RM "
        "already set, needs ADMIN or `exporters:assign_rm`, and a change or clear "
        "needs a reason. `seen_user_id` is the RM the screen showed (`null` for "
        "none): a different current RM refuses the request (409) instead of "
        "overwriting someone else's change. Every change is a `relationship_manager` "
        "history row. Ownership grants nothing: it never unmasks an identifier and "
        "never changes what anyone may see."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {
            "description": (
                "OPERATIONS, COMPLIANCE or ADMIN role required; "
                "`RELATIONSHIP_MANAGER_ASSIGN_NOT_ALLOWED`"
            )
        },
        404: {"description": "Exporter profile not found"},
        409: {"description": "`RELATIONSHIP_MANAGER_CHANGED` — someone changed it since"},
        422: {
            "description": (
                "`RELATIONSHIP_MANAGER_NOT_ELIGIBLE` — not an active RM user; "
                "`RELATIONSHIP_MANAGER_REASON_REQUIRED`"
            )
        },
    },
)
async def assign_exporter_relationship_manager(
    customer_id: uuid.UUID,
    body: AssignRelationshipManagerRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileDetailResponse:
    service = ExporterProfileService(db)
    await service.assign_relationship_manager(
        customer_id,
        user_id=body.user_id,
        reason=body.reason,
        seen_user_id=body.seen_user_id,
        actor_id=str(current_user.id),
        actor_role=current_user.role,
        actor_permissions=permissions,
    )
    return await get_exporter_profile_detail(customer_id, current_user, permissions, db)


async def _claim_on_create(
    service: ExporterProfileService,
    profile: ExporterProfile,
    rm_user_id: uuid.UUID,
    viewer: User,
    permissions: frozenset[Permission],
) -> ExporterProfile:
    """Set the RM named on create, once the company exists."""
    return await service.assign_relationship_manager(
        profile.customer_id,
        user_id=rm_user_id,
        reason=None,
        seen_user_id=None,
        actor_id=str(viewer.id),
        actor_role=viewer.role,
        actor_permissions=permissions,
    )


def _rm_actions(
    viewer: User, permissions: frozenset[Permission], current: uuid.UUID | None
) -> list[str]:
    """What this viewer may do with the company's RM — the service's own rule."""
    may_assign = holds(viewer.role, permissions, ASSIGN_RM)
    if current is None:
        actions = ["CLAIM"] if viewer.role in RM_ROLES else []
        return [*actions, "ASSIGN"] if may_assign else actions
    return ["CHANGE", "CLEAR"] if may_assign else []


async def _name_relationship_managers(db: AsyncSession, viewer: User, responses) -> None:
    """Fill each response's RM name and whether that account is deactivated."""
    ids = [
        str(r.relationship_manager_user_id)
        for r in responses
        if r.relationship_manager_user_id is not None
    ]
    if not ids:
        return
    names = await actor_names(db, viewer, ids)
    members = await staff_members(db, ids)
    for response in responses:
        if response.relationship_manager_user_id is None:
            continue
        key = str(response.relationship_manager_user_id)
        response.relationship_manager_name = names.get(key)
        member = members.get(key)
        response.relationship_manager_inactive = member is None or not member.is_active


async def _company_response(
    db: AsyncSession,
    service: ExporterProfileService,
    profile: ExporterProfile,
    viewer: User,
    permissions: frozenset[Permission] = frozenset(),
) -> ExporterProfileResponse:
    """A company as a create or edit returns it, with a warning for each of
    its GSTINs another company also holds (decision 4: warn, never refuse)."""
    warnings = await service.duplicate_gstin_warnings(profile.customer_id, profile.gstins)
    response = ExporterProfileResponse.model_validate(profile)
    response.gstin_warnings = [
        DuplicateGstinWarningResponse.model_validate(w, from_attributes=True) for w in warnings
    ]
    response = response.masked_for(viewer)
    response.allowed_marker_moves = _marker_moves(profile.marker, viewer)
    await _name_relationship_managers(db, viewer, [response])
    return response


def _marker_moves(current: ExporterMarker, viewer: User) -> list[MarkerMoveResponse]:
    """The marker moves this viewer may make now: the service's own table,
    and none at all for a role the marker route refuses."""
    if viewer.role not in _MARKER_ROLES:
        return []
    return [
        MarkerMoveResponse(to=to_marker, reason_required=needs_reason)
        for to_marker, needs_reason in ExporterProfileService.allowed_marker_moves(current)
    ]


__all__ = ["router"]
