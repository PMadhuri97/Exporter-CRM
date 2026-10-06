import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.platform.authentication.models import UserRole


def validate_password_strength(v: str) -> str:
    """The one place the password rule lives.

    `RegisterRequest`, administrator-created accounts, administrator resets and
    self-service changes all enforce the same rule by calling this — a second
    copy would eventually drift, and the weakest copy would become the real
    policy.
    """
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit")
    return v


class RegisterRequest(BaseModel):
    """Self-service sign-up. Deliberately carries no `role`: the route is
    unauthenticated, so any caller-supplied role is a privilege escalation.
    Every registered account is `API_USER`; elevated roles are granted out of
    band. `extra="forbid"` makes a client still sending `role` fail loudly
    (422) instead of silently receiving a lower role than it asked for."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}


# ── Administrator user management ───────────────────────────────────────────


class AdminUserResponse(UserResponse):
    """What an administrator sees, on top of `UserResponse`'s common fields.

    A separate model rather than extra optional fields on `UserResponse`:
    `GET /auth/me` is served to every role, and `created_by` /`last_login_at`
    are administrative facts about an account, not things every caller needs.
    """

    is_verified: bool
    last_login_at: datetime | None
    created_by: uuid.UUID | None
    deactivated_at: datetime | None
    created_at: datetime
    #: The role row whose permissions this account resolves through. NULL means
    #: "the built-in role matching `role`", which is how most accounts work. The
    #: name is not denormalised here: a client listing roles already has it, and
    #: joining on every row to repeat it would be the more expensive lie to keep
    #: consistent.
    role_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """`total` is the count matching the filter, not the page length, so the
    caller can page without a second request."""

    users: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AdminCreateUserRequest(BaseModel):
    """An administrator creating an account for a colleague.

    Unlike `RegisterRequest` this *does* carry a role: the route is
    ADMIN-gated, so choosing the role is the point rather than an escalation.
    This is the intended replacement for self-service sign-up as a way to get
    a working staff account.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole
    #: Optional permission role. Left unset, the account resolves permissions
    #: through the built-in role matching `role` above — the behaviour before
    #: role management existed. Set, it points at any assignable role, including
    #: a custom one, and overrides that resolution.
    role_id: uuid.UUID | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class AdminUpdateUserRequest(BaseModel):
    """Change another account's role, name or active flag.

    Every field is optional, and `None` is indistinguishable from "absent" for
    `role`/`is_active` on purpose — neither is nullable, so only
    `model_dump(exclude_unset=True)` decides what changes. `full_name` is
    genuinely nullable (clearing a name is a legitimate edit), so the route
    reads the same `exclude_unset` set rather than testing for None.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
    #: Nullable on purpose, and read via `exclude_unset`: sending
    #: `{"role_id": null}` clears the explicit assignment and returns the
    #: account to resolving permissions through its `role` enum, which is a
    #: distinct intent from not mentioning the field at all.
    role_id: uuid.UUID | None = None


class AdminResetPasswordRequest(BaseModel):
    """An administrator setting a new password for someone who cannot sign in.

    The administrator supplies the value rather than the server generating
    one: there is no email delivery in this build, so a generated secret would
    have to come back in an HTTP response body, which is a worse place for it
    than the administrator's own password manager.
    """

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ── Self-service (any signed-in user) ───────────────────────────────────────


class UpdateMeRequest(BaseModel):
    """Edit your own profile. Deliberately has no `role`, `is_active` or
    `email` field: with `extra="forbid"`, a caller trying to promote itself
    gets a 422 at the boundary instead of reaching a handler that has to
    remember to ignore it."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Change your own password. `current_password` is required even though
    the caller is already authenticated — an access token found on an
    unlocked laptop should not be enough to lock the owner out of their own
    account."""

    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class SessionResponse(BaseModel):
    """One active refresh token.

    No device or IP columns exist on `auth.refresh_tokens`, so this reports
    only what is genuinely recorded — times. Showing a fabricated
    "Chrome on Windows" would be worse than showing nothing.
    """

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class AccessTokenPayload(BaseModel):
    sub: str
    email: str
    role: str
    type: str
    exp: int
    iat: int
