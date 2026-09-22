import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.cases.domain.entities.enums import ActorType, TimelineEventType
from app.platform.database.models import Base, UUIDPrimaryKeyMixin

SCHEMA = "cases"


class CaseTimelineEvent(UUIDPrimaryKeyMixin, Base):
    """One entry in a case's audit trail — append-only.

    Not built on `AppendOnlyModel`: that mixin's sole timestamp column is named
    `created_at`, and this table's is `occurred_at`. The append-only guarantee
    itself is unaffected — it comes from the `public.prevent_mutation()`
    trigger the migration attaches to the table, exactly as
    `AppendOnlyModel`-based tables get it, not from the base class.

    `case_id` is RESTRICT, not CASCADE: the timeline is the audit record of a
    case, and it must outlive any attempt to remove the case it describes —
    the same reasoning onboarding's `case_state_transition_case_id_fkey`
    documents.
    """

    __tablename__ = "case_timeline_event"
    __table_args__ = (
        Index("ix_case_timeline_event_case_id", "case_id"),
        Index("ix_case_timeline_event_case_occurred", "case_id", "occurred_at"),
        {"schema": SCHEMA},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.compliance_case.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[TimelineEventType] = mapped_column(
        Enum(TimelineEventType, name="timeline_event_type_enum", schema=SCHEMA), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    to_status: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="case_actor_type_enum", schema=SCHEMA), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
