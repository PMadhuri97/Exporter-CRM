import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import (
    ReviewRiskRating,
    SnapshotReason,
)
from app.platform.database.models import AppendOnlyModel

SCHEMA = "customers"


class CustomerBaselineSnapshot(AppendOnlyModel):
    """An immutable point-in-time record of a customer's verified state.

    Reviews compare against a snapshot rather than the live customer record. The
    live record moves for reasons that are not findings — an address the customer
    updated, a typo an operator corrected — and comparing against it would report
    those as changes. A snapshot taken at the last verified state is the only
    honest baseline, and it preserves what was verified when, which is what a
    regulator asks for.

    Append-only: this is evidence, and evidence that can be edited is not
    evidence. Enforced by `public.prevent_mutation()`, by the absence of
    `updated_at` on `AppendOnlyModel`, and by the repository exposing no update
    or delete.
    """

    __tablename__ = "customer_baseline_snapshot"
    __table_args__ = (
        UniqueConstraint("snapshot_ref", name="uq_customer_baseline_snapshot_ref"),
        # A review resolves the customer's most recent snapshot on every run.
        Index(
            "ix_customer_baseline_snapshot_customer_time",
            "customer_id",
            "captured_at",
        ),
        {"schema": SCHEMA},
    )

    snapshot_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_reason: Mapped[SnapshotReason] = mapped_column(
        Enum(SnapshotReason, name="baseline_snapshot_reason_enum", schema=SCHEMA),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Null for the onboarding snapshot, which no review produced.
    source_review_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    registered_identifiers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    registered_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registration_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # contains_pii — no field-level encryption layer exists yet; see README.
    directors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    beneficial_owners: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    declared_sectors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    declared_corridors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    declared_volumes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_rating: Mapped[ReviewRiskRating] = mapped_column(
        Enum(ReviewRiskRating, name="review_risk_rating_enum", schema=SCHEMA),
        nullable=False,
    )
    screening_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # What the customer was permitted to do at this point.
    entitlements_snapshot: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
