import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import (
    ReviewRiskRating,
    ScheduleStatus,
)
from app.platform.database.models import AnerModel

SCHEMA = "customers"


class ReviewSchedule(AnerModel):
    """When each customer is next due for re-verification.

    One live schedule per customer, enforced by the unique constraint: a second
    row would give the due sweep two answers to the same question.
    """

    __tablename__ = "review_schedule"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_review_schedule_customer_id"),
        # The due sweep reads this pair and nothing else.
        Index("ix_review_schedule_due_sweep", "next_review_due", "schedule_status"),
        CheckConstraint(
            "review_frequency_months > 0",
            name="ck_review_schedule_frequency_positive",
        ),
        CheckConstraint(
            "grace_period_days >= 0",
            name="ck_review_schedule_grace_period_non_negative",
        ),
        # Acceleration must say why. A schedule that silently moved forward is
        # indistinguishable from one that was always due sooner.
        CheckConstraint(
            "accelerated_from IS NULL OR acceleration_reason IS NOT NULL",
            name="ck_review_schedule_acceleration_reason_present",
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_risk_rating: Mapped[ReviewRiskRating] = mapped_column(
        Enum(ReviewRiskRating, name="review_risk_rating_enum", schema=SCHEMA),
        nullable=False,
    )
    review_frequency_months: Mapped[int] = mapped_column(Integer, nullable=False)
    last_review_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_review_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_review_due: Mapped[date] = mapped_column(Date, nullable=False)
    grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus, name="review_schedule_status_enum", schema=SCHEMA),
        nullable=False,
    )
    # The original due date, retained so an acceleration stays visible.
    accelerated_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    acceleration_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
