import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AppendOnlyModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest

SCHEMA = "onboarding"

class OnboardingEvent(AppendOnlyModel):
    __tablename__ = "onboarding_event"
    __table_args__ = (
        Index("ix_onboarding_event_onboarding_request_id", "onboarding_request_id"),
        {"schema": SCHEMA},
    )

    onboarding_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.onboarding_request.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    request: Mapped["OnboardingRequest"] = relationship("OnboardingRequest", back_populates="events")
