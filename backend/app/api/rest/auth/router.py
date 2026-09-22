from __future__ import annotations

from datetime import UTC
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rest.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.platform.authentication.adapters.repository import RefreshTokenRepository, UserRepository
from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User
from app.platform.authentication.services import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.platform.configuration.config import settings
from app.platform.database.services import get_db
from app.shared.exceptions import AnerBaseException, UnauthorizedError

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
    tags=["Auth"],
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user_repo = UserRepository(db)

    if await user_repo.email_exists(body.email):
        raise AnerBaseException(
            detail="Email address is already registered",
            error_code="EMAIL_CONFLICT",
            status_code=409,
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        is_active=True,
    )
    user = await user_repo.create(user)
    logger.info("user_registered", user_id=str(user.id), role=user.role.value)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive tokens",
    tags=["Auth"],
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user_repo = UserRepository(db)
    token_repo = RefreshTokenRepository(db)

    user = await user_repo.get_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    access_token = create_access_token(user.id, user.email, user.role.value)
    raw_refresh, refresh_hash = generate_refresh_token()

    from app.platform.authentication.models import RefreshToken
    db_token = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_token_expiry(),
        revoked=False,
    )
    await token_repo.create(db_token)

    logger.info("user_login", user_id=str(user.id), role=user.role.value)
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for new tokens",
    tags=["Auth"],
)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    from datetime import datetime

    token_repo = RefreshTokenRepository(db)
    token_hash = hash_refresh_token(body.refresh_token)
    db_token = await token_repo.get_by_hash(token_hash)

    if db_token is None or db_token.revoked:
        raise UnauthorizedError("Invalid or revoked refresh token")
    if db_token.expires_at < datetime.now(tz=UTC):
        raise UnauthorizedError("Refresh token has expired")

    user = db_token.user
    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    # Token rotation — revoke old, issue new
    await token_repo.revoke(db_token)

    access_token = create_access_token(user.id, user.email, user.role.value)
    raw_refresh, new_hash = generate_refresh_token()

    from app.platform.authentication.models import RefreshToken
    new_token = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        expires_at=refresh_token_expiry(),
        revoked=False,
    )
    await token_repo.create(new_token)

    logger.info("token_refreshed", user_id=str(user.id))
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current refresh token",
    tags=["Auth"],
)
async def logout(
    body: RefreshRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    token_repo = RefreshTokenRepository(db)
    token_hash = hash_refresh_token(body.refresh_token)
    db_token = await token_repo.get_by_hash(token_hash)

    if db_token and db_token.user_id == current_user.id and not db_token.revoked:
        await token_repo.revoke(db_token)

    logger.info("user_logout", user_id=str(current_user.id))


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user",
    tags=["Auth"],
)
async def me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)
