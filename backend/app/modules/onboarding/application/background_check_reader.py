"""The background check's read seam — **owner: Developer 4A** (L4-01, L4-05 first half;
``docs/contracts/background-check.md`` §10).

What other developers read the gauge through: Developer 3's handover guard today
(§11.2), Developer 2's customer move when U4 is settled (§11.3). Publishing it as a
seam is what keeps ``background_check_decision`` and its evidence private to Dev4A —
a consumer needs the standing, never the chain.

**Read-only, and deliberately weak.** It never commits, never flushes, never writes and
**never locks**. The caller owns locking, because only the caller knows what it is about
to do with the answer: Dev3's handover guard may want the company row locked so a
concurrent ``FLAGGED`` cannot slip past it, and whether it must is **D10**, which this
module does not decide. Dev4A's own moves always take the row lock, so a consumer that
also locks is fully serialised against them.

**"Not ``CLEAR``" is never "clear".** Every consumer compares against ``CLEAR``
explicitly. There is no "is_ok" convenience here, for the same reason the 4A ↔ 4B seam
exposes no ``is_clear_ready``: a judgement belongs to whoever is making the decision,
not to the thing being read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Where a company's background check stands, for a consumer outside Dev4A.

    Strings rather than enums on purpose: a consumer comparing against ``"CLEAR"``
    does not have to import Dev4A's enum, which is what lets the gauge's internals
    change without a cross-developer edit.
    """

    company_id: uuid.UUID
    value: str
    """One of the six §2 values. The current gauge, straight off the company row."""

    risk_rating: str | None
    """The risk of the latest decision that set one.

    **Read ``value`` before trusting this.** A company that was cleared at ``LOW`` and
    then reopened still reports ``LOW`` here while it sits at ``IN_REVIEW`` — what a
    company *should* show after a reopen is **D6, open** (contract §10). Until D6 is
    answered, this is the last risk anyone recorded, not a claim about the company now.
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

    @property
    def is_clear(self) -> bool:
        """Whether the company is cleared **right now**.

        A named comparison rather than a judgement: it is exactly
        ``value == "CLEAR"``, and it exists so a consumer cannot accidentally write
        ``!= "FLAGGED"`` and treat ``MORE_INFO`` as good enough.
        """
        return self.value == BackgroundCheckState.CLEAR.value


def current_background_check(company: ExporterProfile) -> str:
    """The loaded company's current gauge value, as a string. Pure: no I/O.

    For a caller that already holds the company row — Developer 3's handover guard
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
            ExporterProfileNotFoundError: no company has this id. Developer 2's
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

        return BackgroundCheckStanding(
            company_id=company_id,
            value=current,
            risk_rating=await self._latest_risk(company_id),
            latest_decision_id=latest.id if latest else None,
            # The chain head *is* the clearing decision when the company is CLEAR:
            # every move writes a decision, so nothing can have happened since.
            clearing_decision_id=(
                latest.id if latest and current == BackgroundCheckState.CLEAR.value else None
            ),
            decided_at=latest.decided_at if latest else None,
        )

    async def _latest_risk(self, company_id: uuid.UUID) -> str | None:
        """The risk of the most recent decision that set one, or ``None``.

        Not simply the chain head's risk: only ``CLEAR`` is required to carry a risk,
        so the head of a reopened company has none and the last recorded rating would
        otherwise vanish from the read. What that *should* mean is D6.
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
    "BackgroundCheckReader",
    "BackgroundCheckStanding",
    "current_background_check",
]
