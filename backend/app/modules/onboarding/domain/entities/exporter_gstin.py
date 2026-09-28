"""``ExporterGstin`` — one GST registration held by a company (L2-06).

**Owner: Developer 2.** A company holds one GSTIN per state, so several rows
per company; the same GSTIN twice on one company is refused
(``uq_exporter_gstin_customer_gstin``). The same GSTIN on two *different*
companies is allowed by the database on purpose: it is a warning the service
reports, never a constraint (architecture decision 4).

The format is checked twice — by ``domain/tax_identifiers.py`` for a clean
422, and by ``ck_exporter_gstin_format`` so nothing malformed can be written
around the service. That a GSTIN embeds its company's PAN is the service's
rule: it spans two tables.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class ExporterGstin(AnerModel):
    __tablename__ = "exporter_gstin"
    __table_args__ = (
        UniqueConstraint("customer_id", "gstin", name="uq_exporter_gstin_customer_gstin"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.exporter_profile.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)


__all__ = ["ExporterGstin"]
