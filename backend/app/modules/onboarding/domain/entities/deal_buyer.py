"""``DealBuyer`` — who the exporter is selling to on one deal — **owner:
Developer 3B** (L3-06).

Contract: ``docs/contracts/deal-and-buyer.md`` §3. Architecture §3.3, §3.5,
decision 9, migration 0018.

**Its own table, not columns on ``deal``.** Developer 4 attaches buyer checks to
*the buyer* (plan §8.2): a verification result needs something with an id to point
at, and an ``entity_reference`` pointing at the deal would make "a check about the
buyer" and "a check about the deal" indistinguishable. A separate row gives the
buyer its own identity without pretending it is a company — it is not in
``exporter_profile``, it has no journey, and it is never screened as if it were a
client.

**One buyer per deal**, enforced by a unique constraint on ``deal_id``. A deal
with two buyers is two deals: financing one shipment for two buyers is not
something the prototype models, and a list where "the buyer" is ambiguous would
make the handover payload ambiguous too (architecture §3.6).

The buyer's problems stay here. A buyer failing a check is recorded against this
row; the company's record is unchanged (architecture §3.5).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.deal import Deal

SCHEMA = "onboarding"


class DealBuyer(AnerModel):
    __tablename__ = "deal_buyer"
    __table_args__ = (
        UniqueConstraint("deal_id", name="uq_deal_buyer_deal_id"),
        # Two letters, uppercase: ISO-3166-1 alpha-2, the same rule
        # `exporter_profile.country` uses, so one country is not stored three ways.
        CheckConstraint(
            "country ~ '^[A-Z]{2}$'",
            name="ck_deal_buyer_country_iso",
        ),
        {"schema": SCHEMA},
    )

    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.deal.id",
            name="fk_deal_buyer_deal_id",
            # CASCADE, unlike the deal's own FK to the company: a buyer has no
            # meaning without its deal, and a deal is never deleted anyway
            # (`WITHDRAWN` is how one ends), so this only matters if a test or a
            # future cleanup removes a deal outright.
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    #: Whatever the buyer's own jurisdiction issues — not validated by shape,
    #: because a buyer is foreign by definition and India's PAN/GSTIN rules do
    #: not apply to it.
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    deal: Mapped[Deal] = relationship(back_populates="buyer")
