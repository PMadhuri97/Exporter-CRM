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

**Split by owner (L2-01).** This file now carries only the company routes
(Developer 2). The contact and activity routes moved to `engagement_router.py`
(Developer 3) and the screening-review and bank-activity routes to
`screening_router.py` (Developer 4). All three share the `/exporters` prefix
and the `Exporter CRM` tag and are mounted side by side in `router.py`, so no
path, operation or schema changed.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.exporter import (
    CreateExporterProfileRequest,
    DuplicateGstinWarningResponse,
    ExporterProfileDetailResponse,
    ExporterProfileListItemResponse,
    ExporterProfileResponse,
    ExporterProfileSearchResponse,
    SetMarkerRequest,
    TransitionLifecycleStatusRequest,
    UpdateExporterProfileRequest,
)
from app.modules.onboarding.api.schemas.masking import can_reveal_identifiers
from app.modules.onboarding.application import ExporterProfileService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterLifecycleStatus,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.exceptions import IdentifierSearchNotPermittedError
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

# Lifecycle moves are gated per edge in the service
# (`COMPLIANCE_GATED_FROM_STATUSES`), so RMs can still work the sales stages;
# the router only admits staff.
#
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
    # "Add Exporter": a name and country (the schema guarantees both or
    # neither) create a named company through `create_lead`. The contact the
    # legacy identity store needs is the signed-in user's own address, never a
    # field the caller supplies.
    if body.name is not None:
        assert body.country is not None
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
        return await _company_response(service, profile, current_user)

    customer_id = body.customer_id or uuid.uuid4()
    service = ExporterProfileService(db)
    profile, created = await service.create_or_get_profile(
        customer_id,
        source=body.source,
        lifecycle_status=body.lifecycle_status,
        cin=body.cin,
        gstins=body.gstins,
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
    return await _company_response(service, profile, current_user)


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
    db: AsyncSession = Depends(get_db),
) -> ExporterProfileDetailResponse:
    detail = await ExporterProfileService(db).get_profile_detail(customer_id)
    return ExporterProfileDetailResponse.from_detail(detail).masked_for(current_user)


@router.patch(
    "/{customer_id}",
    response_model=ExporterProfileResponse,
    summary="Update an exporter profile's mutable CRM fields",
    description=(
        "Updates CRM fields. A field left out of the body is unchanged; a field "
        "sent as null (or an empty string or list) is cleared. Each change is "
        "recorded in the company's history with the signed-in user as the actor. "
        "`source` and `lifecycle_status` are not accepted here "
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
    # `exclude_unset` is what separates "left out" (no change) from "sent as
    # null" (clear). The actor is the session's, never the body's.
    service = ExporterProfileService(db)
    profile = await service.update_profile(
        customer_id,
        body.model_dump(exclude_unset=True),
        actor_id=str(current_user.id),
    )
    return await _company_response(service, profile, current_user)


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
        "Filters by gstin, pan, iec, source, lifecycle status, marker (exact "
        "match) and name (case-insensitive partial match on the company's "
        "name). ENDED companies are left out of the default working list: "
        "with no marker filter and no search term (name, gstin, pan, iec) they "
        "are excluded; any search term includes them; marker=ENDED lists only "
        "them. The gstin/pan/iec filters are "
        "COMPLIANCE/ADMIN only: an exact match on a tax identifier reveals "
        "which company holds it even when the response body is masked."
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
    status: ExporterLifecycleStatus | None = Query(default=None),
    journey: ExporterJourney | None = Query(default=None),
    qualification: QualificationState | None = Query(default=None),
    marker: ExporterMarker | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ExporterProfileSearchResponse:
    _reject_identifier_search(current_user, gstin=gstin, pan=pan, iec=iec)

    items = await ExporterProfileService(db).search_profiles(
        gstin=gstin,
        pan=pan,
        iec=iec,
        name_contains=name,
        source=source,
        lifecycle_status=status,
        journey=journey,
        qualification=qualification,
        marker=marker,
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
    return ExporterProfileResponse.model_validate(profile).masked_for(current_user)


async def _company_response(
    service: ExporterProfileService, profile: ExporterProfile, viewer: User
) -> ExporterProfileResponse:
    """A company as a create or edit returns it, with a warning for each of
    its GSTINs another company also holds (decision 4: warn, never refuse)."""
    warnings = await service.duplicate_gstin_warnings(profile.customer_id, profile.gstins)
    response = ExporterProfileResponse.model_validate(profile)
    response.gstin_warnings = [
        DuplicateGstinWarningResponse.model_validate(w, from_attributes=True) for w in warnings
    ]
    return response.masked_for(viewer)


__all__ = ["router"]
