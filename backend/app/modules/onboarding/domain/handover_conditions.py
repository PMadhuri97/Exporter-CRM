"""The handover guard, as an ordered list of conditions.

Contract: ``docs/contracts/deal-and-buyer.md`` §6.

Why this file exists
--------------------
``DealService._handover_blocked_reason`` used to be one function with the handover
guard's two rules written inline. More rules followed, and each one reads a
different part of the CRM:

====================================  ==========================================
Condition                             Needs
====================================  ==========================================
the seller is a ``CUSTOMER``          nothing (the company row)
its background check is ``CLEAR``     nothing (the company row)
the required documents are present    ``RequiredDocumentsPolicy``  (deals)
the seller's compliance is current    ``ComplianceFactsReader``    (compliance)
the buyer's sanctions and AML pass    ``ComplianceFactsReader``    (compliance)
the invoicing branch is recorded      ``BranchFlagReader``         (GST branches)
the invoicing branch is not flagged   ``BranchFlagReader``         (GST branches)
the invoicing branch is not           ``BranchFlagReader``         (GST branches)
deactivated
====================================  ==========================================

So the guard is a **list**, in a fixed order, and each provider is **injected**.
Every rule reports on its own; the service joins what comes back with ``"; "``, so
a deal that fails three conditions says all three rather than one at a time. That
is the behaviour the screen already relies on (contract §4.1) and it is why a
condition returns a *string or None* rather than a bool.

A provider that is not built yet is injected as its null version
(:class:`NoComplianceFacts`, :class:`NoRequiredDocuments`,
:class:`NoBranchFlags`), whose answer is always "nothing unmet". That is what makes
it possible to add a rule with **behaviour unchanged**: the two original conditions
decide exactly what they decided before, and a new one is inert until its provider's
real implementation is injected. No condition is edited at that point — only which
provider ``DealService`` hands in.

Where each interface is declared
-------------------------------
``ComplianceFactsReader`` and ``PartyComplianceFacts`` belong to the compliance
engine, imported from ``domain/compliance_facts.py``. This module once declared its
own structural copies; they are gone, so the two cannot drift. ``CheckState`` is a
``Literal`` of plain strings there, so the conditions compare the values directly.

``RequiredDocumentsPolicy`` and ``BranchFlagReader`` stay ``Protocol``s declared here:
the first belongs to deals, and the second is satisfied by the GST-branch reader
without either side importing the other (the same structural choice
``domain/ports.py`` made).

:func:`state_name` remains for the one value that really is an enum on the other side
of a seam — ``exporter_profile.pipeline_status``, read by ``DealService`` for the
buyer-company summary — and compares it by name rather than importing the company
record's enum, exactly as ``_HANDOVER_JOURNEY`` compares the journey.
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
#: may be handed over (the handover guard's first half). Compared by *name* rather
#: than by importing the company record's enum member, so this file states the rule
#: without taking a dependency on the shape of that enum.
HANDOVER_JOURNEY = "CUSTOMER"

#: The background-check value the handover guard's second half requires.
HANDOVER_BACKGROUND_CHECK = "CLEAR"

#: What "this check passed" is called, whoever reports it.
PASSED = "PASSED"
#: What a check that came back against the party is called.
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
    unlocked when it runs to render a page — and every condition then reads
    the same snapshot. A condition that went back to the database could otherwise
    see a different company than the one the lock was taken on.

    ``seller_background_check`` comes through ``DealService.read_background_check``,
    which is the compliance engine's published read seam; this module never calls it, so the
    seam stays visible in one place.
    """

    deal_id: uuid.UUID
    seller_company_id: uuid.UUID
    #: ``LEAD`` / ``PROSPECT`` / ``CUSTOMER``, by name.
    seller_journey: str
    #: ``NOT_STARTED`` / ``IN_REVIEW`` / ``CLEAR`` / … by name. ``None`` only if the
    #: read seam has nothing, which the ``NOT NULL`` column makes unreachable.
    seller_background_check: str | None
    #: The buyer as a company, when the deal records one; ``None`` on a legacy deal.
    buyer_company_id: uuid.UUID | None
    #: The legacy ``deal_buyer`` row's id, when that is still where the buyer is.
    legacy_buyer_id: uuid.UUID | None
    #: The seller's invoicing branch, when the deal records one.
    seller_gst_registration_id: uuid.UUID | None
    #: One "now" for the whole run, so two conditions cannot disagree about
    #: whether a check had expired.
    now: datetime


# ── The providers ────────────────────────────────────────────────────────────


@runtime_checkable
class RequiredDocumentsPolicy(Protocol):
    """Which document categories a deal must have before handover.

    Returns the categories that are **missing** — active requirements with no
    ``AVAILABLE`` document on the deal — in a stable order, so the refusal
    message does not reshuffle between two reads of the same deal.
    """

    async def missing_for_deal(self, deal_id: uuid.UUID) -> tuple[str, ...]: ...


