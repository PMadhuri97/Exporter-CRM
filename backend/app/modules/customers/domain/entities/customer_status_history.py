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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.customers.domain.entities.lifecycle_enums import (
    CustomerStatus,
    RestrictionLevel,
)
from app.platform.database.models import AppendOnlyModel

SCHEMA = "customers"

#: Long enough to say what changed and why. The rule binds a record a regulator
#: reads, not a field an operator clears to get past a form.
MIN_REASON_DETAIL_LENGTH = 20

#: Statuses whose entry requires dual authorisation, and from which a return to
#: ACTIVE is a reinstatement and requires it too.
CONSEQUENTIAL_STATUSES = (CustomerStatus.SUSPENDED, CustomerStatus.RESTRICTED)


class CustomerStatusHistory(AppendOnlyModel):
    """Every change to a customer's standing, in order.

    Append-only. Current status is the latest row, not a column somebody can
    overwrite: a suspension that can be edited out of the record is not a
    suspension anyone can defend at audit.

    `effective_until`, `customer_notified_at` and `notification_ref` are
    therefore written when the row is inserted. A status that later acquires an
    end date, or a notification that lands afterwards, is a new row.

    TODO(AL-737): the supersede-on-notify write path and its repository.
    """

    __tablename__ = "customer_status_history"
    __table_args__ = (
        Index(
            "ix_customer_status_history_customer_time",
            "customer_id",
            "effective_from",
        ),
        CheckConstraint(
            f"char_length(btrim(reason_detail)) >= {MIN_REASON_DETAIL_LENGTH}",
            name="ck_customer_status_history_reason_detail_substantive",
        ),
        # A restriction says to what level; nothing else carries one.
        CheckConstraint(
            "(restriction_level IS NOT NULL) = (to_status = 'RESTRICTED')",
            name="ck_customer_status_history_restriction_level_paired",
        ),
        # Suspending or restricting a live customer, and reinstating one, are
        # each consequential enough to require a second pair of eyes. The
        # `from_status IS NOT NULL` guard is load-bearing: NULL IN (...) is NULL,
        # and a CHECK passes on NULL, so without it the first row of a
        # customer's history would slip past this rule entirely.
        CheckConstraint(
            "NOT ("
            " to_status IN ('SUSPENDED', 'RESTRICTED')"
            " OR ("
            "  to_status = 'ACTIVE'"
            "  AND from_status IS NOT NULL"
            "  AND from_status IN ('SUSPENDED', 'RESTRICTED')"
            " )"
            ") OR approval_request_id IS NOT NULL",
            name="ck_customer_status_history_consequential_change_approved",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_customer_status_history_period_ordered",
        ),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Null on the first row of a customer's history, which has no prior status.
    from_status: Mapped[CustomerStatus | None] = mapped_column(
        Enum(CustomerStatus, name="customer_status_enum", schema=SCHEMA), nullable=True
    )
    to_status: Mapped[CustomerStatus] = mapped_column(
        Enum(CustomerStatus, name="customer_status_enum", schema=SCHEMA), nullable=False
    )
    restriction_level: Mapped[RestrictionLevel | None] = mapped_column(
        Enum(RestrictionLevel, name="customer_restriction_level_enum", schema=SCHEMA),
        nullable=True,
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_detail: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    initiated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_review_ref: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(f"{SCHEMA}.customer_review.review_ref", ondelete="RESTRICT"),
        nullable=True,
    )
    customer_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notification_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
