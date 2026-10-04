"""``TradeRelationship`` — one record per (seller, buyer) pair — **owner:
Developer 3** (allocation task 3.18, plan P5-1).

Two companies either trade with each other or they do not, and when they do there is
one relationship however many deals it carries. That is the whole table: the pair,
and where the record came from.

**No column on ``deal``** (allocation §1, adjustment 1, departing from P5-1's
``deal.relationship_id``). A deal already names both parties —
``company_id`` and ``buyer_company_id`` — so the relationship is *derivable* from
the deal, and a stored link would be a second copy of the same fact, able to drift
from it. ``get_or_create`` on the pair is what callers use instead.

``source`` and ``source_ref`` are on every new table in this lane (BQ-7): a row
created by the backfill (task 3.23) must be distinguishable from one created when a
deal recorded its buyer, because the two mean different things about how much we
know.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"


class TradeRelationship(AnerModel):
    __tablename__ = "trade_relationship"
    __table_args__ = (
        # One relationship per ordered pair. Ordered, not symmetric: A selling to B is
        # a different relationship from B selling to A — different invoices, different
        # risk — and a company really can be on both sides with the same counterparty.
        UniqueConstraint(
            "seller_company_id",
            "buyer_company_id",
            name="uq_trade_relationship_pair",
        ),
        # A company does not trade with itself. The same rule
        # `ck_deal_buyer_is_not_the_seller` applies to a deal, restated here because a
        # relationship can also be created by the backfill, which does not go through
        # a deal.
        CheckConstraint(
            "seller_company_id <> buyer_company_id",
            name="ck_trade_relationship_not_self",
        ),
        # The two read directions (task 3.20): "who does this company sell to" and
        # "who does it buy from".
        Index("ix_trade_relationship_seller", "seller_company_id", "created_at"),
        Index("ix_trade_relationship_buyer", "buyer_company_id", "created_at"),
        {"schema": SCHEMA},
    )

    seller_company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_trade_relationship_seller",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    buyer_company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.exporter_profile.customer_id",
            name="fk_trade_relationship_buyer",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    #: Who created it. A plain string like every other ``actor_id`` here: a migration
    #: or a backfill is not a user.
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: How the row came to exist — BQ-7. ``deal_buyer_recorded`` when a deal named its
    #: buyer company, ``backfill`` when task 3.23 reconstructed it from existing deals.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The thing within that source: a deal id, or a backfill run id.
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


__all__ = ["TradeRelationship"]
