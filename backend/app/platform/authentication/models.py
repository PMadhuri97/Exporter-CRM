import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AnerModel

SCHEMA = "auth"


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    COMPLIANCE = "COMPLIANCE"
    OPERATIONS = "OPERATIONS"
    API_USER = "API_USER"
    #: Internal technical staff. Distinct from API_USER (external/system API
    #: callers) — see auth_0002_developer_role's docstring. Never permitted to
    #: reveal masked PII fields in the Exporter CRM frontend, unlike every
    #: other role.
    DEVELOPER = "DEVELOPER"


class User(AnerModel):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
        {"schema": SCHEMA},
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum", schema=SCHEMA),
        nullable=False,
        default=UserRole.API_USER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: An administrator created this account (so its email is trusted), rather
    #: than it arriving through self-service sign-up. No email-confirmation
    #: flow exists yet, so this records provenance rather than a verified
    #: round-trip — it must not be read as "this address was proven".
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Stamped on every successful login. Nullable because accounts that have
    #: never signed in are a real state an administrator needs to see.
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: The administrator who created this account; NULL for self-service
    #: sign-ups and for the first admin created by the bootstrap command.
    #: ON DELETE SET NULL, since deleting an administrator must never cascade
    #: into deleting the accounts they created.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: The role row backing this account's permissions. NULL means "fall back
    #: to the built-in role matching the `role` enum above", which is still how
    #: most accounts work — see `authorization.resolve_permissions`. Set only
    #: when a role is assigned explicitly (including a custom one).
    #: RESTRICT rather than SET NULL: silently demoting every holder of a
    #: deleted role to their enum default is exactly the kind of quiet
    #: privilege change an audit cannot reconstruct, so the delete is refused
    #: while anyone still holds the role.
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.role.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: When `is_active` last went false. Cleared on reactivation so it always
    #: describes the current state rather than accumulating history — the
    #: audit trail of who deactivated whom belongs in the history log
    #: (Developer 1's task L1-11), not in this column.
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(AnerModel):
    __tablename__ = "refresh_tokens"
    __table_args__ = ({"schema": SCHEMA},)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SHA-256 hex digest of the raw token — raw token is never stored
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
