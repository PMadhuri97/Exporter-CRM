from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.authentication.adapters.repository import UserRepository
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
    except (KeyError, ValueError):
        raise UnauthorizedError("Invalid token payload")

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user
