from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User, UserRole


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
