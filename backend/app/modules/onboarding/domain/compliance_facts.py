"""``ComplianceFactsReader`` — a party's compliance standing, for the rest of the CRM.

Published so that the handover guard and the customer promotion
ask one question — "what do we know about this party's compliance, right now?" —
without reading the background check's decisions, cycles or verification tables.
Pure data structures, one ``Protocol`` and the pure rules the implementation applies;
no I/O. ``application/compliance_facts.py::ComplianceFactsService`` implements it.

Facts, stated plainly
---------------------
``PartyComplianceFacts`` carries the gauge value, whether it is ``CLEAR``, when that
Clear stops being current, whether it still is at ``now``, and the state of the
party's sanctions and AML checks. What a consumer does with them — block a handover,
refuse a promotion, show a warning — is the consumer's rule.

``now`` is an argument, never read inside: the caller takes it from
``app.shared.clock`` (or a test's ``FixedClock``), so "is this Clear still current?"
is answerable at any moment without sleeping.

What the facts mean today
-------------------------
* **Expiry.** Each Clear since migration 0027 stores
  its own ``expires_at`` (``decided_at`` + the validity setting, default 365 days). A
  Clear recorded before then is read by the legacy rule: its ``decided_at`` +
  ``LEGACY_CLEAR_VALIDITY``. An expired Clear stays ``is_clear`` — nothing moves the
  gauge — but is not ``is_clear_current``.
* **Sanctions and AML (decided 1 October 2026).** The latest real result of
  that type in the company's current cycle decides:

  ============================================  ==========
  latest non-placeholder result                  state
  ============================================  ==========
  none (or placeholders only)                    ``MISSING``
  ``PASSED``                                     ``PASSED``
  ``FAILED``                                     ``FAILED``
  ``REVIEW`` with an ``ACCEPTED`` review         ``PASSED``
  ``REVIEW`` with a ``REJECTED`` review          ``FAILED``
  ``REVIEW`` unreviewed or ``ESCALATED``         ``PENDING``
  ``PENDING``                                    ``PENDING``
  ============================================  ==========

  The decision fixes the ``PASSED`` rows. ``REVIEW`` + ``REJECTED`` reading as ``FAILED`` is
  this module's reading — a person looked at an inconclusive result and concluded
  against it. A ``PASSED`` or ``FAILED`` result reads as its status whatever its
  review says, as the decision words it.
* **Legacy deal buyers** (``for_legacy_buyer``) have no background check: their gauge
  reads ``NOT_STARTED``, they are never Clear, and their sanctions and AML come from
  the checks recorded on the ``deal_buyer`` row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from app.modules.onboarding.domain.compliance_inputs import VerificationInput

#: The six gauge values (``background_check_enums.BackgroundCheckState``), as strings so
#: a consumer need not import the enum.
BackgroundCheckValue = Literal[
    "NOT_STARTED", "IN_REVIEW", "CLEAR", "MORE_INFO", "FLAGGED", "ON_HOLD"
]

#: The state of one kind of check for one party (see the module docstring).
CheckState = Literal["PASSED", "FAILED", "MISSING", "PENDING"]

#: How long a Clear recorded before expiry was stored stays current (one year
#: from the last Clear). 365 days, the same default as the validity setting
#: (``CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS``).
LEGACY_CLEAR_VALIDITY = timedelta(days=365)

#: The verification types the facts report on.
SANCTIONS = "SANCTIONS"
AML = "AML"


@dataclass(frozen=True)
class PartyComplianceFacts:
    """What is known about one party's compliance, at one moment."""

    background_check: BackgroundCheckValue
    """The gauge, straight off the company row (``NOT_STARTED`` for a legacy buyer)."""

    is_clear: bool
    """Exactly ``background_check == "CLEAR"`` — current or not."""

    clear_expires_at: datetime | None
    """When the current Clear stops being current. ``None`` unless ``is_clear``."""

    is_clear_current: bool
    """``is_clear`` and ``now`` is before ``clear_expires_at``."""

    sanctions: CheckState
    aml: CheckState


class ComplianceFactsReader(Protocol):
    """Read-only, in the caller's session: never commits, flushes, locks or writes.

    Errors: an unknown company raises ``ExporterProfileNotFoundError``; an unknown
    ``deal_buyer_id`` raises ``ComplianceInputsBuyerNotFoundError`` (404).
    """

    async def for_company(self, company_id: uuid.UUID, now: datetime) -> PartyComplianceFacts:
        ...

    async def for_legacy_buyer(
        self, deal_buyer_id: uuid.UUID, now: datetime
    ) -> PartyComplianceFacts:
        ...


# ── The pure rules ───────────────────────────────────────────────────────────


def check_state(
    verifications: Iterable[VerificationInput], verification_type: str
) -> CheckState:
    """The state of one type of check, from results **newest first** (the seam's order).

    See the module docstring's table. Placeholders never count: a row no
    provider ever ran says nothing about the party.
    """
    for check in verifications:
        if check.verification_type != verification_type or check.is_placeholder:
            continue
        if check.status == "PASSED":
            return "PASSED"
        if check.status == "FAILED":
            return "FAILED"
        if check.status == "REVIEW":
            if check.latest_review_status == "ACCEPTED":
                return "PASSED"
            if check.latest_review_status == "REJECTED":
                return "FAILED"
        return "PENDING"
    return "MISSING"


def legacy_clear_expiry(decided_at: datetime) -> datetime:
    """When a Clear decided at ``decided_at`` stops being current, by the legacy rule."""
    return decided_at + LEGACY_CLEAR_VALIDITY


def is_current(expires_at: datetime | None, now: datetime) -> bool:
    """Whether a Clear expiring at ``expires_at`` is still current at ``now``."""
    return expires_at is not None and now < expires_at


__all__ = [
    "AML",
    "LEGACY_CLEAR_VALIDITY",
    "SANCTIONS",
    "BackgroundCheckValue",
    "CheckState",
    "ComplianceFactsReader",
    "PartyComplianceFacts",
    "check_state",
    "is_current",
    "legacy_clear_expiry",
]
