"""A company's addresses.

Reading is every CRM reader's (`exporters:view`); adding, changing, choosing a default
and deactivating are `exporters:edit`. There is no delete: an address is deactivated,
and ``trg_company_address_no_delete`` refuses a delete anyway. Changing one address
takes only its id, because an address belongs to exactly one company.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.company_address import (
    AddCompanyAddressRequest,
    CompanyAddressListResponse,
    CompanyAddressResponse,
    DeactivateCompanyAddressRequest,
    UpdateCompanyAddressRequest,
)
from app.modules.onboarding.application.company_address_service import CompanyAddressService
from app.platform.authentication.models import User
from app.platform.authorization.services import require_permission
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

_COMPANY_VIEW = require_permission("exporters", "view")
_COMPANY_EDIT = require_permission("exporters", "edit")

_NOT_FOUND = {404: {"description": "No such address"}}


@router.get(
    "/exporters/{customer_id}/addresses",
    response_model=CompanyAddressListResponse,
    summary="A company's addresses",
    description=(
        "Active addresses first, by type with each type's default first; deactivated "
        "ones are included (`is_active`). `registered_changed_since_clear` says the "
        "default registered address was added or changed after the company's last "
        "Clear (`last_clear_at`)."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:view` permission required"},
        404: {"description": "Company not found"},
    },
)
async def list_company_addresses(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPANY_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> CompanyAddressListResponse:
    result = await CompanyAddressService(db).list_for_company(customer_id)
    return CompanyAddressListResponse(
        addresses=[CompanyAddressResponse.model_validate(a) for a in result.addresses],
        last_clear_at=result.last_clear_at,
        registered_changed_since_clear=result.registered_changed_since_clear,
    )


@router.post(
    "/exporters/{customer_id}/addresses",
    response_model=CompanyAddressResponse,
    status_code=201,
    summary="Add an address to a company",
    description=(
        "The first active address of a type becomes that type's default; "
        "`is_default=true` makes this one the default and demotes the old one. "
        "`gst_registration_id` links the new address to that GST registration "
        "(which must be this company's)."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:edit` permission required"},
        404: {"description": "Company, or GST registration, not found"},
        422: {"description": "Invalid address"},
    },
)
async def add_company_address(
    customer_id: uuid.UUID,
    body: AddCompanyAddressRequest,
    current_user: Annotated[User, Depends(_COMPANY_EDIT)],
    db: AsyncSession = Depends(get_db),
) -> CompanyAddressResponse:
    fields = body.model_dump(exclude={"is_default", "gst_registration_id"})
    fields["address_type"] = body.address_type.value
    address = await CompanyAddressService(db).add(
        customer_id,
        fields=fields,
        make_default=body.is_default,
        actor_id=str(current_user.id),
        gst_registration_id=body.gst_registration_id,
    )
    return CompanyAddressResponse.model_validate(address)


@router.patch(
    "/addresses/{address_id}",
    response_model=CompanyAddressResponse,
    summary="Change an address",
    description=(
        "A partial edit: only the fields sent change. A deactivated address cannot be "
        "changed. A default address moved to another type becomes that type's default."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:edit` permission required"},
        **_NOT_FOUND,
        422: {"description": "Invalid change, or the address is deactivated"},
    },
)
async def update_company_address(
    address_id: uuid.UUID,
    body: UpdateCompanyAddressRequest,
    current_user: Annotated[User, Depends(_COMPANY_EDIT)],
    db: AsyncSession = Depends(get_db),
) -> CompanyAddressResponse:
    changes = body.changes()
    if not changes:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body",),
                    "msg": "Send at least one field to change.",
                    "input": {},
                }
            ]
        )
    address = await CompanyAddressService(db).update(
        address_id, changes=changes, actor_id=str(current_user.id)
    )
    return CompanyAddressResponse.model_validate(address)


@router.post(
    "/addresses/{address_id}/default",
    response_model=CompanyAddressResponse,
    summary="Make an address its type's default",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:edit` permission required"},
        **_NOT_FOUND,
        422: {"description": "The address is deactivated"},
    },
)
async def set_default_company_address(
    address_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPANY_EDIT)],
    db: AsyncSession = Depends(get_db),
) -> CompanyAddressResponse:
    address = await CompanyAddressService(db).set_default(
        address_id, actor_id=str(current_user.id)
    )
    return CompanyAddressResponse.model_validate(address)


@router.post(
    "/addresses/{address_id}/deactivate",
    response_model=CompanyAddressResponse,
    summary="Stop using an address",
    description=(
        "Keeps the row; a default address leaves its type with no default until "
        "another is chosen. Deactivating twice is a no-op."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:edit` permission required"},
        **_NOT_FOUND,
    },
)
async def deactivate_company_address(
    address_id: uuid.UUID,
    body: DeactivateCompanyAddressRequest,
    current_user: Annotated[User, Depends(_COMPANY_EDIT)],
    db: AsyncSession = Depends(get_db),
) -> CompanyAddressResponse:
    address = await CompanyAddressService(db).deactivate(
        address_id, reason=body.reason, actor_id=str(current_user.id)
    )
    return CompanyAddressResponse.model_validate(address)
