"""``VerificationReview`` — one compliance review of a verification result —
**owner: Developer 4B** (``docs/contracts/verification-and-screening.md`` §1, migration
``onboarding_0021_verif_review``).

**A verdict changes by adding a record, never by editing one.** The first review of
a result has no ``supersedes_review_id``; every later review names the review it
replaces, which must be the current one. The current review is the **chain head**:
the one nothing supersedes. The database keeps it a single chain per result:

* ``uq_verification_review_supersedes`` — a review is superseded at most once, so two
  reviewers racing to replace the same head cannot fork the chain;
* ``uq_verification_review_first`` — one first review per result;
* ``fk_verification_review_supersedes`` — a review supersedes a review of the same
  result only;
* ``trg_verification_review_append_only`` — ``UPDATE`` and ``DELETE`` are refused.

``reviewed_by`` is ``str(user.id)`` from the login session, never a request field;
``reviewed_at`` is the database clock.

``AppendOnlyModel`` (no ``updated_at``), like every other append-only table here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.orchestration_enums import VerificationReviewStatus
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class VerificationReview(AppendOnlyModel):
    __tablename__ = "verification_review"
    __table_args__ = (
        UniqueConstraint("id", "verification_result_id", name="uq_verification_review_id_result"),
        UniqueConstraint("supersedes_review_id", name="uq_verification_review_supersedes"),
        ForeignKeyConstraint(
            ["supersedes_review_id", "verification_result_id"],
            [f"{SCHEMA}.verification_review.id", f"{SCHEMA}.verification_review.verification_result_id"],
            name="fk_verification_review_supersedes",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "supersedes_review_id IS NULL OR supersedes_review_id <> id",
            name="ck_verification_review_not_self",
        ),
        CheckConstraint(
            "supersedes_review_id IS NULL OR (note IS NOT NULL AND btrim(note) <> '')",
            name="ck_verification_review_supersede_note",
        ),
        Index(
            "uq_verification_review_first",
            "verification_result_id",
            unique=True,
            postgresql_where=text("supersedes_review_id IS NULL"),
        ),
        Index(
            "ix_verification_review_result",
            "verification_result_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": SCHEMA},
    )

    verification_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.verification_result.id",
            name="fk_verification_review_result_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    review_status: Mapped[VerificationReviewStatus] = mapped_column(
        Enum(VerificationReviewStatus, name="verification_review_status_enum", schema=SCHEMA),
        nullable=False,
    )
    reviewed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


__all__ = ["VerificationReview"]
