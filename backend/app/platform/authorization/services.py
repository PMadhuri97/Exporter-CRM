from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import and_, or_, select
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


async def users_holding(
    db: AsyncSession, module: str, action: str, *, among_roles: frozenset[UserRole]
) -> frozenset[str]:
    """The ids of every **active** user in one of `among_roles` granted `module:action`,
    by the same two paths `resolve_permissions` reads (the explicitly assigned role,
    else the built-in role row matching the enum).

    For a rule that needs to know how many people could act — "how many eligible
    checkers does this proposal have" — rather than whether one person can.
    """
    result = await db.execute(
        select(User.id)
        .join(
            Role,
            or_(
                Role.id == User.role_id,
                and_(User.role_id.is_(None), Role.builtin_role == User.role),
            ),
        )
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(
            User.is_active.is_(True),
            User.role.in_(list(among_roles)),
            RolePermission.module == module,
            RolePermission.action == action,
        )
    )
    return frozenset(str(user_id) for user_id in result.scalars())


#: Where a request's resolved permissions are kept on the signed-in user, so a route
#: and the response shapes it builds read one answer instead of resolving it again.
_GRANTED_ATTRIBUTE = "_granted_permissions"


def remember_permissions(user: User, granted: frozenset[tuple[str, str]]) -> None:
    """Keep ``granted`` on this request's user object (never persisted)."""
    setattr(user, _GRANTED_ATTRIBUTE, granted)


def granted_permissions(user: User) -> frozenset[tuple[str, str]]:
    """What ``require_permission`` / ``require_any_permission`` resolved for this user
    in this request; empty when nothing was resolved, so a reader fails closed."""
    return getattr(user, _GRANTED_ATTRIBUTE, frozenset())


def has_permission(user: User, module: str, action: str) -> bool:
    """Whether the signed-in user holds ``module:action`` — for a response that says
    what its reader may do, after the route's own permission check ran."""
    return (module, action) in granted_permissions(user)


async def get_current_permissions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> frozenset[tuple[str, str]]:
    """FastAPI dependency: the signed-in user's permissions."""
    granted = await resolve_permissions(db, current_user)
    remember_permissions(current_user, granted)
    return granted


def _forbidden(detail: str):
    from app.shared.exceptions import AnerBaseException

    return AnerBaseException(detail=detail, error_code="FORBIDDEN", status_code=403)


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
        remember_permissions(current_user, granted)
        if (module, action) not in granted:
            # Names the permission, not the roles that happen to hold it: with roles
            # editable, a role list in this message would go stale the moment someone
            # changes a grant.
            raise _forbidden(f"Required permission: {module}:{action}")
        return current_user

    return _check


def require_any_permission(*permissions: tuple[str, str]) -> Callable:
    """Like ``require_permission``, satisfied by any one of ``permissions`` — for a
    route two kinds of user reach for different reasons (a background-check move the
    RM starts and compliance decides; the staff picker an RM lead and a compliance lead
    both use). The service behind it still decides which move each may make."""

    async def _check(
        current_user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> User:
        granted = await resolve_permissions(db, current_user)
        remember_permissions(current_user, granted)
        if not any(permission in granted for permission in permissions):
            names = " or ".join(f"{module}:{action}" for module, action in permissions)
            raise _forbidden(f"Required permission: {names}")
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
