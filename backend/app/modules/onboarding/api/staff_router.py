"""Who can be given work: the staff picker, and moving one RM's companies to another.

The user list (`/auth/users`) is user management's and needs `users:view`, which most
staff do not hold. Assigning a relationship manager or a reviewer needs only to know who
is active in the right role, so this serves exactly that — id, name, role and how much
each person already holds — and nothing else about an account.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.exporter import (
    BulkCollectorReassignRequest,
    BulkCollectorReassignResponse,
    BulkReassignRequest,
    BulkReassignResponse,
    StaffListResponse,
    StaffMemberResponse,
)
from app.modules.onboarding.application import ExporterProfileService
from app.modules.onboarding.application.collections_owner_service import (
    CollectionsOwnerService,
)
from app.modules.onboarding.domain.assignment import Permission
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication import active_staff
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import get_current_permissions, require_permission
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

_ASSIGN_RM = require_permission("exporters", "assign_rm")
_ASSIGN_COLLECTOR = require_permission("exporters", "assign_collector")
_COMPANY_EDIT = require_permission("exporters", "edit")

_PERMISSIONS = Annotated[frozenset[Permission], Depends(get_current_permissions)]

#: The roles a picker may ask for: relationship managers, and reviewers. Never the
#: administrator, who is neither.
_PICKABLE = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE})


@router.get(
    "/staff",
    response_model=StaffListResponse,
    summary="Active staff in a role, for an assignment picker",
    description=(
        "Every **active** account in the given role(s), by name: `role=OPERATIONS` for "
        "the relationship-manager picker, `role=COMPLIANCE` for the reviewer picker. "
        "Each carries how many companies it is RM of and how many reviews it holds, so "
        "work can be spread. Never an email, password or custom role. Needs "
        "`exporters:edit`; DEVELOPER and the administrator are refused (they assign "
        "nothing)."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "exporters:edit permission required"},
    },
)
async def list_assignable_staff(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_COMPANY_EDIT)],
    role: Annotated[list[UserRole], Query()] = [UserRole.OPERATIONS],  # noqa: B006
) -> StaffListResponse:
    wanted = [r for r in role if r in _PICKABLE]
    members = await active_staff(db, wanted)
    ids = [m.id for m in members]
    companies: dict[str, int] = {}
    reviews: dict[str, int] = {}
    if ids:
        rm_rows = await db.execute(
            select(ExporterProfile.relationship_manager_user_id, func.count())
            .where(
                ExporterProfile.relationship_manager_user_id.in_([uuid.UUID(i) for i in ids])
            )
            .group_by(ExporterProfile.relationship_manager_user_id)
        )
        companies = {str(user_id): count for user_id, count in rm_rows}
        review_rows = await db.execute(
            select(ExporterProfile.background_check_reviewer_id, func.count())
            .where(ExporterProfile.background_check_reviewer_id.in_(ids))
            .group_by(ExporterProfile.background_check_reviewer_id)
        )
        reviews = {str(user_id): count for user_id, count in review_rows}
    return StaffListResponse(
        staff=[
            StaffMemberResponse(
                id=m.id,
                name=m.name,
                role=m.role.value,
                companies=companies.get(m.id, 0),
                open_reviews=reviews.get(m.id, 0),
            )
            for m in members
        ]
    )


@router.post(
    "/relationship-managers/reassign",
    response_model=BulkReassignResponse,
    summary="Move one relationship manager's companies to another",
    description=(
        "All of `from_user_id`'s companies, or those listed in `company_ids`, or those "
        "at one `journey` stage, to `to_user_id` — an active RM user. ADMIN or "
        "`exporters:assign_rm`; a reason always. Companies are locked in id order and "
        "re-read under the lock: one whose RM changed meanwhile is skipped, not "
        "overwritten. One `relationship_manager` history row per company, all sharing "
        "`bulk_run_id`. `dry_run` reports what would move and writes nothing. Use it "
        "when someone leaves: the companies of a deactivated RM are listed by "
        "`GET /exporters?relationship_manager=inactive`."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`RELATIONSHIP_MANAGER_ASSIGN_NOT_ALLOWED`"},
        422: {
            "description": (
                "`RELATIONSHIP_MANAGER_NOT_ELIGIBLE` — the target is not an active RM "
                "user; `RELATIONSHIP_MANAGER_REASON_REQUIRED`; or the same RM twice"
            )
        },
    },
)
async def reassign_relationship_managers(
    body: BulkReassignRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_ASSIGN_RM)],
    permissions: _PERMISSIONS,
) -> BulkReassignResponse:
    result = await ExporterProfileService(db).reassign_relationship_managers(
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        company_ids=body.company_ids,
        journey=body.journey,
        reason=body.reason,
        dry_run=body.dry_run,
        actor_id=str(user.id),
        actor_role=user.role,
        actor_permissions=permissions,
    )
    return BulkReassignResponse(
        bulk_run_id=result.run_id,
        dry_run=result.dry_run,
        matched=len(result.matched),
        moved=len(result.moved),
        skipped=len(result.skipped),
        company_ids=list(result.matched if result.dry_run else result.moved),
        skipped_company_ids=list(result.skipped),
    )


@router.post(
    "/collections-owners/reassign",
    response_model=BulkCollectorReassignResponse,
    summary="Move one collections owner's companies to another",
    description=(
        "All of `from_user_id`'s companies, or those in `company_ids`, to `to_user_id`. "
        "Needs `exporters:assign_collector` and a reason. A company whose owner "
        "changed meanwhile is skipped. One history row per company, sharing "
        "`bulk_run_id`; `dry_run` writes nothing."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:assign_collector` permission required"},
        422: {"description": "Not an active staff user, no reason, or the same owner twice"},
    },
)
async def reassign_collections_owners(
    body: BulkCollectorReassignRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(_ASSIGN_COLLECTOR)],
    permissions: _PERMISSIONS,
) -> BulkCollectorReassignResponse:
    result = await CollectionsOwnerService(db).reassign(
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        company_ids=body.company_ids,
        reason=body.reason,
        dry_run=body.dry_run,
        actor_id=str(current_user.id),
        actor_permissions=permissions,
    )
    return BulkCollectorReassignResponse(
        bulk_run_id=result.run_id,
        dry_run=result.dry_run,
        matched=len(result.matched),
        moved=len(result.moved),
        skipped=len(result.skipped),
        company_ids=list(result.matched if result.dry_run else result.moved),
        skipped_company_ids=list(result.skipped),
    )


__all__ = ["router"]
