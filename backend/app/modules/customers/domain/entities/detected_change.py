import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import ChangeType, Materiality
from app.platform.database.models import AppendOnlyModel

SCHEMA = "customers"


class DetectedChange(AppendOnlyModel):
    """One difference between a customer's baseline and their current state.

    Change detection is the substance of a review: a re-review that reports the
    current directors without saying whether they changed has done half the job.

    Append-only. `customer_response`, `assessor_note` and `accepted` are
    therefore written when the row is inserted, not edited into it afterwards —
    an assessment that arrives later is a new row superseding this one, which
    also keeps the assessment history a review needs. A director who changed
    three times in two years is a different fact from one who changed once.

    TODO(AL-737): the supersede-on-assess write path and its repository.
    """

    __tablename__ = "detected_change"
    __table_args__ = (
        UniqueConstraint("change_ref", name="uq_detected_change_ref"),
        # Assessment reads one review's changes, worst materiality first.
        Index("ix_detected_change_review_materiality", "review_ref", "materiality"),
        {"schema": SCHEMA},
    )

    change_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    review_ref: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA}.customer_review.review_ref", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    attribute: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(
        Enum(ChangeType, name="detected_change_type_enum", schema=SCHEMA), nullable=False
    )
    baseline_value: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    current_value: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Configured per attribute: a beneficial owner change is material, a
    # registered address change notable, a formatting difference immaterial.
    materiality: Mapped[Materiality] = mapped_column(
        Enum(Materiality, name="detected_change_materiality_enum", schema=SCHEMA),
        nullable=False,
    )
    # Which source established the current value, and therefore how far the
    # change can be relied upon.
    verification_source: Mapped[str] = mapped_column(String(100), nullable=False)
    requires_customer_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    customer_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessor_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
