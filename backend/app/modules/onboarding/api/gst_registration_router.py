"""GST registration routes.

A GST registration is a branch (``domain/entities/exporter_gstin.py``). Reading and
adding one is a company sub-resource, so those paths sit under
``/exporters/{customer_id}/gst-registrations``; flagging one is about the
registration itself and takes only its id, because a registration belongs to exactly
one company and a path carrying both would admit a request whose halves disagree.

Who may do what, and why
------------------------
* **Read** — every CRM reader, with the GSTIN masked per role as it is everywhere
  else.
* **Add** and **deactivate** — ``STAFF``. Which branches a company trades through is
  a record a relationship manager keeps.
* **Flag** and **unflag** — **COMPLIANCE and ADMIN only**. A flag blocks
  handovers for every deal invoiced through that branch, so it is a
  compliance decision, not a sales one. This is the one place in these routes where
  OPERATIONS is refused.

There is no delete route, by design: ``trg_exporter_gstin_no_delete`` refuses the
operation and ``deactivate`` is what replaces it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.gst_registration import (
    AddGstRegistrationRequest,
    DeactivateGstRegistrationRequest,
    FlagGstRegistrationRequest,
    GstRegistrationListResponse,
    GstRegistrationResponse,
    withholds_branch_flags,
)
from app.modules.onboarding.application.gst_registration_service import (
    GstRegistrationService,
)
from app.modules.onboarding.domain.entities.exporter_enums import GstRegistrationFlag
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)
_STAFF = require_role(UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN)
#: A flag stops trade. Compliance's decision, never sales'.
_COMPLIANCE = require_role(UserRole.COMPLIANCE, UserRole.ADMIN)


def _response(registration, viewer: User, *, also_held_by=()) -> GstRegistrationResponse:
    response = GstRegistrationResponse.model_validate(registration)
    response.also_held_by = list(also_held_by)
    return response.masked_for(viewer)


@router.get(
    "/exporters/{customer_id}/gst-registrations",
    response_model=GstRegistrationListResponse,
    summary="A company's GST registrations (its branches)",
    description=(
        "Newest last, **including deactivated ones**: a deactivated branch is how a "
        "deal handed over through it is explained, and `active` tells them apart.\n\n"
        "`state_code` and `state_name` are derived from each GSTIN, never entered. "
        "The GSTIN is masked for OPERATIONS and DEVELOPER, and `verify_url` — the "
        "GST portal's page for that GSTIN — is served only to a role that sees the "
        "full value, because the link contains it.\n\n"
        "`flagged_count` is how many active branches compliance has flagged, which "
        "is what the company page's warning chip shows.\n\n"
        "DEVELOPER is not served flags: `flag_status`, `flag_reason` and "
        "`flagged_count` are `null` for that role."
    ),
    responses={
        200: {"model": GstRegistrationListResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "CRM read role required"},
    },
)
async def list_gst_registrations(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_READER)],
    db: AsyncSession = Depends(get_db),
) -> GstRegistrationListResponse:
    registrations = await GstRegistrationService(db).list_for_company(customer_id)
    flagged_count = (
        None
        if withholds_branch_flags(current_user)
        else sum(
            1
            for r in registrations
            if r.active and r.flag_status is GstRegistrationFlag.FLAGGED
        )
    )
    return GstRegistrationListResponse(
        registrations=[_response(r, current_user) for r in registrations],
        flagged_count=flagged_count,
    )


@router.post(
    "/exporters/{customer_id}/gst-registrations",
    response_model=GstRegistrationResponse,
    status_code=201,
    summary="Record a GST registration for a company",
    description=(
        "The GSTIN must carry the company's PAN in characters 3–12, the same rule "
        "every other write path applies. The state is derived from the GSTIN and is "
        "not accepted here.\n\n"
        "A GSTIN this company **deactivated** earlier reactivates that row rather "
        "than adding a second one, so there is one row per company and GSTIN "
        "forever — which keeps a handed-over deal's invoicing branch pointing at the "
        "branch it really used. Re-adding an **active** one is a 409.\n\n"
        "A GSTIN another company also holds is **allowed** and reported in "
        "`also_held_by` (duplicates stay warn-only), never refused."
    ),
    responses={
        201: {"model": GstRegistrationResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "Company not found"},
        409: {"description": "The company already holds this GSTIN, active"},
        422: {
            "description": (
                "A malformed GSTIN, or one that does not carry the company's PAN"
            )
        },
    },
)
async def add_gst_registration(
    customer_id: uuid.UUID,
    body: AddGstRegistrationRequest,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
) -> GstRegistrationResponse:
    registration, others = await GstRegistrationService(db).add(
        customer_id,
        gstin=body.gstin,
        address=body.address,
        status=body.status,
        actor_id=str(current_user.id),
    )
    return _response(registration, current_user, also_held_by=others)


@router.post(
    "/gst-registrations/{registration_id}/deactivate",
    response_model=GstRegistrationResponse,
    summary="Stop using a branch, keeping its record",
    description=(
        "There is no delete: `trg_exporter_gstin_no_delete` refuses one, because a "
        "GST registration is a branch the company really traded through and a "
        "handed-over deal names the one it invoiced from. Deactivating removes it "
        "from the company's current GSTINs and from the branches a new deal may be "
        "invoiced through, and leaves the row readable.\n\n"
        "Deactivating an already-deactivated branch is a no-op, so a retry is not an "
        "error."
    ),
    responses={
        200: {"model": GstRegistrationResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "OPERATIONS, COMPLIANCE or ADMIN role required"},
        404: {"description": "GST registration not found"},
    },
)
async def deactivate_gst_registration(
    registration_id: uuid.UUID,
    current_user: Annotated[User, Depends(_STAFF)],
    db: AsyncSession = Depends(get_db),
    body: DeactivateGstRegistrationRequest | None = None,
) -> GstRegistrationResponse:
    registration = await GstRegistrationService(db).deactivate(
        registration_id,
        reason=body.reason if body is not None else None,
        actor_id=str(current_user.id),
    )
    return _response(registration, current_user)


@router.post(
    "/gst-registrations/{registration_id}/flag",
    response_model=GstRegistrationResponse,
    summary="Flag a branch (COMPLIANCE, ADMIN)",
    description=(
        "A reason is required: it is what a blocked handover will say, so without it "
        "whoever hits the block has nothing to act on.\n\n"
        "Flagging a branch blocks a handover for deals invoiced **through that "
        "branch** and leaves the company's other branches alone — a "
        "company trading through five states may have a problem in one of them.\n\n"
        "The flag belongs to **this** company's row. When another company holds the "
        "same GSTIN (allowed), `also_held_by` names it: that copy is "
        "**not** flagged, and whoever flags this one needs to know trade may still be "
        "running on the other."
    ),
    responses={
        200: {"model": GstRegistrationResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "GST registration not found"},
        422: {"description": "A flag without a reason"},
    },
)
async def flag_gst_registration(
    registration_id: uuid.UUID,
    body: FlagGstRegistrationRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE)],
    db: AsyncSession = Depends(get_db),
) -> GstRegistrationResponse:
    registration, others = await GstRegistrationService(db).flag(
        registration_id, reason=body.reason, actor_id=str(current_user.id)
    )
    return _response(registration, current_user, also_held_by=others)


@router.post(
    "/gst-registrations/{registration_id}/unflag",
    response_model=GstRegistrationResponse,
    summary="Lift a branch's flag (COMPLIANCE, ADMIN)",
    description=(
        "A reason is required here too: \"why we decided the problem is resolved\" is "
        "the half of the story a later reader needs most, and the flag's own reason "
        "is about to stop being readable on the row. Both reasons survive in the "
        "company's history."
    ),
    responses={
        200: {"model": GstRegistrationResponse},
        401: {"description": "Unauthorized"},
        403: {"description": "COMPLIANCE or ADMIN role required"},
        404: {"description": "GST registration not found"},
        422: {"description": "Lifting a flag without a reason"},
    },
)
async def unflag_gst_registration(
    registration_id: uuid.UUID,
    body: FlagGstRegistrationRequest,
    current_user: Annotated[User, Depends(_COMPLIANCE)],
    db: AsyncSession = Depends(get_db),
) -> GstRegistrationResponse:
    registration = await GstRegistrationService(db).unflag(
        registration_id, reason=body.reason, actor_id=str(current_user.id)
    )
    return _response(registration, current_user)
