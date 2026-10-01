"""``ComplianceFactsService`` — implements ``domain/compliance_facts.py``'s
``ComplianceFactsReader`` — **owner: Developer 1** (allocation §3, F1).

What another lane reads a party's compliance through: Developer 2's handover guard
(plan P3-3b, P3-4, P4-7) and Developer 3's customer promotion
(``ExporterProfileService.promote_to_customer_if_ready``, IQ-18). The rules the facts
follow are the domain module's; this class only gathers what they need.

**Read-only, and never locks** — the same contract as ``BackgroundCheckReader`` and
the compliance-inputs seam it reads through. It never commits, flushes or writes; the
caller owns locking and knows why it is asking. A consumer that must not race a
background-check move takes the company row itself (the handover guard's
``FOR SHARE``, D10; the promotion's caller's ``FOR UPDATE``).

What it reads, today
--------------------
* The gauge and the clearing decision through ``BackgroundCheckReader.standing`` — the
  chain head of a ``CLEAR`` company is its clearing decision.
* Expiry (plan P3-3b) from the standing: the clearing decision's stored
  ``expires_at`` (P3-3a), or — for a Clear recorded before migration 0027 — the legacy
  rule (the decision + one year, BQ-5). An expired Clear is still ``is_clear``; only
  ``is_clear_current`` turns false. Nothing moves the gauge.
* Sanctions and AML from the company's **current-cycle** inputs, through the
  compliance-inputs seam (plan P2-3b), by IQ-2's meaning of "passed".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.domain.compliance_facts import (
    AML,
    SANCTIONS,
    PartyComplianceFacts,
    check_state,
)
from app.modules.onboarding.domain.compliance_inputs import ComplianceInputsReader


def _require_aware(now: datetime) -> datetime:
    # A naive `now` compared with a timestamptz is off by the server's UTC offset, and
    # silently so. Refuse it where it enters.
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("ComplianceFactsReader needs a timezone-aware `now`")
    return now


class ComplianceFactsService:
    """Implements ``ComplianceFactsReader``. See the module docstring.

    Args:
        db: The caller's session. Read only.
        reader: The compliance-inputs seam; defaults to ``ComplianceInputsService`` on
            the same session. A test may pass a fake.
    """

    def __init__(self, db: AsyncSession, *, reader: ComplianceInputsReader | None = None) -> None:
        self._db = db
        self._inputs: ComplianceInputsReader = reader or ComplianceInputsService(db)

    async def for_company(self, company_id: uuid.UUID, now: datetime) -> PartyComplianceFacts:
        """One company's facts at ``now``.

        Raises:
            ExporterProfileNotFoundError: no company has this id.
        """
        now = _require_aware(now)
        standing = await BackgroundCheckReader(self._db).standing(company_id)
        inputs = await self._inputs.company_inputs(company_id)
        return PartyComplianceFacts(
            background_check=standing.value,  # type: ignore[arg-type]
            is_clear=standing.is_clear,
            clear_expires_at=standing.expires_at,
            is_clear_current=standing.is_clear_and_current(now),
            sanctions=check_state(inputs.verifications, SANCTIONS),
            aml=check_state(inputs.verifications, AML),
        )

    async def for_legacy_buyer(
        self, deal_buyer_id: uuid.UUID, now: datetime
    ) -> PartyComplianceFacts:
        """The facts of a deal buyer that is still a ``deal_buyer`` row (legacy deals).

        A legacy buyer has no background check, so it is ``NOT_STARTED`` and never
        Clear; its sanctions and AML come from the checks recorded on the buyer row.

        Raises:
            ComplianceInputsBuyerNotFoundError: no deal buyer has this id.
        """
        _require_aware(now)
        checks = await self._inputs.buyer_checks(deal_buyer_id)
        return PartyComplianceFacts(
            background_check="NOT_STARTED",
            is_clear=False,
            clear_expires_at=None,
            is_clear_current=False,
            sanctions=check_state(checks, SANCTIONS),
            aml=check_state(checks, AML),
        )


__all__ = ["ComplianceFactsService"]
