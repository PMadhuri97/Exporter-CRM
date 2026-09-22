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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import AttestationStatus
from app.platform.database.models import AnerModel

SCHEMA = "customers"


class ReAttestationRequest(AnerModel):
    """Where a customer must confirm or update the information they declared.

    A completed attestation is only worth the authority of whoever answered it.
    `signatory_authority_verified` records that the responder was checked
    against the current director and signatory record, and the database refuses
    to mark an attestation complete without it — an unverified answer binds
    nobody and is worse than no answer, because the file looks satisfied.
    """

    __tablename__ = "re_attestation_request"
    __table_args__ = (
        UniqueConstraint("attestation_ref", name="uq_re_attestation_request_ref"),
        Index("ix_re_attestation_request_due", "status", "due_by"),
        # Completion requires an answer, someone who gave it, and the authority
        # to have given it.
        CheckConstraint(
            "status <> 'COMPLETED' OR ("
            " signatory_authority_verified IS TRUE"
            " AND responded_at IS NOT NULL"
            " AND responded_by IS NOT NULL"
            ")",
            name="ck_re_attestation_request_completion_authorised",
        ),
        {"schema": SCHEMA},
    )

    attestation_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_ref: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA}.customer_review.review_ref", ondelete="RESTRICT"),
        nullable=False,
    )
    # What the customer must confirm, update, or supply.
    requested_items: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_by: Mapped[date] = mapped_column(Date, nullable=False)
    reminder_schedule: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[AttestationStatus] = mapped_column(
        Enum(AttestationStatus, name="attestation_status_enum", schema=SCHEMA), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The individual who responded, not the entity they answered for.
    responded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signatory_authority_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    response_detail: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
