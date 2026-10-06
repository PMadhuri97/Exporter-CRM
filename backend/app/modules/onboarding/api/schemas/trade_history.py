"""Trade history as the API serves it.

What two companies have traded, and how it went. Its own file, like the other
records that are not companies.

**No identifiers, for any role.** A relationship names its two companies by id,
name and country — the same four fields `CompanyMatchCandidate` carries — and
nothing here holds a PAN, GSTIN, IEC, CIN or registration number. That is what
makes "DEVELOPER reads masked" true of these routes without a
masking pass: there is nothing to mask. It matches the rule the history log already
follows for `trade` rows (`history-row.md`: those rows go to DEVELOPER, and their
writers store identifiers already masked).

A reader who needs a counterparty's identifiers opens that company, where the
role matrix applies as usual.

**Amounts are exact and never converted**. `amount` and
`amount_paid` are serialised as strings, not floats: a float is the wrong type for
money, and JSON numbers would invite a client to add two currencies together.
There is no total anywhere in these shapes for the same reason — summing an AED
invoice and a USD one is a decision a person makes with a rate they choose.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.modules.onboarding.api.schemas.verification import (
    VerificationEvidenceRefModel,
    VerificationEvidenceRefOut,
)
from app.modules.onboarding.domain.entities.exporter_enums import CompanyPipelineStatus
from app.modules.onboarding.domain.entities.trade_enums import (
    TradePaymentStatus,
    TradeProofStatus,
)


class TradeCounterparty(BaseModel):
    """The company on the other side. No identifiers — see the module docstring."""

    company_id: uuid.UUID
    name: str | None
    country: str | None
    pipeline_status: CompanyPipelineStatus


class RecordTradeInvoiceRequest(BaseModel):
    """Record an invoice against a relationship.

    Its identity is frozen the moment it is written, so there is no edit route: a
    mistake is corrected by recording the right invoice, and the wrong one stays
    visible. That is the same trade-off every append-only record in this module
    makes, and it is why the fields here are worth getting right first time.
    """

    model_config = ConfigDict(extra="forbid")

    invoice_number: str = Field(min_length=1, max_length=100)
    invoice_date: date
    #: Exact, positive. Sent as a string or a number; stored as `Numeric`.
    amount: Decimal = Field(gt=0)
    #: ISO 4217, three letters. Stored as issued and **never converted**.
    currency: str = Field(min_length=3, max_length=3)
    #: The deal this invoice came from, when it came from one. Omitted for past
    #: trade — what the two companies did before they came to us.
    deal_id: uuid.UUID | None = None


class RecordTradeOutcomeRequest(BaseModel):
    """Append what we now know about an invoice.

    Nothing is edited: a correction is a **new** outcome naming the one it replaces,
    so the record says what we believed and when we stopped believing it.

    `supersedes_outcome_id` must be the invoice's **current** outcome — the one
    `current_outcome` reports. Omit it for the first. Getting it wrong is a 409
    rather than an overwrite, because two people each correcting the same outcome
    without seeing the other's is exactly what the chain exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    payment_status: TradePaymentStatus
    #: Required for `PARTIAL`; optional otherwise. In the invoice's own currency —
    #: there is no second currency, because a payment in another one is a conversion
    #: and the CRM rules those out.
    amount_paid: Decimal | None = Field(default=None, ge=0)
    #: `CLAIMED` (somebody told us) or `PROVEN` (there is evidence on file). Kept
    #: apart from `payment_status` so a reader can weigh a history rather than just
    #: read it.
    proof_status: TradeProofStatus = TradeProofStatus.CLAIMED
    #: Required when superseding: "we changed our mind" with no reason is not a
    #: record anyone can act on later.
    evidence_note: str | None = Field(default=None, max_length=4000)
    #: `{type, ref}` references, validated by the same shape rule a verification
    #: result's evidence gets — a `url` must be an http(s) link. Verification's own
    #: models, so the generated client types name the shape and the two cannot drift.
    evidence_refs: list[VerificationEvidenceRefModel] | None = None
    supersedes_outcome_id: uuid.UUID | None = None


