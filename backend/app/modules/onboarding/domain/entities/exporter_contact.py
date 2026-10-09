"""``ExporterContact`` — a contact person for an exporter relationship.

``customer_id`` points at a company that exists: migration 0014 added
``fk_exporter_contact_customer_id`` (its ``_LINKED`` tuple, step 4), a real
foreign key to ``exporter_profile.customer_id`` with ``ON DELETE RESTRICT``. It
is declared on the column below so the ORM says the same thing the database
does.

This docstring used to say the opposite — "a bare, indexed UUID with no formal
FK", on the reasoning that a contact could be recorded for a Lead before any
``ExporterProfile`` row existed. That reasoning stopped applying when the
company record became the CRM's own table (``docs/contracts/company-record.md``
§1): a company *is* an ``exporter_profile`` row from the moment it is created,
Lead or not, so there is no state in which a contact has a company id but no
company. The constraint has its own direct-SQL test; the
constraint itself was already there, and 0016 does not re-add it.

At most one contact per ``customer_id`` may have ``is_primary_contact=True`` —
enforced by a partial unique index (migration ``onboarding_0005_exporter_crm``)
and, redundantly, by ``ExporterContactActivityService.add_contact`` demoting
any existing primary in the same transaction before the DB constraint is ever
reached in normal operation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class ExporterContact(AnerModel):
    __tablename__ = "exporter_contact"
    __table_args__ = (
        Index("ix_exporter_contact_customer_id", "customer_id"),
        # Partial unique index: at most one primary contact per customer_id.
        # A plain UniqueConstraint on (customer_id, is_primary_contact) would
        # also forbid a second *non*-primary contact for the same customer,
        # which is the common case — same partial-index pattern as
        # onboarding_request's uq_onboarding_request_active_customer.
        Index(
            "uq_exporter_contact_primary_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("is_primary_contact = true"),
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'LEFT_COMPANY')", name="ck_exporter_contact_status"
        ),
        # Only someone still reachable can be the person to reach.
        CheckConstraint(
            "status = 'ACTIVE' OR is_primary_contact = false",
            name="ck_exporter_contact_primary_is_active",
        ),
        {"schema": SCHEMA},
    )

    #: The company. `ON DELETE RESTRICT`, so a company with contacts cannot be
    #: deleted out from under them — the same rule every other child of
    #: `exporter_profile` got in 0014.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_exporter_contact_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: ``ContactStatus``: ACTIVE, INACTIVE or LEFT_COMPANY, with when and why it changed.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: When someone last confirmed these details are right, and who.
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = ["ExporterContact"]
