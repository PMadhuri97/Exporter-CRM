"""``ExporterActivity`` — an append-only relationship-history log entry,
same base and enforcement pattern as ``OnboardingEvent``: a logged
call, meeting, email, note, task, or follow-up is never edited after the
fact. ``trg_exporter_activity_append_only`` (migration
``onboarding_0005_exporter_crm``) rejects UPDATE and DELETE at the database
level, reusing the shared ``public.prevent_mutation()`` function
``onboarding_event`` already relies on.

``customer_id`` points at a company that exists: migration 0014 added
``fk_exporter_activity_customer_id``, a real foreign key to
``exporter_profile.customer_id`` with ``ON DELETE RESTRICT``, declared on the
column below. This docstring used to claim the column was bare, for the same
(since-retired) reason ``ExporterContact``'s did — see that module's docstring
for what changed and why 0016 does not re-add the constraint.

``due_at`` is nullable and meaningful only for ``TASK``/``FOLLOW_UP`` entries;
it is left unconstrained at the database level (no CHECK tying it to
``activity_type``) since a CALL or NOTE logged with an incidental due date is
harmless, not a data-integrity violation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class ExporterActivity(AppendOnlyModel):
    __tablename__ = "exporter_activity"
    __table_args__ = (
        Index("ix_exporter_activity_customer_id", "customer_id"),
        # Migration 0008; declared so autogenerate does not propose dropping it.
        Index(
            "ix_exporter_activity_actor_due_at_pending",
            "actor_id",
            "due_at",
            postgresql_where=text("due_at IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    #: The company. `ON DELETE RESTRICT`: an activity is the relationship's
    #: record of what happened, and this table is append-only, so nothing may
    #: remove the company it happened to either.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_exporter_activity_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    activity_type: Mapped[ExporterActivityType] = mapped_column(
        Enum(ExporterActivityType, name="exporter_activity_type_enum", schema=SCHEMA),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # TEXT in the database
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["ExporterActivity"]
