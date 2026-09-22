import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Mutable records — created_at and updated_at."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CreatedOnlyMixin:
    """Immutable records — only created_at, no updated_at."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AnerModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Standard mutable model. All regular domain records use this."""

    __abstract__ = True


class AppendOnlyModel(UUIDPrimaryKeyMixin, CreatedOnlyMixin, Base):
    """Append-only model. No UPDATE or DELETE allowed — enforced by DB trigger."""

    __abstract__ = True
