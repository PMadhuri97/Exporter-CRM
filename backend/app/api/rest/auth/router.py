from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rest.auth.roles_router import me_router as roles_me_router
from app.api.rest.auth.roles_router import router as roles_router
from app.api.rest.auth.schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    AdminUserResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SessionListResponse,
    SessionResponse,
    TokenResponse,
    UpdateMeRequest,
    UserListResponse,
    UserResponse,
)
from app.platform.authentication.adapters.repository import RefreshTokenRepository, UserRepository
from app.platform.authentication.dependencies import get_current_active_user
from app.platform.authentication.models import User, UserRole
from app.platform.authentication.services import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.platform.authorization.services import require_permission
from app.platform.configuration.config import settings
from app.platform.database.services import get_db
from app.shared.exceptions import AnerBaseException, NotFoundError, UnauthorizedError

logger = structlog.get_logger(__name__)
router = APIRouter()

# Committing before the response. Every route here (and in roles_router.py) that
# writes commits before it returns. `get_db` commits as well, but in its teardown,
# which FastAPI runs *after* the response has been sent — so a client acting on the
# response at once (signing in straight after signing up, reloading the user list
# after creating an account) could reach the database before the write did. The CRM's
# services already commit before returning, for the same reason.

# Role management and `GET /me/permissions` live in their own module but under
# this same `/auth` prefix, mirroring how onboarding includes its exporter
# router: one import surface per area, without a second mount point to keep in
# sync in app/api/rest/router.py.
router.include_router(roles_router)
router.include_router(roles_me_router)

# Managing other people's accounts is permission-gated, not role-gated: role
# management (Phase 2) exists so this can be granted to another role without a
# code change. Only the ADMIN role is seeded with these, so out of the box this
# is exactly the ADMIN-only rule section 3.7 of the architecture plan describes.
_CAN_VIEW_USERS = require_permission("users", "view")
_CAN_CREATE_USERS = require_permission("users", "create")
_CAN_EDIT_USERS = require_permission("users", "edit")


#: Sentinel for "the request did not mention role_id at all", which is distinct
#: from `None` ("clear it").
_UNSET = object()

#: The permission whose last holder must never be removed: granting any
#: permission requires it, so once no active account has it, nothing can grant
#: it back.
_UNRECOVERABLE_PERMISSION = ("roles", "edit")


async def _refuse_removing_last_role_manager(
    db: AsyncSession,
    user: User,
    *,
    new_role,
    new_role_id,
    new_is_active,
) -> None:
    """Refuse a user change that would leave nobody able to manage roles."""
    from app.platform.authorization.adapters.repository import RoleRepository

    module, action = _UNRECOVERABLE_PERMISSION
    repo = RoleRepository(db)

    async def holds(role_id: uuid.UUID | None, role) -> bool:
        if role_id is not None:
            return await repo.grants(role_id, module, action)
        return await repo.builtin_grants(role, module, action)

    if not await holds(user.role_id, user.role):
        return  # This account never had it; nothing to lose.

    role_id_after = user.role_id if new_role_id is _UNSET else new_role_id
    role_after = new_role if new_role is not None else user.role
    active_after = user.is_active if new_is_active is None else new_is_active

    keeps_it = active_after and await holds(role_id_after, role_after)
    if keeps_it:
        return

    others = await repo.count_active_holders_of(module, action, excluding=user.id)
    if others == 0:
        raise AnerBaseException(
            detail=(
                "This is the only active account that can manage roles. Grant "
                "role management to someone else first, or nobody will be able "
                "to grant it back."
            ),
            error_code="LAST_ROLE_MANAGER_PROTECTED",
            status_code=409,
        )


