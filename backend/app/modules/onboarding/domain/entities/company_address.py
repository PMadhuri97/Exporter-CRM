"""``CompanyAddress`` — one of a company's addresses.

A company holds many addresses, each of a type (``CompanyAddressType``: registered,
billing, shipping, factory or warehouse, correspondence), and at most one **default**
per type among the active ones (``uq_company_address_default_per_type``). Any company
may hold one — a foreign buyer with no GSTIN included.

Addresses are **deactivated, never deleted** (``trg_company_address_no_delete``): a GST
branch or a document may point at one, and every change is in the company's history
(dimension ``address``).

A GST registration may name the address it trades from (``exporter_gstin.address_id``);
the foreign key carries the company too, so a branch can only point at its own
company's address.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

ADDRESS_TYPES = ("REGISTERED", "BILLING", "SHIPPING", "FACTORY_WAREHOUSE", "CORRESPONDENCE")


class CompanyAddress(AnerModel):
    __tablename__ = "company_address"
    __table_args__ = (
        Index("ix_company_address_customer_id", "customer_id"),
        # The target of the GST branch's (address_id, customer_id) foreign key.
        UniqueConstraint("id", "customer_id", name="uq_company_address_id_customer_id"),
        Index(
            "uq_company_address_default_per_type",
            "customer_id",
            "address_type",
            unique=True,
            postgresql_where=text("is_default AND is_active"),
        ),
        CheckConstraint(
            "address_type IN ("
            + ", ".join(f"'{value}'" for value in ADDRESS_TYPES)
            + ")",
            name="ck_company_address_type",
        ),
        # A deactivated address is nobody's default.
        CheckConstraint("is_active OR NOT is_default", name="ck_company_address_default_active"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_company_address_customer_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: ``CompanyAddressType``.
    address_type: Mapped[str] = mapped_column(String(24), nullable=False)
    line1: Mapped[str] = mapped_column(String(255), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: ISO 3166-1 alpha-2.
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = ["ADDRESS_TYPES", "CompanyAddress"]
