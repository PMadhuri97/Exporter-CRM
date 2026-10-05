"""``FollowUpCompletion`` — the record that a follow-up was dealt with.

A follow-up is an ``ExporterActivity`` with a ``due_at``: something someone said
they would do. A completion is one append-only row saying that promise was dealt
with, and how. The contract is ``docs/contracts/engagement.md`` §5.

**It is a new row, never an edit.** ``exporter_activity`` is append-only, enforced
by ``trg_exporter_activity_append_only``, so nothing marks an activity as done —
there is no ``completed_at`` on the activity and there must never be one.
Architecture §9.3's "Watch out for" lists that mistake first because it is the one
this design invites. This table is append-only too
(``trg_follow_up_completion_append_only``, via the shared
``public.prevent_mutation()``), so a correction is a **new activity** plus its own
completion.

**The table already existed when this file was written.** Migration 0016
created it; follow-ups add no migration at all. This class
maps what the DDL built and adds nothing: the columns, the two foreign keys, the
unique constraint on ``activity_id`` and the ``next_due_at`` check are all declared
here so the ORM says what the database says, and every one of them is already in
0016. Declaring them does not create them a second time — nothing in this
repository runs ``metadata.create_all``.

``customer_id`` is denormalised from the activity on purpose (contract §5.2): one
company's completions then need no join, and the foreign key keeps it honest.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.platform.database.models import AppendOnlyModel

SCHEMA = "onboarding"


class FollowUpOutcome(str, enum.Enum):
    """How a follow-up was dealt with — ``docs/contracts/engagement.md`` §5.3.

    Lives here rather than in ``engagement_enums.py`` because that file holds the
    conversation gauge's values. Migration 0016 created
    the Postgres type ``onboarding.follow_up_outcome_enum`` and no Python enum; this
    is it.

    ``RESCHEDULED`` is the only value that carries ``next_due_at``, and it is not a
    way to move a due date: the activity keeps the date it was promised for, and
    ``FollowUpService`` logs a **new** activity for the new one.
    """

    DONE = "DONE"
    NO_ANSWER = "NO_ANSWER"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class FollowUpCompletion(AppendOnlyModel):
    """One completion per follow-up. Append-only, at both layers.

    ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and the
    database trigger refuses both whatever code tries — the same pair of guarantees
    ``ExporterActivity`` and ``ExporterLifecycleHistory`` have.
    """

    __tablename__ = "follow_up_completion"
    __table_args__ = (
        # One completion per follow-up. A reschedule is a new activity, so nothing
        # legitimate completes the same activity twice; a second attempt is a
        # refusal, never an upsert (contract §5.4).
        UniqueConstraint("activity_id", name="uq_follow_up_completion_activity_id"),
        CheckConstraint(
            "(outcome = 'RESCHEDULED' AND next_due_at IS NOT NULL)"
            " OR (outcome <> 'RESCHEDULED' AND next_due_at IS NULL)",
            name="ck_follow_up_completion_next_due",
        ),
        # One company's completions, newest first. `completed_at` defaults to the
        # transaction clock, so `id` breaks the tie and the order is deterministic
        # rather than chronological — the caveat every index in this schema carries.
        Index(
            "ix_follow_up_completion_customer_recent",
            "customer_id",
            text("completed_at DESC"),
            text("id DESC"),
        ),
        {"schema": SCHEMA},
    )

    #: The follow-up this completes. `ON DELETE RESTRICT`: the activity is
    #: append-only and this row is the record that it was dealt with, so neither may
    #: outlive the other.
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_activity.id",
            name="fk_follow_up_completion_activity_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: The company. Denormalised from the activity (contract §5.2) so one company's
    #: completions need no join; the foreign key keeps it honest.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_follow_up_completion_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    outcome: Mapped[FollowUpOutcome] = mapped_column(
        Enum(FollowUpOutcome, name="follow_up_outcome_enum", schema=SCHEMA),
        nullable=False,
    )
    #: What happened, in the actor's words.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The moment it was moved to — set **exactly** when the outcome is
    #: `RESCHEDULED` (`ck_follow_up_completion_next_due`).
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Who, from their login session — never from a request body (architecture §7.5).
    #: `NULL` means the platform itself acted, the same meaning `actor_id` carries
    #: everywhere else in this CRM.
    completed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["FollowUpCompletion", "FollowUpOutcome"]