class RecordDealPaymentOutcomeRequest(RecordTradeOutcomeRequest):
    """How a handed-over deal was actually paid.

    The outcome fields of `RecordTradeOutcomeRequest`, plus the invoice's identity —
    **required only when this deal has no invoice yet**, and refused when it already
    has one, because an invoice's identity is frozen and ignoring new details would
    tell the caller they had been recorded.

    Recording it at the deal rather than at an invoice is the point: the person who
    knows whether a deal was paid has the deal in front of them, not a relationship
    id and an invoice id.
    """

    model_config = ConfigDict(extra="forbid")

    invoice_number: str | None = Field(default=None, min_length=1, max_length=100)
    invoice_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @property
    def invoice_fields_given(self) -> bool:
        return any(
            value is not None
            for value in (self.invoice_number, self.invoice_date, self.amount, self.currency)
        )

    @model_validator(mode="after")
    def _invoice_identity_is_whole_or_absent(self) -> RecordDealPaymentOutcomeRequest:
        """All four invoice fields, or none.

        A partial identity is the one case worth refusing early: an invoice is
        immutable once written, so an invoice created from three of the four fields
        could never be completed.
        """
        given = [
            self.invoice_number is not None,
            self.invoice_date is not None,
            self.amount is not None,
            self.currency is not None,
        ]
        if any(given) and not all(given):
            raise ValueError(
                "an invoice needs its number, date, amount and currency together, or "
                "none of them if this deal already has one"
            )
        return self


class DealPaymentOutcomeResponse(BaseModel):
    """The invoice this deal was paid against, and what we now know about it."""

    invoice: TradeInvoiceResponse
    outcome: TradeOutcomeResponse
    #: True when this request created the invoice. Served so a screen can say "invoice
    #: recorded" rather than implying it was already there.
    invoice_created: bool = False


class TradeOutcomeResponse(BaseModel):
    """One thing we learned about an invoice."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    payment_status: TradePaymentStatus
    amount_paid: Decimal | None
    proof_status: TradeProofStatus
    evidence_note: str | None
    evidence_refs: list[VerificationEvidenceRefOut] | None
    recorded_by: str | None
    recorded_at: datetime
    #: The outcome this one replaced, if any. `null` on an invoice's first.
    supersedes_outcome_id: uuid.UUID | None
    #: Whether this is what we believe **now** — the chain's head. Served rather
    #: than inferred, so a screen and the guard cannot disagree about which row is
    #: live; the head is the row nothing supersedes, not the newest by timestamp.
    is_current: bool = False

    @field_serializer("amount_paid")
    def _amount_paid_as_text(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class TradeInvoiceResponse(BaseModel):
    """One invoice, with the outcome we currently believe."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    relationship_id: uuid.UUID
    #: The deal it came from; `null` for past trade.
    deal_id: uuid.UUID | None
    invoice_number: str
    invoice_date: date
    amount: Decimal
    currency: str
    created_by: str | None
    created_at: datetime
    #: What we believe now. `null` for an invoice nobody has recorded an outcome on
    #: — which is different from `UNKNOWN`, where somebody looked and could not say.
    current_outcome: TradeOutcomeResponse | None = None

    @field_serializer("amount")
    def _amount_as_text(self, value: Decimal) -> str:
        return str(value)


class TradeRelationshipResponse(BaseModel):
    """One (seller, buyer) pair.

    Ordered, not symmetric: A selling to B is a different relationship from B
    selling to A, with different invoices and different risk.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seller: TradeCounterparty
    buyer: TradeCounterparty
    #: How the row came to exist — `deal_buyer_recorded`, `backfill`, `manual`.
    source: str | None
    created_at: datetime
    #: How many invoices are recorded. Served so a list can say "nothing recorded
    #: yet" without a second request per row.
    invoice_count: int = 0


class TradeRelationshipListResponse(BaseModel):
    """A company's relationships on one side.

    Two sides, two lists, for the same reason the deal lists are separate (task
    2.7): a company can sell to one counterparty and buy from another, and one list
    mixing them would read differently row by row.
    """

    relationships: list[TradeRelationshipResponse]
    total: int


class TradeRelationshipDetailResponse(BaseModel):
    """One relationship with its invoices, newest first, each carrying the outcome
    we currently believe. The full outcome chain of one invoice is its own route."""

    relationship: TradeRelationshipResponse
    invoices: list[TradeInvoiceResponse]


class TradeInvoiceDetailResponse(BaseModel):
    """One invoice and its **whole** outcome chain, oldest first.

    The chain, not just the head, because that is the record: every belief and when
    it was replaced. A screen showing only the current outcome would make a
    corrected invoice indistinguishable from one that was right first time.
    """

    invoice: TradeInvoiceResponse
    outcomes: list[TradeOutcomeResponse]


__all__ = [
    "DealPaymentOutcomeResponse",
    "RecordDealPaymentOutcomeRequest",
    "RecordTradeInvoiceRequest",
    "RecordTradeOutcomeRequest",
    "TradeCounterparty",
    "TradeInvoiceDetailResponse",
    "TradeInvoiceResponse",
    "TradeOutcomeResponse",
    "TradeRelationshipDetailResponse",
    "TradeRelationshipListResponse",
    "TradeRelationshipResponse",
]
