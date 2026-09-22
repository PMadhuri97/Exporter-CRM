from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import (
    RestrictionLevel,
    ReviewAction,
    TriggerSeverity,
)
from app.platform.database.models import AnerModel

SCHEMA = "customers"


class ReviewTriggerDefinition(AnerModel):
    """A configured event that causes an unscheduled review.

    Version-controlled configuration seeded to this table, not operator-authored
    data: `trigger_code` is the stable identifier a seed file and an emitting
    module both refer to.
    """

    __tablename__ = "review_trigger_definition"
    __table_args__ = (
        UniqueConstraint("trigger_code", name="uq_review_trigger_definition_code"),
        # A trigger that restricts a live customer before any human looks must
        # say which restriction; one that does not must not carry a level.
        CheckConstraint(
            "auto_restrict = (restriction_level IS NOT NULL)",
            name="ck_review_trigger_definition_restriction_paired",
        ),
        {"schema": SCHEMA},
    )

    trigger_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_epic: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[TriggerSeverity] = mapped_column(
        Enum(TriggerSeverity, name="review_trigger_severity_enum", schema=SCHEMA),
        nullable=False,
    )
    review_action: Mapped[ReviewAction] = mapped_column(
        Enum(ReviewAction, name="review_trigger_action_enum", schema=SCHEMA),
        nullable=False,
    )
    # True only where the risk of the customer continuing outweighs the cost of
    # interrupting them — a confirmed sanctions match, a struck-off registry status.
    auto_restrict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    restriction_level: Mapped[RestrictionLevel | None] = mapped_column(
        Enum(RestrictionLevel, name="customer_restriction_level_enum", schema=SCHEMA),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
