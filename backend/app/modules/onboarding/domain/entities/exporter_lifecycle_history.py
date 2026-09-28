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

**Every way a profile gets a status is recorded, not only transitions.**
``create_or_get_profile`` accepts a ``lifecycle_status`` from the caller, so a
profile can be born at any status — including ``ONBOARDED``. Recording only
``transition_lifecycle_status`` would leave exactly that case with no row: no
record of who put the exporter there, and nothing for the ANER-4.2-S1T2 hook to
see. Creation therefore writes a ``lifecycle_initial`` row with
``from_status = NULL``. ``from_status`` and ``actor_id`` are nullable for that
reason, matching ``onboarding_event``: ``NULL`` from means "entered at
creation", ``NULL`` actor means an internal caller that supplied none.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"

#: ``event_type`` for a row written by ``transition_lifecycle_status``. A column
#: rather than an implied constant so a later writer (a bulk migration, an
#: automated re-KYC sweep) can be told apart from a person clicking a button.
LIFECYCLE_TRANSITION_EVENT = "lifecycle_transition"

#: ``event_type`` for the row written when a profile is created at a status
#: (``from_status`` is ``NULL``).
LIFECYCLE_INITIAL_EVENT = "lifecycle_initial"

#: ``dimension`` for the company's main journey (LEAD -> PROSPECT -> CUSTOMER,
#: and the ten-status lifecycle it replaces). The only dimension written today.
#:
#: The full list is owned by ``docs/contracts/history-row.md``, not by this
#: module: the gauges belong to Developers 2, 3 and 4, and each adds its own
#: constant next to the service that writes it. A dimension is a plain string
#: in the database precisely so adding one needs no migration here.
HISTORY_DIMENSION_JOURNEY = "journey"


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
        # One company's history filtered to one gauge — what a gauge panel asks.
        Index(
            "ix_exporter_lifecycle_history_dimension_recent",
            "customer_id",
            "dimension",
            text("created_at DESC"),
            text("id DESC"),
        ),
        # One deal's history. Partial: `deal_id` is NULL on every
        # company-level row, and indexing those NULLs would double the index
        # for entries no query can use.
        Index(
            "ix_exporter_lifecycle_history_deal_recent",
            "deal_id",
            text("created_at DESC"),
            postgresql_where=text("deal_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    #: Which row of the model changed — see ``HISTORY_DIMENSION_JOURNEY`` and
    #: ``docs/contracts/history-row.md``. No server default: the column had one
    #: for the length of migration 0013's backfill and then lost it, so that a
    #: writer which forgets the dimension fails loudly instead of silently
    #: recording a journey move.
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)

    #: The deal this row is about, when it is about one. ``NULL`` for every
    #: company-level change. Bare uuid with no FK, like ``customer_id``.
    deal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Why, in the actor's words. Required by the service for the moves section
    #: 3 of the architecture marks as needing one (setting a marker, withdrawing
    #: a deal, flagging or reopening a background check); nullable in the
    #: database because most moves do not need one.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


__all__ = [
    "HISTORY_DIMENSION_JOURNEY",
    "LIFECYCLE_INITIAL_EVENT",
    "LIFECYCLE_TRANSITION_EVENT",
    "ExporterLifecycleHistory",
]
