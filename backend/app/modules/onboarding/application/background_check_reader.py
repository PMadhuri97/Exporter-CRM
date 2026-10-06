"""The background check's read seam (``docs/contracts/background-check.md`` §10).

What the rest of the CRM reads the gauge through: the handover guard (§11.2) and the
customer move (§11.3). Publishing it as a seam is what keeps
``background_check_decision`` and its evidence private to the background check —
a consumer needs the standing, never the chain.

**Read-only, and deliberately weak.** It never commits, never flushes, never writes and
**never locks**. The caller owns locking, because only the caller knows what it is about
to do with the answer. The handover guard share-locks the company row on the move
(settled 28 September 2026) and reads it unlocked on a page render. The background check's own
moves always take the row lock, so a consumer that also locks is fully serialised
against them.

**"Not ``CLEAR``" is never "clear".** Every consumer compares against ``CLEAR``
explicitly. There is no "is_ok" convenience here, for the same reason the compliance-inputs seam
exposes no ``is_clear_ready``: a judgement belongs to whoever is making the decision,
not to the thing being read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.compliance_facts import legacy_clear_expiry
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
)
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)


@dataclass(frozen=True)
class BackgroundCheckStanding:
    """Where a company's background check stands, for a consumer outside the background check.

    Strings rather than enums on purpose: a consumer comparing against ``"CLEAR"``
    does not have to import the background check's enum, which is what lets the gauge's internals
    change without an edit elsewhere.
    """

    company_id: uuid.UUID
    value: str
    """One of the six §2 values. The current gauge, straight off the company row."""

    risk_rating: str | None
    """The risk of the latest decision that set one — only ``CLEAR`` decisions can.

    **Read ``value`` before trusting this.** A company that was cleared at ``LOW`` and
    then reopened still reports ``LOW`` here while it sits at ``IN_REVIEW``: the rule
    (settled 28 September 2026) keeps the last recorded risk, explicitly labelled. It
    is the last clearance's rating, not a claim about the company now.
    """

    latest_decision_id: uuid.UUID | None
    """The chain head. ``None`` for a company still at ``NOT_STARTED``, which has
    never had a decision."""

    clearing_decision_id: uuid.UUID | None
    """The decision that made the company's **current** ``CLEAR``.

    ``None`` unless ``value == "CLEAR"``. This is what
    ``company.became_customer`` carries (event-envelope §3), so it must name the
    clearance in force — not a historical one that was later reopened.
    """

    decided_at: datetime | None
    """When the latest decision was made. ``None`` with no decisions."""

    expires_at: datetime | None = None
    """When the current ``CLEAR`` stops being current: the
    clearing decision's stored ``expires_at``, or — for a ``CLEAR`` recorded before
    migration 0027 — its ``decided_at`` + one year (the documented read rule).
    ``None`` unless ``value == "CLEAR"``. Expiry never moves the gauge: an expired
    Clear still reads ``CLEAR`` here, and :meth:`is_clear_and_current` says whether it
    is still current."""

    def is_clear_and_current(self, now: datetime) -> bool:
        """``CLEAR`` **and** not yet expired at ``now``. ``is_clear`` is kept
        as it is for consumers that ask only about the gauge."""
        return self.is_clear and self.expires_at is not None and now < self.expires_at

    @property
    def is_clear(self) -> bool:
        """Whether the company is cleared **right now**.

        A named comparison rather than a judgement: it is exactly
        ``value == "CLEAR"``, and it exists so a consumer cannot accidentally write
        ``!= "FLAGGED"`` and treat ``MORE_INFO`` as good enough.
        """
        return self.value == BackgroundCheckState.CLEAR.value


def clear_expiry(decided_at: datetime, stored: datetime | None) -> datetime:
    """A CLEAR decision's expiry: its stored ``expires_at``, else the legacy rule
    (``compliance_facts.legacy_clear_expiry`` — the one place the year is defined)."""
    return stored if stored is not None else legacy_clear_expiry(decided_at)


def current_background_check(company: ExporterProfile) -> str:
    """The loaded company's current gauge value, as a string. Pure: no I/O.

    For a caller that already holds the company row — the handover guard
    loads it to check the journey anyway, so making it query again would be a second
    round trip for a column it is already holding.

    The column is ``NOT NULL DEFAULT 'NOT_STARTED'``, so there is no "not recorded"
    case and this never returns ``None``: a company that has never been checked reads
    ``NOT_STARTED``, which is a fact, not an absence.
    """
    value = company.background_check
    return str(getattr(value, "value", value))


class BackgroundCheckReader:
    """Reads one company's standing. Never writes, never locks."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._decisions = BackgroundCheckDecisionRepository(db)

    async def standing(self, company_id: uuid.UUID) -> BackgroundCheckStanding:
        """Where this company's check stands.

        Raises:
            ExporterProfileNotFoundError: no company has this id. The company record's
                existing error, so a consumer handles one "unknown company" case
                rather than one per gauge.
        """
        value = await self._db.scalar(
            select(ExporterProfile.background_check).where(
                ExporterProfile.customer_id == company_id
            )
        )
        if value is None:
            raise ExporterProfileNotFoundError(company_id)

        latest = await self._decisions.latest_for_company(company_id)
        current = str(getattr(value, "value", value))

        # The chain head *is* the clearing decision when the company is CLEAR: every
        # move writes a decision, so nothing can have happened since.
        clearing = (
            latest
            if latest is not None
            and current == BackgroundCheckState.CLEAR.value
            and latest.to_value is BackgroundCheckState.CLEAR
            else None
        )
        return BackgroundCheckStanding(
            company_id=company_id,
            value=current,
            risk_rating=await self._latest_risk(company_id),
            latest_decision_id=latest.id if latest else None,
            clearing_decision_id=clearing.id if clearing else None,
            decided_at=latest.decided_at if latest else None,
            expires_at=(
                clear_expiry(clearing.decided_at, clearing.expires_at) if clearing else None
            ),
        )

    async def _latest_risk(self, company_id: uuid.UUID) -> str | None:
        """The risk of the most recent decision that set one, or ``None``.

        Not simply the chain head's risk: only ``CLEAR`` may carry a risk, so the head
        of a reopened company has none and the last recorded rating would otherwise
        vanish from the read. ``decided_at`` is insert-time wall clock, taken after
        the row lock, so it orders decisions the way the chain does.
        """
        risk = await self._db.scalar(
            select(BackgroundCheckDecision.risk_rating)
            .where(
                BackgroundCheckDecision.company_id == company_id,
                BackgroundCheckDecision.risk_rating.is_not(None),
            )
            .order_by(
                BackgroundCheckDecision.decided_at.desc(),
                BackgroundCheckDecision.id.desc(),
            )
            .limit(1)
        )
        return str(getattr(risk, "value", risk)) if risk is not None else None


__all__ = [
    "clear_expiry",
    "BackgroundCheckReader",
    "BackgroundCheckStanding",
    "current_background_check",
]
