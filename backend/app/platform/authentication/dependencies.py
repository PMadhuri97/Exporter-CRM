from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.authentication.adapters.repository import (
    RefreshTokenRepository,
    UserRepository,
)
from app.platform.authentication.models import User
from app.platform.authentication.services import decode_access_token
from app.platform.database.services import get_db
from app.shared.exceptions import UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Missing Bearer token")

    payload = decode_access_token(credentials.credentials)

    try:
        user_id = uuid.UUID(payload["sub"])
        # A token from before sessions were recorded has no `sid`; it is refused like
        # an expired one, and the client signs in again (or refreshes) for a new one.
        session_id = uuid.UUID(payload["sid"])
    except (KeyError, ValueError, TypeError):
        raise UnauthorizedError("Invalid token payload")

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise UnauthorizedError("Account is inactive")
    # A valid signature is not enough: the sign-in must still be live. Logging out,
    # revoking the session, a password change or a reset all revoke its refresh token,
    # and this ends every access token it issued at the same moment.
    if not await RefreshTokenRepository(db).session_is_live(session_id, user_id):
        raise UnauthorizedError("Session has ended")

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user
