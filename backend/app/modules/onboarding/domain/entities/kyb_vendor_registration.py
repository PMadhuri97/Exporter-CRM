"""KYB Vendor Registration entity — S1T4.

The registry of KYB vendor adapters known to the platform. One row per vendor.
Populated at service startup from each adapter's ``declare_capabilities()`` and
kept current by the health monitor. The onboarding orchestration engine reads
this table to pick the right vendor for a customer's registration country and
entity type.

Mirrors ``rails.rail_registration`` (Epic 2.4 S1T3): a ``capability_declaration``
JSONB blob holds the full declaration verbatim, while the fields the registry
actually routes and monitors on are promoted to columns.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum

SCHEMA = "onboarding"


class KybVendorRegistration(AnerModel):
    """A registered KYB vendor adapter and its declared capabilities."""

    __tablename__ = "kyb_vendor_registration"
    __table_args__ = (
        UniqueConstraint("vendor_id", name="uq_kyb_vendor_registration_vendor_id"),
        CheckConstraint(
            "octet_length(capability_declaration::text) <= 65536",
            name="ck_kyb_vendor_registration_cap_decl_size",
        ),
        Index("ix_kyb_vendor_registration_health_status", "health_status"),
        {"schema": SCHEMA},
    )

    # Stable unique identifier for the vendor. Examples: "middesk", "trulioo".
    vendor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # ISO 3166-1 alpha-2 country codes, stored upper-cased.
    supported_countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Onboarding entity-type vocabulary (CORPORATION, PARTNERSHIP, ...), upper-cased.
    # A vendor matches only the entity types it explicitly lists; an empty list
    # matches nothing.
    supported_entity_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    processing_mode: Mapped[KYBVendorProcessingMode] = mapped_column(
        Enum(KYBVendorProcessingMode, name="kyb_vendor_processing_mode_enum", schema=SCHEMA),
        nullable=False,
    )

    # Operational state, owned by the health monitor — never reset by re-registration.
    health_status: Mapped[VendorHealthStatusEnum] = mapped_column(
        Enum(VendorHealthStatusEnum, name="kyb_vendor_health_status_enum", schema=SCHEMA),
        nullable=False,
        server_default="HEALTHY",
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The full KYBVendorCapabilityDeclaration as received, for audit and future fields.
    capability_declaration: Mapped[dict] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"KybVendorRegistration(vendor_id={self.vendor_id!r}, "
            f"health_status={self.health_status!r})"
        )


__all__ = ["KybVendorRegistration"]
