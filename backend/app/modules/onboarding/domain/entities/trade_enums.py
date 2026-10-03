"""Trade history's enums — **owner: Developer 3** (allocation task 3.19, plan P5-2).

What a buyer did with an invoice, and how well we know it. Two axes, deliberately
separate, because conflating them is the mistake this model exists to avoid: "they
paid" and "we can prove they paid" are different claims, and a trade history that
could not tell them apart would be worthless as evidence and misleading as a sales
record.
"""

from __future__ import annotations

import enum


class TradePaymentStatus(str, enum.Enum):
    """What happened to an invoice.

    ``UNKNOWN`` is a real answer and not a missing one: a relationship manager may
    know an invoice exists — the exporter showed it to them — without knowing whether
    it was paid. Recording that is more useful than recording nothing, and it is why
    an outcome is required to carry a status at all.

    ``PARTIAL`` carries ``amount_paid``; the others may. ``DISPUTED`` is not a
    judgement about who is right, only that the two parties disagree.
    """

    PAID = "PAID"
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


class TradeProofStatus(str, enum.Enum):
    """How well we know it.

    ``CLAIMED`` — somebody told us, usually the exporter. ``PROVEN`` — there is
    evidence on file: a document, a bank reference, a link.

    Kept apart from ``payment_status`` so a reader can weigh a trade history rather
    than just read it. An exporter's own account of its past trade is worth
    recording; it is not worth the same as a settled invoice, and a model that stored
    only "PAID" would make the two indistinguishable six months later.
    """

    CLAIMED = "CLAIMED"
    PROVEN = "PROVEN"


__all__ = ["TradePaymentStatus", "TradeProofStatus"]