async def _assignable_role_or_refuse(db: AsyncSession, role_id: uuid.UUID) -> None:
    """A role must exist and be marked assignable before anyone is put in it.

    `is_assignable` exists so a half-built role can be saved without becoming
    reachable; honouring it here is what makes that flag mean anything.
    """
    from app.platform.authorization.adapters.repository import RoleRepository

    role = await RoleRepository(db).get_by_id(role_id)
    if role is None:
        raise AnerBaseException(
            detail="Role not found", error_code="NOT_FOUND", status_code=404
        )
    if not role.is_assignable:
        raise AnerBaseException(
            detail=f"Role '{role.name}' is not currently assignable",
            error_code="ROLE_NOT_ASSIGNABLE",
            status_code=409,
        )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
    description=(
        "Self-service sign-up. Always grants the lowest role (`API_USER`), which "
        "reaches nothing in the CRM. Returns `404` when "
        "`SELF_SERVICE_SIGNUP_ENABLED` is false."
    ),
    responses={
        201: {"model": UserResponse},
        404: {"description": "Self-service sign-up is disabled on this deployment"},
        409: {"description": "Email address is already registered"},
    },
    tags=["Auth"],
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    # 404, not 403: a deployment that has turned sign-up off is saying the
    # route is not there, and 403 would confirm it exists and is merely closed
    # to this caller — on an unauthenticated route, to every caller equally.
    # Read from `settings` at request time rather than skipping the decorator
    # at import, so the switch can be flipped without rebuilding the app and
    # so the OpenAPI document stays the same shape in both states.
    if not settings.SELF_SERVICE_SIGNUP_ENABLED:
        raise NotFoundError("Not Found")

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
        # Unauthenticated route: never take the role from the caller.
        role=UserRole.API_USER,
        is_active=True,
    )
    user = await user_repo.create(user)
    logger.info("user_registered", user_id=str(user.id), role=user.role.value)
    response = UserResponse.model_validate(user)
    await db.commit()  # before the response is sent — see the note above `router`
    return response


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

    # Stamped here rather than in a middleware so it records an actual
    # credential check, not any authenticated request.
    user.last_login_at = datetime.now(tz=UTC)
    await user_repo.session.flush()

    logger.info("user_login", user_id=str(user.id), role=user.role.value)
    await db.commit()  # before the response is sent — see the note above `router`
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
    await db.commit()  # before the response is sent — see the note above `router`
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
    responses={401: {"description": "Unauthorized"}},
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
    await db.commit()  # before the response is sent — see the note above `router`


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user",
    responses={401: {"description": "Unauthorized"}},
    tags=["Auth"],
)
async def me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)


# ── Self-service: your own profile, password and sessions ───────────────────


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update your own profile",
    description=(
        "Edits your own display name. Role, email and active status are not "
        "fields on this request at all — sending one returns 422."
    ),
    responses={401: {"description": "Unauthorized"}},
    tags=["Auth"],
)
async def update_me(
    body: UpdateMeRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    fields = body.model_dump(exclude_unset=True)
    if "full_name" in fields:
        current_user.full_name = fields["full_name"]
        await db.flush()
        logger.info("user_profile_updated", user_id=str(current_user.id))
    response = UserResponse.model_validate(current_user)
    await db.commit()  # before the response is sent — see the note above `router`
    return response


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Change your own password",
    description=(
        "Requires the current password. On success every refresh token for the "
        "account is revoked, including this client's, so the user signs in "
        "again with the new password — a password change is exactly when a "
        "stolen session should stop working."
    ),
    responses={
        401: {"description": "Unauthorized, or current password incorrect"},
        422: {"description": "New password fails the strength rule"},
    },
    tags=["Auth"],
)
async def change_my_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(body.current_password, current_user.hashed_password):
        # 401 rather than 403: the claim being rejected is the supplied
        # password, not the caller's role.
        raise UnauthorizedError("Current password is incorrect")

    current_user.hashed_password = hash_password(body.new_password)
    await db.flush()
    await RefreshTokenRepository(db).revoke_all_for_user(current_user.id)
    logger.info("user_password_changed", user_id=str(current_user.id))
    await db.commit()  # before the response is sent — see the note above `router`


@router.get(
    "/me/sessions",
    response_model=SessionListResponse,
    summary="List your active sessions",
    description=(
        "Active (unrevoked, unexpired) refresh tokens for your own account. "
        "Only timestamps are reported: no device or IP is recorded on these "
        "rows, so none is invented here."
    ),
    responses={401: {"description": "Unauthorized"}},
    tags=["Auth"],
)
async def list_my_sessions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    tokens = await RefreshTokenRepository(db).list_active_for_user(current_user.id)
    return SessionListResponse(
        sessions=[SessionResponse.model_validate(t) for t in tokens]
    )


