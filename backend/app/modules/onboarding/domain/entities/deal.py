"""``Deal`` — one financing need a company brought us — **owner: Developer 3B**
(L3-05).

Contract: ``docs/contracts/deal-and-buyer.md``. Architecture §3.3 ("The deal"),
§3.5, and migration 0018.

**A company has any number of deals, over time and at once** (architecture §3.3),
so ``company_id`` carries no uniqueness. It is a real foreign key to
``exporter_profile.customer_id`` with ``ON DELETE RESTRICT``: a company with
deals is not deletable, because deleting one would silently destroy the record of
what was financed.

**A deal is never deleted.** ``WITHDRAWN`` is how a deal ends, with a reason
(assumption A7), and the row stays. There is no delete route and no
``AppendOnlyModel`` either — the stage genuinely changes, and each change is a
history row (``dimension="deal"``), so the table is mutable while its history is
not.

**Nothing about the company lives here, and nothing about the deal lives on the
company.** A buyer failing a check is recorded against the buyer, a deal falling
through against the deal; neither touches ``exporter_profile`` (architecture §3.5,
decision 9). There is no "has a bad deal" field on the company record, and adding
one would be a contract change.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer

SCHEMA = "onboarding"


class Deal(AnerModel):
    __tablename__ = "deal"
    __table_args__ = (
        # Assumption A7: a withdrawal carries its reason, and nothing else does.
        # Both halves, so the column cannot fill up with reasons for live deals —
        # the same shape as `ck_exporter_profile_marker_reason`.
        CheckConstraint(
            "(stage = 'WITHDRAWN' AND withdrawal_reason IS NOT NULL)"
            " OR (stage <> 'WITHDRAWN' AND withdrawal_reason IS NULL)",
            name="ck_deal_withdrawal_reason",
        ),
        # One company's deals, newest first — what the Deals panel asks for.
        Index("ix_deal_company_recent", "company_id", "created_at"),
        # The open-work views filter by stage across companies.
        Index("ix_deal_stage", "stage"),
        {"schema": SCHEMA},
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_deal_company_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: A short human label, so a list of a company's deals is readable without
    #: opening each one ("Rotterdam shipment, March"). Not an identifier.
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    stage: Mapped[DealStage] = mapped_column(
        Enum(DealStage, name="deal_stage_enum", schema=SCHEMA, create_type=False),
        nullable=False,
        default=DealStage.OPEN,
    )
    #: Required exactly when `stage` is `WITHDRAWN` (assumption A7), enforced by
    #: `ck_deal_withdrawal_reason` as well as by the service.
    withdrawal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: When the deal reached `HANDED_OVER`. Phase 4 sets it; NULL until then, and
    #: NULL forever on a deal that was withdrawn instead.
    handed_over_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    buyer: Mapped[DealBuyer | None] = relationship(
        back_populates="deal",
        cascade="all, delete-orphan",
        # One buyer per deal (contract §3), so this is a scalar, not a list.
        uselist=False,
        lazy="selectin",
    )
