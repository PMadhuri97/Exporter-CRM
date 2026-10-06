"""Persistent compliance-review checklist state for the Exporter CRM."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

#: The four statuses a checklist decision may carry — the API's `Literal` and
#: `ck_screening_review_item_status` (migration onboarding_0021_verif_review).
SCREENING_STATUSES: tuple[str, ...] = ("NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT")


class ScreeningReviewItem(AnerModel):
    """One compliance-checklist decision, as taken. Append-only.

    There is deliberately no unique constraint on ``(customer_id, item_key)``.
    Each decision on an item is its own row, and the current state of an item is
    the most recent row for it — see
    ``ScreeningReviewService.list_review_items``. A reviewer marking an item
    ``PASSED`` after someone else marked it ``FAILED`` adds a row; it does not
    overwrite who failed it, or when, or why (onboarding_0011_review_log).

    ``trg_screening_review_item_append_only`` rejects every ``UPDATE`` and
    ``DELETE`` on this table via the shared ``public.prevent_mutation()``, the
    same guard ``onboarding_event`` and ``exporter_activity`` carry. Mutating a
    loaded instance and flushing it raises at the database, not here — the rule
    does not depend on callers coming through this module's service.

    Stays on ``AnerModel`` rather than ``AppendOnlyModel`` despite being
    append-only: ``AppendOnlyModel`` has no ``updated_at``, and
    ``ScreeningReviewItemResponse`` requires that field. It is always equal to
    ``created_at`` here.

    ``customer_id`` references the company. The database constraint
    (``fk_screening_review_item_customer_id``) has existed since migration
    0014; declaring it here only makes the model say what the table already
    enforces, so it needs no migration.
    ``status`` is one of ``SCREENING_STATUSES`` at the database too
    (``ck_screening_review_item_status``, migration 0021).

    ``evidence_refs`` is what an answer rests on, in the
    verification result's ``{type, ref}`` shape — ``document`` (a ``crm_document.id``
    of the company) or ``url`` (http(s)). Optional. Added by migration
    ``onboarding_0024_screen_evidence`` as ``NOT NULL DEFAULT '[]'``: the DDL filled
    the existing rows without firing the append-only trigger, so no row was updated.

    ``cycle_id`` is the check cycle the answer belongs to, stamped by
    ``ScreeningReviewService``. ``NULL`` on rows written before cycles existed reads as
    the company's cycle 1. The composite foreign key ``fk_screening_review_item_cycle``
    ties it to a cycle **of the same company**.
    """

    __tablename__ = "screening_review_item"
    __table_args__ = (
        Index("ix_screening_review_customer_id", "customer_id"),
        # Serves the DISTINCT ON in list_review_items without a sort. Column
        # order and direction mirror that query exactly.
        Index(
            "ix_screening_review_customer_item_recent",
            "customer_id",
            "item_key",
            text("created_at DESC"),
            text("id DESC"),
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in SCREENING_STATUSES) + ")",
            name="ck_screening_review_item_status",
        ),
        CheckConstraint(  # 0024
            "jsonb_typeof(evidence_refs) = 'array'",
            name="ck_screening_review_item_evidence_refs_array",
        ),
        ForeignKeyConstraint(  # 0025
            ["cycle_id", "customer_id"],
            [f"{SCHEMA}.check_cycle.id", f"{SCHEMA}.check_cycle.company_id"],
            name="fk_screening_review_item_cycle",
            ondelete="RESTRICT",
        ),
        Index(  # 0025
            "ix_screening_review_item_cycle_id",
            "cycle_id",
            postgresql_where=text("cycle_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_screening_review_item_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    item_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEEDS_REVIEW")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``[{"type": "document" | "url", "ref": str}, ...]`` — optional.
    evidence_refs: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: The check cycle this answer belongs to; ``NULL`` = the company's cycle 1.
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class BankActivityFinding(AnerModel):
    """Provider-originated bank/activity signal. The CRM only exposes read APIs.

    Real Surepass/Finpass ingestion can write these rows later without changing
    the CRM contract or UI. No fake findings are generated.
    """

    __tablename__ = "bank_activity_finding"
    __table_args__ = (
        Index("ix_bank_activity_finding_customer_id", "customer_id"),
        Index("ix_bank_activity_finding_customer_status", "customer_id", "status"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="REVIEW")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["SCREENING_STATUSES", "ScreeningReviewItem", "BankActivityFinding"]
