"""The handover guard, as an ordered list of conditions — **owner: Developer 2**
(allocation F2).

Contract: ``docs/contracts/deal-and-buyer.md`` §6. Plan P2-5b, P3-4, P4-7, P6-7.

Why this file exists
--------------------
``DealService._handover_blocked_reason`` used to be one function with assumption
A5's two rules written inline. Four more rules are coming, and each one belongs to
a different lane:

====================================  ==========================================
Condition                             Needs
====================================  ==========================================
the seller is a ``CUSTOMER``          nothing (the company row)
its background check is ``CLEAR``     nothing (the company row)
the required documents are present    ``RequiredDocumentsPolicy``  (Dev 2, P2-5b)
the seller's compliance is current    ``ComplianceFactsReader``    (Dev 1, P4-7)
the buyer's sanctions and AML pass    ``ComplianceFactsReader``    (Dev 1, P4-7)
the invoicing branch is recorded      ``BranchFlagReader``         (Dev 3, P6-7)
the invoicing branch is not flagged   ``BranchFlagReader``         (Dev 3, P6-7)
====================================  ==========================================

So the guard is a **list**, in a fixed order, and each provider is **injected**.
Every rule reports on its own; the service joins what comes back with ``"; "``, so
a deal that fails three conditions says all three rather than one at a time. That
is the behaviour the screen already relies on (contract §4.1) and it is why a
condition returns a *string or None* rather than a bool.

A provider that is not built yet is injected as its null version
(:class:`NoComplianceFacts`, :class:`NoRequiredDocuments`,
:class:`NoBranchFlags`), whose answer is always "nothing unmet". That is what makes
this file land with **behaviour unchanged**: the two A5 conditions decide exactly
what they decided before, and the other four are inert until the lane that owns
their provider ships the real one. No condition is edited at that point — only
which provider ``DealService`` hands in.

Where each interface is declared
-------------------------------
``ComplianceFactsReader`` and ``PartyComplianceFacts`` are **Developer 1's**, imported
from ``domain/compliance_facts.py``. This module declared its own structural copies
while F1 was unmerged; they are gone, so the two cannot drift (``dev2-remaining-work.md``
§2 item 2). ``CheckState`` is a ``Literal`` of plain strings there, so the conditions
compare the values directly.

``RequiredDocumentsPolicy`` and ``BranchFlagReader`` stay ``Protocol``s declared here:
the first is this lane's own, and the second is satisfied by Developer 3's stub and
later their real reader without either lane importing the other (the same structural
choice ``domain/ports.py`` made).

:func:`state_name` remains for the one value that really is an enum on the other side
of a seam — ``exporter_profile.pipeline_status``, read by ``DealService`` for the
buyer-company summary — and compares it by name rather than importing Developer 3's
enum, exactly as ``_HANDOVER_JOURNEY`` compares the journey.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.modules.onboarding.domain.compliance_facts import (
    ComplianceFactsReader,
    PartyComplianceFacts,
)

__all__ = [
    "BranchFlagReader",
    "HANDOVER_CONDITIONS",
    "HandoverProviders",
    "HandoverSubject",
    "NoBranchFlags",
    "NoComplianceFacts",
    "NoRequiredDocuments",
    "RequiredDocumentsPolicy",
    "state_name",
]

#: Architecture §3.3: the journey value a company must have reached before a deal
#: may be handed over (assumption A5's first half). Compared by *name* rather than
#: by importing Developer 3's enum member, so this file states the rule without
#: taking a dependency on the shape of their enum.
HANDOVER_JOURNEY = "CUSTOMER"

#: The background-check value A5's second half requires.
HANDOVER_BACKGROUND_CHECK = "CLEAR"

#: What "this check passed" is called, whoever reports it (plan BQ-4, IQ-2).
PASSED = "PASSED"
#: What a check that came back against the party is called (plan BQ-3).
FAILED = "FAILED"


def state_name(value: Any) -> str | None:
    """A fact's value as a plain name, whether it arrived as a ``str`` or an enum.

    ``None`` stays ``None`` — "the provider has nothing to say" is distinct from
    any state it could name.
    """
    if value is None:
        return None
    return getattr(value, "value", None) or getattr(value, "name", None) or str(value)


# ── What one guard run looks at ──────────────────────────────────────────────


@dataclass(frozen=True)
class HandoverSubject:
    """The deal being handed over and the seller's row, read once.

    Plain values rather than live lookups: ``DealService`` reads the company
    exactly once per guard run — share-locked when the guard runs on the move
    (D10), unlocked when it runs to render a page — and every condition then reads
    the same snapshot. A condition that went back to the database could otherwise
    see a different company than the one the lock was taken on.

    ``seller_background_check`` comes through ``DealService.read_background_check``,
    which is Developer 1's published read seam; this module never calls it, so the
    seam stays visible in one place.
    """

    deal_id: uuid.UUID
    seller_company_id: uuid.UUID
    #: ``LEAD`` / ``PROSPECT`` / ``CUSTOMER``, by name.
    seller_journey: str
    #: ``NOT_STARTED`` / ``IN_REVIEW`` / ``CLEAR`` / … by name. ``None`` only if the
    #: read seam has nothing, which the ``NOT NULL`` column makes unreachable.
    seller_background_check: str | None
    #: The buyer as a company, once P4-4 records one; ``None`` on a legacy deal.
    buyer_company_id: uuid.UUID | None
    #: The legacy ``deal_buyer`` row's id, when that is still where the buyer is.
    legacy_buyer_id: uuid.UUID | None
    #: The seller's invoicing branch, once P6-6 records one.
    seller_gst_registration_id: uuid.UUID | None
    #: One "now" for the whole run, so two conditions cannot disagree about
    #: whether a check had expired.
    now: datetime


# ── The providers ────────────────────────────────────────────────────────────


@runtime_checkable
class RequiredDocumentsPolicy(Protocol):
    """Which document categories a deal must have before handover (P2-5a).

    Returns the categories that are **missing** — active requirements with no
    ``AVAILABLE`` document on the deal (IQ-11) — in a stable order, so the refusal
    message does not reshuffle between two reads of the same deal.
    """

    async def missing_for_deal(self, deal_id: uuid.UUID) -> tuple[str, ...]: ...


@runtime_checkable
class BranchFlagReader(Protocol):
    """Developer 3's interface to GST registrations, for the two branch rules (P6-7).

    ``is_flagged`` answers about one registration and returns the state's name with
    it, because the refusal quotes it — "the invoicing branch Maharashtra is flagged"
    — and only Developer 3's lane knows that a GSTIN's state comes from its first two
    characters.

    ``has_active_registrations`` answers about the **company**, and exists for P6-7's
    second rule: a deal with no invoicing branch recorded is blocked *only* when its
    seller has a branch to record. A seller with no GST registration at all is not
    asked for one, which is the difference between a rule and a nuisance — some
    sellers legitimately have none.
    """

    async def is_flagged(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]: ...

    async def has_active_registrations(self, company_id: uuid.UUID) -> bool: ...


class NoComplianceFacts:
    """The null ``ComplianceFactsReader``: no facts, so nothing to report.

    Injected until Developer 1's F1 reader exists. It is deliberately **not** a
    reader that answers "everything passed": the conditions below treat "no facts"
    as "this condition has nothing to say" and skip it, so a missing provider can
    never be mistaken for a passing check.
    """

    async def for_company(
        self, company_id: uuid.UUID, now: datetime
    ) -> PartyComplianceFacts | None:
        return None

    async def for_legacy_buyer(
        self, deal_buyer_id: uuid.UUID, now: datetime
    ) -> PartyComplianceFacts | None:
        return None

    # Deliberately **not** a `ComplianceFactsReader`: that Protocol returns
    # `PartyComplianceFacts`, never `None`. The `| None` here is what the conditions
    # test for to decide "no provider, so this condition has nothing to say", and
    # typing it honestly keeps anyone from mistaking this for a real reader.


class NoRequiredDocuments:
    """The null ``RequiredDocumentsPolicy``: nothing is required, so nothing is
    missing. Also the correct answer on a live database with no requirements
    configured, which is why P2-5b keeps it rather than replacing it."""

    async def missing_for_deal(self, deal_id: uuid.UUID) -> tuple[str, ...]:
        return ()


class NoBranchFlags:
    """The null ``BranchFlagReader``: no branch is flagged, and no seller is known to
    have one.

    Both answers are the ones that **add no refusal**, which is what a null provider
    must do: a caller that has not injected a real reader gets the guard it had
    before these rules existed. In particular ``has_active_registrations`` returning
    ``False`` means "we cannot see any", so the "record the invoicing branch" rule
    stays silent rather than blocking every deal on a question nobody can answer.
    """

    async def is_flagged(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]:
        return (False, None)

    async def has_active_registrations(self, company_id: uuid.UUID) -> bool:
        return False


@dataclass(frozen=True)
class HandoverProviders:
    """Everything the conditions ask, in one injectable bundle.

    Defaulted to the null providers so a caller that needs only assumption A5 —
    every caller, until P2-5b — constructs ``HandoverProviders()`` and gets today's
    behaviour. A test substitutes one field and leaves the rest alone.
    """

    compliance: ComplianceFactsReader = field(default_factory=NoComplianceFacts)
    required_documents: RequiredDocumentsPolicy = field(
        default_factory=NoRequiredDocuments
    )
    branch_flags: BranchFlagReader = field(default_factory=NoBranchFlags)


# ── The conditions, in the order they are reported ───────────────────────────

Condition = Callable[[HandoverSubject, HandoverProviders], Awaitable[str | None]]


async def seller_is_a_customer(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Assumption A5, first half."""
    if subject.seller_journey == HANDOVER_JOURNEY:
        return None
    return f"the company is {subject.seller_journey}, not {HANDOVER_JOURNEY}"


