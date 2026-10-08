"""Parent and child companies.

* **Read the group** — every CRM reader (`exporters:view`). Each member's background
  check and risk are served only to a reader of compliance work (`compliance:view`);
  for anyone else they are `null`, as on the company itself.
* **Link or unlink** a parent — `exporters:edit`. A loop is refused (422).
* **Possible members** — companies sharing a beneficial owner with this one, named by
  person, so `compliance:view` (staff); never linked automatically.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.company_group_service import (
    CompanyGroup,
    CompanyGroupService,
)
from app.platform.authentication.models import User
from app.platform.authorization.services import has_permission, require_permission
from app.platform.database.services import get_db

router = APIRouter(prefix="/exporters", tags=["Exporter CRM"])

_COMPANY_VIEW = require_permission("exporters", "view")
_COMPANY_EDIT = require_permission("exporters", "edit")
_COMPLIANCE_VIEW = require_permission("compliance", "view")

GroupRelationship = Literal["SUBSIDIARY", "BRANCH_OFFICE", "GROUP_COMPANY", "JOINT_VENTURE"]


class GroupMemberResponse(BaseModel):
    company_id: uuid.UUID
    name: str | None
    parent_company_id: uuid.UUID | None
    group_relationship: GroupRelationship | None
    #: 0 for the ultimate parent, 1 for its children, and so on.
    depth: int
    journey: str
    background_check: str | None
    risk_rating: str | None
    open_deals: int
    #: Open deals' value by currency, e.g. `{"USD": "125000.00"}`.
    open_deal_value: dict[str, Decimal]


class CompanyGroupResponse(BaseModel):
    company_id: uuid.UUID
    ultimate_parent_id: uuid.UUID
    members: list[GroupMemberResponse]


class SetParentCompanyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The parent, or `null` to take the company out of its group.
    parent_company_id: uuid.UUID | None
    relationship: GroupRelationship | None = None


class GroupSuggestionResponse(BaseModel):
    company_id: uuid.UUID
    name: str | None
    shared_people: list[str]


class GroupSuggestionListResponse(BaseModel):
    suggestions: list[GroupSuggestionResponse]


def _response(group: CompanyGroup, viewer: User) -> CompanyGroupResponse:
    sees_compliance = has_permission(viewer, "compliance", "view")
    return CompanyGroupResponse(
        company_id=group.company_id,
        ultimate_parent_id=group.ultimate_parent_id,
        members=[
            GroupMemberResponse(
                company_id=m.company_id,
                name=m.name,
                parent_company_id=m.parent_company_id,
                group_relationship=m.group_relationship,  # type: ignore[arg-type]
                depth=m.depth,
                journey=m.journey,
                background_check=m.background_check if sees_compliance else None,
                risk_rating=m.risk_rating if sees_compliance else None,
                open_deals=m.open_deals,
                open_deal_value=m.open_deal_value,
            )
            for m in group.members
        ],
    )


@router.get(
    "/{company_id}/group",
    response_model=CompanyGroupResponse,
    summary="The group a company belongs to",
    description=(
        "The whole tree from the ultimate parent (worked out, never stored) down, each "
        "member with its stage, background check and risk (for readers of compliance "
        "work), open deals and their value by currency. A company in no group is a "
        "group of one."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:view` permission required"},
        404: {"description": "Company not found"},
    },
)
async def get_company_group(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPANY_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> CompanyGroupResponse:
    return _response(await CompanyGroupService(db).group(company_id), current_user)


@router.put(
    "/{company_id}/parent",
    response_model=CompanyGroupResponse,
    summary="Put a company under a parent, or take it out of its group",
    description=(
        "`relationship` is required with a parent. A link that would make a company its "
        "own ancestor is refused (422). Every change is a `group` history row on the "
        "company and on each parent involved."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:edit` permission required"},
        404: {"description": "Company or parent not found"},
        422: {"description": "A loop, the company itself, or no relationship"},
    },
)
async def set_parent_company(
    company_id: uuid.UUID,
    body: SetParentCompanyRequest,
    current_user: Annotated[User, Depends(_COMPANY_EDIT)],
    db: AsyncSession = Depends(get_db),
) -> CompanyGroupResponse:
    service = CompanyGroupService(db)
    await service.set_parent(
        company_id,
        parent_id=body.parent_company_id,
        relationship=body.relationship,
        actor_id=str(current_user.id),
    )
    return _response(await service.group(company_id), current_user)


@router.get(
    "/{company_id}/group/suggestions",
    response_model=GroupSuggestionListResponse,
    summary="Companies that may belong to the same group",
    description=(
        "Companies outside this one's group that record a beneficial owner with the same "
        "name (and date of birth, where both hold one). Suggestions only: nothing is "
        "linked until someone links it."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`compliance:view` permission required"},
        404: {"description": "Company not found"},
    },
)
async def list_group_suggestions(
    company_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPLIANCE_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> GroupSuggestionListResponse:
    suggestions = await CompanyGroupService(db).suggestions(company_id)
    return GroupSuggestionListResponse(
        suggestions=[
            GroupSuggestionResponse(
                company_id=s.company_id, name=s.name, shared_people=s.shared_people
            )
            for s in suggestions
        ]
    )
