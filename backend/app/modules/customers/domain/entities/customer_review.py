import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import (
    ReviewOutcome,
    ReviewRiskRating,
    ReviewStatus,
    ReviewType,
)
from app.platform.database.models import AnerModel

SCHEMA = "customers"

#: A rationale is a compliance record read by a regulator, not a field to clear.
#: Whitespace is trimmed before the length is measured so spaces cannot satisfy it.
MIN_OUTCOME_RATIONALE_LENGTH = 50


class CustomerReview(AnerModel):
    """One review of one customer, scheduled or triggered.

    Every review compares current facts against a recorded baseline, so
    `baseline_snapshot_ref` is a real foreign key and not merely non-null: a ref
    that points at no snapshot buys nothing over a null one.
    """

    __tablename__ = "customer_review"
    __table_args__ = (
        UniqueConstraint("review_ref", name="uq_customer_review_ref"),
        Index("ix_customer_review_customer_time", "customer_id", "initiated_at"),
        CheckConstraint(
            "review_ref ~ '^REV-[0-9]{4}-[0-9]+$'",
            name="ck_customer_review_ref_format",
        ),
        # A completed review states what it concluded and why, in enough words to
        # be a record. A one-word rationale is not a compliance record.
        CheckConstraint(
            "status <> 'COMPLETED' OR ("
            " outcome IS NOT NULL"
            f" AND char_length(btrim(outcome_rationale)) >= {MIN_OUTCOME_RATIONALE_LENGTH}"
            ")",
            name="ck_customer_review_completion_recorded",
        ),
        # Consequential outcomes carry dual authorisation, guaranteed here rather
        # than only in the service that writes them.
        CheckConstraint(
            "outcome IS NULL"
            " OR outcome NOT IN ('SUSPENDED', 'RESTRICTED', 'REFERRED_TO_OFFBOARDING')"
            " OR approval_request_id IS NOT NULL",
            name="ck_customer_review_consequential_outcome_approved",
        ),
        # An event-triggered review names the trigger that fired; a periodic one
        # has none to name.
        CheckConstraint(
            "(review_type = 'EVENT_TRIGGERED' AND trigger_code IS NOT NULL)"
            " OR (review_type = 'PERIODIC' AND trigger_code IS NULL)"
            " OR review_type IN ('AD_HOC', 'REMEDIATION_FOLLOWUP')",
            name="ck_customer_review_trigger_code_consistent",
        ),
        # rating_changed is derived, so it cannot be allowed to disagree with the
        # two ratings it summarises.
        CheckConstraint(
            "CASE WHEN risk_rating_after IS NULL"
            " THEN rating_changed = false"
            " ELSE rating_changed = (risk_rating_before IS DISTINCT FROM risk_rating_after)"
            " END",
            name="ck_customer_review_rating_changed_derived",
        ),
        CheckConstraint(
            "material_change_count >= 0",
            name="ck_customer_review_material_change_count_non_negative",
        ),
        {"schema": SCHEMA},
    )

    review_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_type: Mapped[ReviewType] = mapped_column(
        Enum(ReviewType, name="customer_review_type_enum", schema=SCHEMA), nullable=False
    )
    trigger_code: Mapped[str | None] = mapped_column(
        String(100),
        ForeignKey(
            f"{SCHEMA}.review_trigger_definition.trigger_code", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    trigger_event_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    due_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="customer_review_status_enum", schema=SCHEMA), nullable=False
    )
    # The recorded state this review compares against. A review with no baseline
    # is not a review.
    baseline_snapshot_ref: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            f"{SCHEMA}.customer_baseline_snapshot.snapshot_ref", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    verification_result_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # The comparison output — the substance of the review.
    changes_detected: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    material_change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_rating_before: Mapped[ReviewRiskRating] = mapped_column(
        Enum(ReviewRiskRating, name="review_risk_rating_enum", schema=SCHEMA), nullable=False
    )
    risk_rating_after: Mapped[ReviewRiskRating | None] = mapped_column(
        Enum(ReviewRiskRating, name="review_risk_rating_enum", schema=SCHEMA), nullable=True
    )
    rating_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome: Mapped[ReviewOutcome | None] = mapped_column(
        Enum(ReviewOutcome, name="customer_review_outcome_enum", schema=SCHEMA), nullable=True
    )
    outcome_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
