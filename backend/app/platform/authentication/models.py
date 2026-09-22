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