async def seller_background_check_is_clear(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Assumption A5, second half.

    "Not ``CLEAR``" is never read as "clear": a company that has never been checked
    reads ``NOT_STARTED``, which is a fact and not an absence.
    """
    value = subject.seller_background_check
    if value == HANDOVER_BACKGROUND_CHECK:
        return None
    return f"the background check is {value}, not {HANDOVER_BACKGROUND_CHECK}"


async def required_documents_are_present(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Plan P2-5b. Names every missing category at once, like every other
    condition here, rather than the first one found."""
    missing = await providers.required_documents.missing_for_deal(subject.deal_id)
    if not missing:
        return None
    return "missing required documents: " + ", ".join(missing)


async def seller_compliance_is_current(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Plan P3-3b and P4-7: the seller's Clear must not have expired, and a
    ``FAILED`` sanctions or AML result on the seller blocks (BQ-3).

    The expiry clause is gated on ``is_clear and not is_clear_current``, not on
    ``not is_clear_current`` alone. A seller that is not ``CLEAR`` at all also has no
    current Clear, and condition 2 already says so by name — reporting "expired" as
    well would tell an operator to renew a check that was never passed. It names the
    date, as P3-3b asks, because "expired" without a date leaves the reader to go
    looking for when.

    Inert while :class:`NoComplianceFacts` is injected — "no facts" is not
    "everything passed".
    """
    facts = await providers.compliance.for_company(subject.seller_company_id, subject.now)
    if facts is None:
        return None

    unmet: list[str] = []
    if facts.is_clear and not facts.is_clear_current:
        unmet.append(f"the background check expired on {_on(facts.clear_expires_at)}")
    for label, value in (("sanctions", facts.sanctions), ("AML", facts.aml)):
        if value == FAILED:
            unmet.append(f"the company's {label} check has failed")
    return "; ".join(unmet) or None


def _on(moment: datetime | None) -> str:
    """A date an operator can act on, or an honest stand-in.

    ``clear_expires_at`` is set on every Clear the facts report as expired, so the
    fallback is unreachable in practice; it is here so a provider that omits the date
    produces a readable message rather than the word ``None``.
    """
    return moment.date().isoformat() if moment is not None else "an unrecorded date"


async def buyer_compliance_passes(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Plan P3-4 and P4-7: the buyer's sanctions **and** AML must be ``PASSED``
    (BQ-4) — not merely "not failed", because "we have not checked" and "the check
    came back clean" must not collapse into one outcome.

    A deal whose buyer is still a ``deal_buyer`` row is read through
    ``for_legacy_buyer``, so the rule applies to old and new deals alike.
    """
    if subject.buyer_company_id is not None:
        facts = await providers.compliance.for_company(
            subject.buyer_company_id, subject.now
        )
    elif subject.legacy_buyer_id is not None:
        facts = await providers.compliance.for_legacy_buyer(
            subject.legacy_buyer_id, subject.now
        )
    else:
        # No buyer at all is `DealBuyerRequiredError`'s refusal, raised before the
        # guard runs; it is not reported as an unmet condition here.
        return None
    if facts is None:
        return None

    unmet = [
        f"the buyer's {label} check is {value}, not {PASSED}"
        for label, value in (("sanctions", facts.sanctions), ("AML", facts.aml))
        if value != PASSED
    ]
    return "; ".join(unmet) or None


async def invoicing_branch_is_recorded(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Plan P6-7's second rule (task 2.9): a deal invoiced from somewhere must say
    where.

    Asked **only of a seller that has a branch to name**. A seller with no active GST
    registration is not asked for one — some sellers legitimately have none, and
    blocking them on a field they cannot fill would make the rule a nuisance rather
    than a control. That is why the reader answers about the company and not just
    about the deal.

    Kept separate from the flag rule below rather than folded into it: the two have
    different remedies — "record the branch" versus "resolve the flag or invoice from
    another branch" — and a joined message that offered both for one deal would be
    confusing.
    """
    if subject.seller_gst_registration_id is not None:
        return None
    if not await providers.branch_flags.has_active_registrations(
        subject.seller_company_id
    ):
        return None
    return "the invoicing branch is not recorded"


async def invoicing_branch_is_not_flagged(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Plan P6-7's first rule. A deal with no branch recorded is not refused here —
    that is ``invoicing_branch_is_recorded``'s question.

    One branch, not the company (decision BQ-6): a company trading through five
    states may have a problem in one of them, and deals invoiced from the other four
    proceed.
    """
    registration_id = subject.seller_gst_registration_id
    if registration_id is None:
        return None
    flagged, state = await providers.branch_flags.is_flagged(registration_id)
    if not flagged:
        return None
    return f"the invoicing branch {state or 'registration'} is flagged"


#: The guard, in reporting order: the seller's own standing first, then the
#: paperwork, then the two parties' compliance, then the branch. Ordered so the
#: cheapest and most fundamental refusals read first in a joined message — a
#: PROSPECT whose check is FLAGGED needs both fixed, not one.
HANDOVER_CONDITIONS: tuple[Condition, ...] = (
    seller_is_a_customer,
    seller_background_check_is_clear,
    required_documents_are_present,
    seller_compliance_is_current,
    buyer_compliance_passes,
    invoicing_branch_is_recorded,
    invoicing_branch_is_not_flagged,
)


async def blocked_reason(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Every unmet condition, joined with ``"; "`` — or ``None`` if the deal may be
    handed over.

    Every condition runs: the screen tells the whole story at once rather than
    making an operator fix one thing to discover the next (contract §4.1).
    """
    unmet = [
        reason
        for reason in [await condition(subject, providers) for condition in HANDOVER_CONDITIONS]
        if reason is not None
    ]
    return "; ".join(unmet) or None
