"""``ExporterLifecycleHistory`` — one recorded move of an exporter's
``lifecycle_status``, append-only.

Same base and enforcement pattern as ``ExporterActivity`` and
``OnboardingEvent``: ``trg_exporter_lifecycle_history_append_only`` (migration
``onboarding_0011_e9_audit``) rejects UPDATE and DELETE at the database, reusing
the shared ``public.prevent_mutation()`` function both of those already rely on.

``customer_id`` is a bare, indexed UUID with no formal FK, for the same reason
``ExporterActivity.customer_id`` and ``ExporterContact.customer_id`` are bare —
see those modules' docstrings.

**Why this is not an ``onboarding_event`` row.** That was the first choice, and
``ExporterProfileService`` already holds a repository for it.
``onboarding_event.onboarding_request_id`` is NOT NULL with an FK to
``onboarding_request``, and an exporter profile does not require one:
``create_or_get_profile`` — the path behind ``POST /onboarding/exporters`` —
creates a profile and no request. Only ``create_lead`` creates both. Most
profiles in practice have no request, so lifecycle transitions written to
``onboarding_event`` would fail outright or be silently skipped for exactly the
sales-entered exporters whose provenance is least otherwise recorded. The
migration docstring has the measured numbers.

``from_status``/``to_status`` are plain strings rather than the
``ExporterLifecycleStatus`` enum on purpose: a history table must be able to
record a status that has just been added to the enum without needing its own
migration first, and it must be able to keep recording one that was later
removed. ``ExporterProfileService.transition_lifecycle_status`` validates the
edge before writing, so the values are enum members at the time they are stored.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"

#: ``event_type`` for a row written by ``transition_lifecycle_status``. A column
#: rather than an implied constant so a later writer (a bulk migration, an
#: automated re-KYC sweep) can be told apart from a person clicking a button.
LIFECYCLE_TRANSITION_EVENT = "lifecycle_transition"


class ExporterLifecycleHistory(AppendOnlyModel):
    __tablename__ = "exporter_lifecycle_history"
    __table_args__ = (
        Index("ix_exporter_lifecycle_history_customer_id", "customer_id"),
        Index(
            "ix_exporter_lifecycle_history_recent",
            "customer_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        # Serves the ANER-4.2-S1T2 completion hook — a consumer watching for
        # COMPLIANCE_REVIEW -> ONBOARDED.
        Index(
            "ix_exporter_lifecycle_history_to_status",
            "to_status",
            text("created_at DESC"),
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str] = mapped_column(String(64), nullable=False)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


__all__ = ["ExporterLifecycleHistory", "LIFECYCLE_TRANSITION_EVENT"]
