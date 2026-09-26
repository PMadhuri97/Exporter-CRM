"""``ExporterActivity`` — an append-only relationship-history log entry
(EXP-1), same base and enforcement pattern as ``OnboardingEvent``: a logged
call, meeting, email, note, task, or follow-up is never edited after the
fact. ``trg_exporter_activity_append_only`` (migration
``onboarding_0005_exporter_crm``) rejects UPDATE and DELETE at the database
level, reusing the shared ``public.prevent_mutation()`` function
``onboarding_event`` already relies on.

``customer_id`` is a bare, indexed UUID with no formal FK, for the same
reason ``ExporterContact.customer_id`` is bare — see that module's docstring.

``due_at`` is nullable and meaningful only for ``TASK``/``FOLLOW_UP`` entries;
it is left unconstrained at the database level (no CHECK tying it to
``activity_type``) since a CALL or NOTE logged with an incidental due date is
harmless, not a data-integrity violation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class ExporterActivity(AppendOnlyModel):
    __tablename__ = "exporter_activity"
    __table_args__ = (
        Index("ix_exporter_activity_customer_id", "customer_id"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    activity_type: Mapped[ExporterActivityType] = mapped_column(
        Enum(ExporterActivityType, name="exporter_activity_type_enum", schema=SCHEMA),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["ExporterActivity"]