@runtime_checkable
class BranchFlagReader(Protocol):
    """The interface to GST registrations, for the branch rules.

    ``is_flagged`` answers about one registration and returns the state's name with
    it, because the refusal quotes it — "the invoicing branch Maharashtra is flagged"
    — and only the GST-branch code knows that a GSTIN's state comes from its first two
    characters.

    ``has_active_registrations`` answers about the **company**, and exists for the
    branch-recorded rule: a deal with no invoicing branch recorded is blocked *only* when its
    seller has a branch to record. A seller with no GST registration at all is not
    asked for one, which is the difference between a rule and a nuisance — some
    sellers legitimately have none.

    ``is_active`` answers about one registration, with its state's name for the same
    reason as ``is_flagged``: a branch deactivated after a deal recorded it blocks
    that deal's handover (decided 4 October 2026).
    """

    async def is_flagged(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]: ...

    async def is_active(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]: ...

    async def has_active_registrations(self, company_id: uuid.UUID) -> bool: ...


class NoComplianceFacts:
    """The null ``ComplianceFactsReader``: no facts, so nothing to report.

    Injected when no compliance reader is wired. It is deliberately **not** a
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
    configured, which is why the guard keeps it rather than replacing it."""

    async def missing_for_deal(self, deal_id: uuid.UUID) -> tuple[str, ...]:
        return ()


class NoBranchFlags:
    """The null ``BranchFlagReader``: no branch is flagged, and no seller is known to
    have one.

    Every answer is the one that **adds no refusal**, which is what a null provider
    must do: a caller that has not injected a real reader gets the guard it had
    before these rules existed. In particular ``has_active_registrations`` returning
    ``False`` means "we cannot see any", so the "record the invoicing branch" rule
    stays silent rather than blocking every deal on a question nobody can answer.
    """

    async def is_flagged(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]:
        return (False, None)

    async def is_active(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]:
        return (True, None)

    async def has_active_registrations(self, company_id: uuid.UUID) -> bool:
        return False


@dataclass(frozen=True)
class HandoverProviders:
    """Everything the conditions ask, in one injectable bundle.

    Defaulted to the null providers so a caller that needs only the two original
    rules constructs ``HandoverProviders()`` and gets that behaviour. A test
    substitutes one field and leaves the rest alone.
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
    """The handover guard, first half: the seller is a ``CUSTOMER``."""
    if subject.seller_journey == HANDOVER_JOURNEY:
        return None
    return f"the company is {subject.seller_journey}, not {HANDOVER_JOURNEY}"


async def seller_background_check_is_clear(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """The handover guard, second half: the seller's background check is ``CLEAR``.

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
    """Required documents. Names every missing category at once, like every other
    condition here, rather than the first one found."""
    missing = await providers.required_documents.missing_for_deal(subject.deal_id)
    if not missing:
        return None
    return "missing required documents: " + ", ".join(missing)


async def seller_compliance_is_current(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """The seller's Clear must not have expired, and a ``FAILED`` sanctions or AML
    result on the seller blocks.

    The expiry clause is gated on ``is_clear and not is_clear_current``, not on
    ``not is_clear_current`` alone. A seller that is not ``CLEAR`` at all also has no
    current Clear, and condition 2 already says so by name — reporting "expired" as
    well would tell an operator to renew a check that was never passed. It names the
    date, because "expired" without a date leaves the reader to go
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
    """The buyer's sanctions **and** AML must be ``PASSED``
    — not merely "not failed", because "we have not checked" and "the check
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
    """The branch-recorded rule: a deal invoiced from somewhere must say
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
    """The flagged-branch rule. A deal with no branch recorded is not refused here —
    that is ``invoicing_branch_is_recorded``'s question.

    One branch, not the company: a company trading through five
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


async def invoicing_branch_is_active(
    subject: HandoverSubject, providers: HandoverProviders
) -> str | None:
    """Block, not warn (decided 4 October 2026). A branch can only be
    *chosen* while active, but it can be deactivated after a deal recorded it; that
    deal is then invoiced from a branch the company no longer trades through.

    Kept apart from the flag rule for the same reason the recorded rule is: the
    remedy differs — choose another active branch — and a branch can be both
    flagged and deactivated, in which case both are reported.
    """
    registration_id = subject.seller_gst_registration_id
    if registration_id is None:
        return None
    active, state = await providers.branch_flags.is_active(registration_id)
    if active:
        return None
    return f"the invoicing branch {state or 'registration'} is deactivated"


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
    invoicing_branch_is_active,
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
