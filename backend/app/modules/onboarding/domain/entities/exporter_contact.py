"""``ExporterContact`` — a contact person for an exporter relationship (EXP-1).

``customer_id`` is a bare, indexed UUID with no formal FK — the same
convention ``cases.ComplianceCase`` uses for ``customer_id``/``settlement_id``/
``onboarding_id`` (see that entity's module docstring): a contact belongs to
the *exporter relationship*, which may exist (as a bare Lead) before any
``ExporterProfile`` row is even created, so a hard FK to ``exporter_profile``
would forbid recording a contact for a lead that hasn't been profiled yet.

At most one contact per ``customer_id`` may have ``is_primary_contact=True`` —
enforced by a partial unique index (migration ``onboarding_0005_exporter_crm``)
and, redundantly, by ``ExporterContactActivityService.add_contact`` demoting
any existing primary in the same transaction before the DB constraint is ever
reached in normal operation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, String
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
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


__all__ = ["ExporterContact"]