@router.delete(
    "/me/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke one of your own sessions",
    description=(
        "The session is looked up by id *and* owner, so one user can never "
        "revoke another's session by guessing an id — an unknown or "
        "someone else's id is a 404, which also avoids confirming it exists."
    ),
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "No such session for this user"},
    },
    tags=["Auth"],
)
async def revoke_my_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    token_repo = RefreshTokenRepository(db)
    token = await token_repo.get_for_user(session_id, current_user.id)
    if token is None:
        raise AnerBaseException(
            detail="Session not found",
            error_code="NOT_FOUND",
            status_code=404,
        )
    if not token.revoked:
        await token_repo.revoke(token)
    logger.info(
        "user_session_revoked", user_id=str(current_user.id), session_id=str(session_id)
    )
    await db.commit()  # before the response is sent — see the note above `router`


# ── Administrator user management ───────────────────────────────────────────


@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List and search user accounts",
    description=(
        "ADMIN only. `q` matches email or full name as a case-insensitive "
        "partial match; `role` and `is_active` filter exactly. `total` is the "
        "count matching the filter, not the length of this page."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "The matching users:* permission is required"},
    },
    tags=["Auth"],
)
async def list_users(
    current_user: Annotated[User, Depends(_CAN_VIEW_USERS)],
    q: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    users, total = await UserRepository(db).search(
        query=q, role=role, is_active=is_active, limit=limit, offset=offset
    )
    return UserListResponse(
        users=[AdminUserResponse.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/users",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account with a role",
    description=(
        "ADMIN only. This is the supported way to create a working staff "
        "account: `POST /auth/register` is unauthenticated and therefore always "
        "produces an API_USER, which can reach nothing in the CRM."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "The matching users:* permission is required"},
        409: {"description": "Email address already registered"},
    },
    tags=["Auth"],
)
async def admin_create_user(
    body: AdminCreateUserRequest,
    current_user: Annotated[User, Depends(_CAN_CREATE_USERS)],
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user_repo = UserRepository(db)

    if await user_repo.email_exists(body.email):
        raise AnerBaseException(
            detail="Email address is already registered",
            error_code="EMAIL_CONFLICT",
            status_code=409,
        )

    if body.role_id is not None:
        await _assignable_role_or_refuse(db, body.role_id)

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        role_id=body.role_id,
        is_active=True,
        # An administrator vouched for this address; see the column comment for
        # why that is not the same as a proven email round-trip.
        is_verified=True,
        created_by=current_user.id,
    )
    user = await user_repo.create(user)
    logger.info(
        "user_created_by_admin",
        user_id=str(user.id),
        role=user.role.value,
        created_by=str(current_user.id),
    )
    response = AdminUserResponse.model_validate(user)
    await db.commit()  # before the response is sent — see the note above `router`
    return response


@router.get(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    summary="Get one user account",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "The matching users:* permission is required"},
        404: {"description": "User not found"},
    },
    tags=["Auth"],
)
async def admin_get_user(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(_CAN_VIEW_USERS)],
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise AnerBaseException(
            detail="User not found", error_code="NOT_FOUND", status_code=404
        )
    return AdminUserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    summary="Update a user's name, role or active status",
    description=(
        "ADMIN only. Two changes are refused outright, because each one can "
        "lock an administrator out of the deployment:\n\n"
        "* changing your own role — self-promotion, and a self-demotion that "
        "you would then have no way to undo;\n"
        "* deactivating your own account.\n\n"
        "Together these are also what prevents the last administrator "
        "disappearing: the caller is always an active ADMIN, so any *other* "
        "account can be demoted or deactivated while at least the caller "
        "remains.\n\n"
        "Deactivating an account also revokes every refresh token it holds, so "
        "the block takes effect on the next request rather than whenever the "
        "current access token happens to expire."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "The matching users:* permission is required"},
        404: {"description": "User not found"},
        409: {"description": "Refused: self role change or self deactivation"},
    },
    tags=["Auth"],
)
async def admin_update_user(
    user_id: uuid.UUID,
    body: AdminUpdateUserRequest,
    current_user: Annotated[User, Depends(_CAN_EDIT_USERS)],
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise AnerBaseException(
            detail="User not found", error_code="NOT_FOUND", status_code=404
        )

    fields = body.model_dump(exclude_unset=True)
    new_role = fields.get("role")
    new_is_active = fields.get("is_active")
    is_self = user.id == current_user.id

    if is_self and new_role is not None and new_role != user.role:
        raise AnerBaseException(
            detail="You cannot change your own role; ask another administrator",
            error_code="SELF_ROLE_CHANGE_FORBIDDEN",
            status_code=409,
        )
    if is_self and new_is_active is False:
        raise AnerBaseException(
            detail="You cannot deactivate your own account",
            error_code="SELF_DEACTIVATION_FORBIDDEN",
            status_code=409,
        )

    if "role_id" in fields and fields["role_id"] is not None:
        await _assignable_role_or_refuse(db, fields["role_id"])
    # Assigning yourself a different permission role can silently strip your own
    # access, exactly like changing your own role, so it is refused the same way.
    if is_self and "role_id" in fields and fields["role_id"] != user.role_id:
        raise AnerBaseException(
            detail=(
                "You cannot change your own permission role; ask another "
                "administrator"
            ),
            error_code="SELF_ROLE_CHANGE_FORBIDDEN",
            status_code=409,
        )

    # Would this change leave nobody able to manage roles? `roles:edit` is the
    # one permission that cannot be granted back once lost — granting anything
    # requires it — so losing every holder means database surgery to recover.
    #
    # This became reachable when these routes moved from `require_role(ADMIN)` to
    # a `users:edit` permission: the caller no longer has to be an administrator,
    # so they can now demote or deactivate the last account that holds it.
    await _refuse_removing_last_role_manager(
        db,
        user,
        new_role=new_role,
        new_role_id=fields.get("role_id") if "role_id" in fields else _UNSET,
        new_is_active=new_is_active,
    )

    if "full_name" in fields:
        user.full_name = fields["full_name"]
    if new_role is not None:
        user.role = new_role
    if "role_id" in fields:
        user.role_id = fields["role_id"]
    if new_is_active is not None and new_is_active != user.is_active:
        user.is_active = new_is_active
        user.deactivated_at = None if new_is_active else datetime.now(tz=UTC)

    await db.flush()

    # A deactivated account keeps working until its access token expires unless
    # its refresh tokens go too.
    if new_is_active is False:
        await RefreshTokenRepository(db).revoke_all_for_user(user.id)

    logger.info(
        "user_updated_by_admin",
        user_id=str(user.id),
        changed=sorted(fields.keys()),
        updated_by=str(current_user.id),
    )
    response = AdminUserResponse.model_validate(user)
    await db.commit()  # before the response is sent — see the note above `router`
    return response


@router.post(
    "/users/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Set a new password for a user",
    description=(
        "ADMIN only, for a colleague who cannot sign in. Every refresh token "
        "for that account is revoked, so an attacker who already has a session "
        "does not keep it. The administrator supplies the password rather than "
        "the server generating one: with no email delivery in this build, a "
        "generated secret would have to travel back in a response body."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "The matching users:* permission is required"},
        404: {"description": "User not found"},
    },
    tags=["Auth"],
)
async def admin_reset_password(
    user_id: uuid.UUID,
    body: AdminResetPasswordRequest,
    current_user: Annotated[User, Depends(_CAN_EDIT_USERS)],
    db: AsyncSession = Depends(get_db),
) -> None:
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise AnerBaseException(
            detail="User not found", error_code="NOT_FOUND", status_code=404
        )

    user.hashed_password = hash_password(body.new_password)
    await db.flush()
    await RefreshTokenRepository(db).revoke_all_for_user(user.id)
    logger.info(
        "user_password_reset_by_admin",
        user_id=str(user.id),
        reset_by=str(current_user.id),
    )
    await db.commit()  # before the response is sent — see the note above `router`
