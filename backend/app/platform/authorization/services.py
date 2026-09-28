from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.models import Role, RolePermission
from app.platform.database.services import get_db


async def resolve_permissions(db: AsyncSession, user: User) -> frozenset[tuple[str, str]]:
    """Every (module, action) pair this user is granted.

    One source of truth, reached two ways, because the migration off the legacy
    `UserRole` enum is deliberately incomplete:

    1. `user.role_id` set — the role explicitly assigned to this account.
    2. Otherwise — the built-in role row matching `user.role`, the enum column
       every account still carries.

    Both paths read the same `auth.role_permission` rows, so granting a
    permission changes behaviour for enum-only and explicitly-assigned users
    alike. A user whose enum value has no matching row (impossible unless a
    built-in row was deleted, which is refused) gets no permissions rather than
    an error: failing closed is the only safe direction here.
    """
    if user.role_id is not None:
        criterion = Role.id == user.role_id
    else:
        criterion = Role.builtin_role == user.role

    result = await db.execute(
        select(RolePermission.module, RolePermission.action)
        .join(Role, Role.id == RolePermission.role_id)
        .where(criterion)
    )
    return frozenset((module, action) for module, action in result.all())


async def get_current_permissions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> frozenset[tuple[str, str]]:
    """FastAPI dependency: the signed-in user's permissions."""
    return await resolve_permissions(db, current_user)


def require_permission(module: str, action: str) -> Callable:
    """
    Factory returning a dependency that enforces one permission.

    Usage:
        @router.get("/users")
        async def endpoint(user: User = Depends(require_permission("users", "view"))):
            ...

    Prefer this over `require_role` for new routes: it is the mechanism role
    management actually configures. `require_role` remains for the routes that
    have not migrated yet — see `catalog.py`'s `enforced` flag for which
    modules those are.
    """

    async def _check(
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
        granted = await resolve_permissions(db, current_user)
        if (module, action) not in granted:
            from app.shared.exceptions import AnerBaseException

            raise AnerBaseException(
                # Names the permission, not the roles that happen to hold it:
                # with roles editable, a role list in this message would go
                # stale the moment someone changes a grant.
                detail=f"Required permission: {module}:{action}",
                error_code="FORBIDDEN",
                status_code=403,
            )
        return current_user

    return _check


def require_role(*roles: UserRole) -> Callable:
    """
    Factory that returns a FastAPI dependency enforcing role-based access.

    Usage:
        @router.get("/admin-only")
        async def endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    """
    async def _check(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if current_user.role not in roles:
            from app.shared.exceptions import AnerBaseException
            raise AnerBaseException(
                detail=f"Required role: {[r.value for r in roles]}",
                error_code="FORBIDDEN",
                status_code=403,
            )
        return current_user

    return _check
