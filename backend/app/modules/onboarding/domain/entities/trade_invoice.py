"""``TradeInvoice`` and ``TradeInvoiceOutcome`` — what a pair has traded, and how it
went — **owner: Developer 3** (allocation task 3.19, plan P5-2).

An invoice is a **fact about the past**: it was issued, for an amount, in a currency,
on a date. Its *identity* — which relationship, which number, which date, how much —
is frozen once written by ``trg_trade_invoice_identity_immutability``, because an
invoice whose amount could be edited afterwards is not evidence of anything. What
changes is its **outcome**, and that is an append-only superseding chain, exactly the
shape ``verification_review`` uses for the same reason: a payment story is a sequence
of things we learned, and the earlier belief is part of the record.

Currency is stored and never converted (decision IQ-4)
------------------------------------------------------
An invoice in AED stays in AED. No conversion, no reporting currency, no stored rate.
A converted figure is only as good as the rate and the date behind it, and a trade
history that quietly reported everything in USD would invite comparisons between
numbers that were never comparable. A reader who needs a total across currencies has
to decide the rate themselves, which is the honest position.

``deal_id`` is nullable
-----------------------
Past trade — what the two companies did before they came to us — has no deal
(task 3.21). That is the point of recording it: a relationship with a settled history
is worth more than a new one, and the evidence for it predates us.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.onboarding.domain.entities.trade_enums import (
    TradePaymentStatus,
    TradeProofStatus,
)
from app.platform.database.models import AnerModel, AppendOnlyModel

SCHEMA = "onboarding"

#: Longest currency code stored. ISO 4217 is three characters; the column is sized for
#: it and `ck_trade_invoice_currency` holds the shape.
CURRENCY_LENGTH = 3


class TradeInvoice(AnerModel):
    __tablename__ = "trade_invoice"
    __table_args__ = (
        # One invoice number per relationship. Not globally unique: two different
        # exporters may both number an invoice "001", and they are different invoices.
        UniqueConstraint(
            "relationship_id", "invoice_number", name="uq_trade_invoice_number"
        ),
        # `(id, relationship_id)`, so an outcome's FK can be composite and the chain
        # cannot be attached to an invoice of another relationship.
        UniqueConstraint(
            "id", "relationship_id", name="uq_trade_invoice_id_relationship"
        ),
        # ISO 4217: three upper-case letters. Checked here as well as in the service
        # because a currency is meaningless if it is not a code somebody can look up,
        # and this column is never converted — so a wrong code is permanent.
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_trade_invoice_currency"
        ),
        # An invoice is for a positive amount. A zero or negative invoice is a credit
        # note or a mistake, and neither is this table's subject.
        CheckConstraint("amount > 0", name="ck_trade_invoice_amount_positive"),
        Index("ix_trade_invoice_relationship", "relationship_id", text("invoice_date DESC")),
        # The deals that produced an invoice, for the deal page's panel (task 3.22).
        Index(
            "ix_trade_invoice_deal",
            "deal_id",
            postgresql_where=text("deal_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    relationship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.trade_relationship.id",
            name="fk_trade_invoice_relationship",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    #: The deal this invoice came from, when it came from one. ``NULL`` for past trade
    #: recorded against the relationship (task 3.21). A bare uuid with no FK, like
    #: ``exporter_lifecycle_history.deal_id``: losing the invoice because a deal was
    #: cleaned up would be worse than losing the link.
    deal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: The invoiced amount, exact. ``Numeric`` and never a float: money compared or
    #: summed as binary floating point is money reported wrongly.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    #: ISO 4217, stored as issued and **never converted** (decision IQ-4).
    currency: Mapped[str] = mapped_column(String(CURRENCY_LENGTH), nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: BQ-7: how this row came to exist.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TradeInvoiceOutcome(AppendOnlyModel):
    """One thing we learned about an invoice. Append-only, superseding chain.

    The same shape as ``verification_review``, and for the same reason: a correction
    is a **new** row naming the one it replaces, so the record says what we believed
    and when we stopped believing it. Nothing is edited and nothing is deleted —
    ``trg_trade_invoice_outcome_append_only`` enforces that at the database.

    Exactly one row per invoice has ``supersedes_outcome_id IS NULL`` (the chain's
    head, by ``uq_trade_invoice_outcome_first``), and each later row supersedes
    exactly one earlier row (``uq_trade_invoice_outcome_supersedes``). Together those
    make the chain a line rather than a tree: two people cannot each correct the same
    outcome without one of them seeing the other's, which is the race the equivalent
    rule prevents for verification reviews.
    """

    __tablename__ = "trade_invoice_outcome"
    __table_args__ = (
        UniqueConstraint(
            "id", "invoice_id", name="uq_trade_invoice_outcome_id_invoice"
        ),
        UniqueConstraint(
            "supersedes_outcome_id", name="uq_trade_invoice_outcome_supersedes"
        ),
        # The superseded row must belong to the same invoice — composite, so a chain
        # cannot be spliced across invoices.
        ForeignKeyConstraint(
            ["supersedes_outcome_id", "invoice_id"],
            [
                f"{SCHEMA}.trade_invoice_outcome.id",
                f"{SCHEMA}.trade_invoice_outcome.invoice_id",
            ],
            name="fk_trade_invoice_outcome_supersedes",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "supersedes_outcome_id IS NULL OR supersedes_outcome_id <> id",
            name="ck_trade_invoice_outcome_not_self",
        ),
        # A correction says why. The first outcome needs no note; one that overrules an
        # earlier belief does, because "we changed our mind" without a reason is not a
        # record anyone can act on later.
        CheckConstraint(
            "supersedes_outcome_id IS NULL"
            " OR (evidence_note IS NOT NULL AND btrim(evidence_note) <> '')",
            name="ck_trade_invoice_outcome_supersede_note",
        ),
        # PARTIAL carries how much was paid; nothing else may claim an amount it did
        # not receive. A negative amount paid is never right.
        CheckConstraint(
            "amount_paid IS NULL OR amount_paid >= 0",
            name="ck_trade_invoice_outcome_amount_paid",
        ),
        CheckConstraint(
            "payment_status <> 'PARTIAL' OR amount_paid IS NOT NULL",
            name="ck_trade_invoice_outcome_partial_amount",
        ),
        # One head per invoice.
        Index(
            "uq_trade_invoice_outcome_first",
            "invoice_id",
            unique=True,
            postgresql_where=text("supersedes_outcome_id IS NULL"),
        ),
        Index(
            "ix_trade_invoice_outcome_invoice",
            "invoice_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": SCHEMA},
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.trade_invoice.id",
            name="fk_trade_invoice_outcome_invoice",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    payment_status: Mapped[TradePaymentStatus] = mapped_column(
        Enum(
            TradePaymentStatus,
            name="trade_payment_status_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
    )
    #: How much was paid, when that is known. Required for ``PARTIAL``. Same currency
    #: as the invoice — there is no second currency column, because a payment in
    #: another currency is a conversion and IQ-4 says we do not do those.
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    proof_status: Mapped[TradeProofStatus] = mapped_column(
        Enum(
            TradeProofStatus,
            name="trade_proof_status_enum",
            schema=SCHEMA,
            create_type=False,
        ),
        nullable=False,
        server_default=TradeProofStatus.CLAIMED.value,
        default=TradeProofStatus.CLAIMED,
    )
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: References backing this outcome, in the shape verification evidence uses
    #: (``domain/verification_evidence.py``): a list of ``{type, ref}``. Validated by
    #: the service, which is where that rule already lives.
    evidence_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    recorded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    supersedes_outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


@dataclass(frozen=True)
class DealInvoiceDraft:
    """The identity of an invoice being created alongside a deal's payment outcome
    (task 3.21).

    A plain value rather than the request schema, so the service does not import the
    API layer — and so the buyer migration or a script can call the same method.
    """

    invoice_number: str
    invoice_date: date
    amount: Decimal
    currency: str


__all__ = ["CURRENCY_LENGTH", "DealInvoiceDraft", "TradeInvoice", "TradeInvoiceOutcome"]
