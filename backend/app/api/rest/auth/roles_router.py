"""Role management routes.

Mounted under `/auth` by `router.py`, so the paths are `/auth/roles...`.

Every route here is gated by a permission rather than a role, because roles are
now data: `require_role(ADMIN)` would be a rule an administrator cannot change,
which is the thing this feature exists to fix. Out of the box only the ADMIN
role is seeded with `roles:*`, so behaviour is unchanged until someone grants
them elsewhere.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rest.auth.role_schemas import (
    CreateRoleRequest,
    MyPermissionsResponse,
    PermissionCatalogResponse,
    PermissionRef,
    RoleListResponse,
    RoleResponse,
    UpdateRoleRequest,
)
from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User
from app.platform.authorization.adapters.repository import RoleRepository
from app.platform.authorization.models import Role
from app.platform.authorization.services import require_permission, resolve_permissions
from app.platform.database.services import get_db
from app.shared.exceptions import AnerBaseException

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/roles", tags=["Roles"])

_CAN_VIEW = require_permission("roles", "view")
_CAN_CREATE = require_permission("roles", "create")
_CAN_EDIT = require_permission("roles", "edit")
_CAN_DELETE = require_permission("roles", "delete")

#: Losing this permission is unrecoverable through the API: without it nobody
#: can grant it back. Editing your own role is otherwise allowed.
_SELF_LOCKOUT_GUARD = ("roles", "edit")


def _to_response(role: Role, user_count: int) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        slug=role.slug,
        name=role.name,
        description=role.description,
        builtin_role=role.builtin_role,
        is_builtin=role.is_builtin,
        is_assignable=role.is_assignable,
        permissions=[
            PermissionRef(module=p.module, action=p.action)
            for p in sorted(role.permissions, key=lambda p: (p.module, p.action))
        ],
        user_count=user_count,
        created_at=role.created_at,
    )


async def _role_or_404(repo: RoleRepository, role_id: uuid.UUID) -> Role:
    role = await repo.get_by_id(role_id)
    if role is None:
        raise AnerBaseException(
            detail="Role not found", error_code="NOT_FOUND", status_code=404
        )
    return role


async def _refuse_self_lockout(
    db: AsyncSession, current_user: User, role: Role, new_pairs: set[tuple[str, str]]
) -> None:
    """Refuse an edit that removes role management from the caller's own role.

    Unlike a "last administrator" rule, this is genuinely reachable: an
    administrator editing the very role they hold can drop `roles:edit` and
    nobody — including them — can grant it back afterwards, since granting
    requires the permission just removed. A database edit would be the only way
    out.
    """
    if _SELF_LOCKOUT_GUARD in new_pairs:
        return

    holds_this_role = (
        current_user.role_id == role.id
        if current_user.role_id is not None
        else role.builtin_role == current_user.role
    )
    if not holds_this_role:
        return

    raise AnerBaseException(
        detail=(
            "This is your own role, and the change would remove your permission "
            "to manage roles — nobody could grant it back. Remove it from a role "
            "you do not hold, or have another administrator make this change."
        ),
        error_code="SELF_LOCKOUT_FORBIDDEN",
        status_code=409,
    )


@router.get(
    "/catalog",
    response_model=PermissionCatalogResponse,
    summary="Every permission that can be granted",
    description=(
        "The vocabulary role editing works against. `enforced` is false for a "
        "module whose routes still use the older role check — those permissions "
        "are stored and will apply once those routes migrate, but they gate "
        "nothing today, and a client must say so rather than implying otherwise."
    ),
    responses={403: {"description": "roles:view permission required"}},
)
async def get_catalog(
    current_user: Annotated[User, Depends(_CAN_VIEW)],
) -> PermissionCatalogResponse:
    return PermissionCatalogResponse.from_catalog()


@router.get(
    "",
    response_model=RoleListResponse,
    summary="List roles with their permissions and holder counts",
    responses={403: {"description": "roles:view permission required"}},
)
async def list_roles(
    current_user: Annotated[User, Depends(_CAN_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> RoleListResponse:
    repo = RoleRepository(db)
    roles = await repo.list_all()
    counts = await repo.user_counts()
    return RoleListResponse(
        roles=[_to_response(role, counts.get(role.id, 0)) for role in roles]
    )


@router.post(
    "",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role",
    description=(
        "A custom role can be assigned immediately, but only the routes listed "
        "as enforced in the catalogue consult it. Everything else still reads "
        "the account's built-in role, so a custom role does not yet widen or "
        "narrow access to the CRM screens."
    ),
    responses={
        403: {"description": "roles:create permission required"},
        409: {"description": "A role with this slug already exists"},
    },
)
async def create_role(
    body: CreateRoleRequest,
    current_user: Annotated[User, Depends(_CAN_CREATE)],
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    repo = RoleRepository(db)
    if await repo.get_by_slug(body.slug) is not None:
        raise AnerBaseException(
            detail=f"A role with slug '{body.slug}' already exists",
            error_code="ROLE_SLUG_CONFLICT",
            status_code=409,
        )

    role = Role(
        slug=body.slug,
        name=body.name,
        description=body.description,
        builtin_role=None,
        is_assignable=True,
    )
    role = await repo.create(role)
    await repo.replace_permissions(
        role, {(p.module, p.action) for p in body.permissions}
    )
    logger.info(
        "role_created",
        role_id=str(role.id),
        slug=role.slug,
        permission_count=len(body.permissions),
        actor_id=str(current_user.id),
    )
    response = _to_response(role, user_count=0)
    await db.commit()  # before the response is sent — see auth/router.py
    return response


@router.get(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Get one role",
    responses={
        403: {"description": "roles:view permission required"},
        404: {"description": "Role not found"},
    },
)
async def get_role(
    role_id: uuid.UUID,
    current_user: Annotated[User, Depends(_CAN_VIEW)],
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    repo = RoleRepository(db)
    role = await _role_or_404(repo, role_id)
    counts = await repo.user_counts()
    return _to_response(role, counts.get(role.id, 0))


@router.patch(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Rename a role or change what it grants",
    description=(
        "Built-in roles are editable, by decision — section 3.7 of the "
        "architecture plan describes their starting permissions, not a "
        "guarantee. `permissions`, when supplied, replaces the whole set.\n\n"
        "One edit is refused: removing `roles:edit` from the role you yourself "
        "hold, because no one could grant it back afterwards."
    ),
    responses={
        403: {"description": "roles:edit permission required"},
        404: {"description": "Role not found"},
        409: {"description": "Refused: would remove your own ability to manage roles"},
    },
)
async def update_role(
    role_id: uuid.UUID,
    body: UpdateRoleRequest,
    current_user: Annotated[User, Depends(_CAN_EDIT)],
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    repo = RoleRepository(db)
    role = await _role_or_404(repo, role_id)
    fields = body.model_dump(exclude_unset=True)

    if body.permissions is not None:
        new_pairs = {(p.module, p.action) for p in body.permissions}
        await _refuse_self_lockout(db, current_user, role, new_pairs)

    if "name" in fields:
        role.name = fields["name"]
    if "description" in fields:
        role.description = fields["description"]
    if "is_assignable" in fields and fields["is_assignable"] is not None:
        role.is_assignable = fields["is_assignable"]
    await db.flush()

    if body.permissions is not None:
        await repo.replace_permissions(
            role, {(p.module, p.action) for p in body.permissions}
        )

    counts = await repo.user_counts()
    logger.info(
        "role_updated",
        role_id=str(role.id),
        changed=sorted(fields.keys()),
        actor_id=str(current_user.id),
    )
    response = _to_response(role, counts.get(role.id, 0))
    await db.commit()  # before the response is sent — see auth/router.py
    return response


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a custom role",
    description=(
        "Refused for a built-in role: those back the account role values every "
        "unmigrated route still reads, so deleting one would leave its holders "
        "resolving to no permissions at all.\n\n"
        "Also refused while any account still holds the role — reassign them "
        "first. Silently demoting people is a privilege change nobody asked for."
    ),
    responses={
        403: {"description": "roles:delete permission required"},
        404: {"description": "Role not found"},
        409: {"description": "Refused: built-in role, or the role is still held"},
    },
)
async def delete_role(
    role_id: uuid.UUID,
    current_user: Annotated[User, Depends(_CAN_DELETE)],
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = RoleRepository(db)
    role = await _role_or_404(repo, role_id)

    if role.is_builtin:
        raise AnerBaseException(
            detail=(
                f"'{role.name}' is a built-in role and cannot be deleted. Its "
                "permissions can be edited instead."
            ),
            error_code="BUILTIN_ROLE_PROTECTED",
            status_code=409,
        )

    counts = await repo.user_counts()
    holders = counts.get(role.id, 0)
    if holders > 0:
        raise AnerBaseException(
            detail=(
                f"{holders} account(s) still hold '{role.name}'. Move them to "
                "another role first."
            ),
            error_code="ROLE_STILL_ASSIGNED",
            status_code=409,
        )

    await db.delete(role)
    await db.flush()
    logger.info(
        "role_deleted",
        role_id=str(role.id),
        slug=role.slug,
        actor_id=str(current_user.id),
    )
    await db.commit()  # before the response is sent — see auth/router.py


# ── What the signed-in user may do ──────────────────────────────────────────

me_router = APIRouter(tags=["Roles"])


@me_router.get(
    "/me/permissions",
    response_model=MyPermissionsResponse,
    summary="The signed-in user's own permissions",
    description=(
        "Needs no permission of its own: every caller may ask what they "
        "themselves can do. This is what a client should branch on instead of "
        "comparing role names, so a permission granted in role management takes "
        "effect in the UI without a code change."
    ),
    responses={401: {"description": "Unauthorized"}},
)
async def my_permissions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> MyPermissionsResponse:
    granted = await resolve_permissions(db, current_user)
    repo = RoleRepository(db)
    # The same row `resolve_permissions` read: the assigned role, else the built-in
    # row for the enum — whose name an administrator may have changed, and which
    # for OPERATIONS reads "RM (Relationship Manager)" (auth_0005).
    role = (
        await repo.get_by_id(current_user.role_id)
        if current_user.role_id is not None
        else await repo.get_builtin(current_user.role)
    )
    return MyPermissionsResponse(
        role=current_user.role,
        role_id=current_user.role_id,
        # Falls back to the enum's own name only if no row resolves at all, so
        # the field is always something a client can display.
        role_name=role.name if role is not None else current_user.role.value.title(),
        permissions=[
            PermissionRef(module=module, action=action)
            for module, action in sorted(granted)
        ],
    )
