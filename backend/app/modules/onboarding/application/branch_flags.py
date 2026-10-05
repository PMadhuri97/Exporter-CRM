"""``BranchFlagReader`` — is this GST registration flagged?

The Protocol is declared in ``domain/handover_conditions.py``
because the handover guard is its only consumer. This
module provides the class that satisfies it; nothing here re-declares the Protocol,
and nothing here injects it — ``DealService`` chooses to use it.

**This is the real reader.** An earlier stub answered "not flagged" for
everything, which was true at the time because there was nowhere to record a flag.
Task 3.12 added ``flag_status`` and ``flag_reason`` to ``exporter_gstin`` and task
3.14 the routes that write them, so it now reads the column.

Why the answer carries a state name
-----------------------------------
The guard's message names the branch — "the invoicing branch Maharashtra is
flagged" — and a deal's invoicing branch is a row id, not something the guard can
describe on its own. Only the GST-branch code knows that a GSTIN's state comes from its first
two characters (``domain/gst_states.py``), so the state travels with the answer
rather than the guard having to look it up.

A registration with no name falls back to its code, and then to the word "a"
branch: ``state_name`` is ``NULL`` for a code this release does not know, and a
block that read "the invoicing branch None is flagged" would be worse than a vague
one.

**A flag is per company, not per GSTIN** (duplicates stay
warn-only). This reads the row it is given, so a GSTIN that two companies hold is
flagged for one of them and not the other — which is the intended behaviour, and
why ``GstRegistrationService.flag`` tells whoever flags it that the other copy
exists.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_enums import GstRegistrationFlag
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin

logger = structlog.get_logger(__name__)


class BranchFlagService:
    """Satisfies the handover guard's ``BranchFlagReader`` Protocol."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def is_flagged(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]:
        """Whether this registration is flagged, and how to name its branch.

        ``(False, None)`` for a registration that does not exist: the guard's job is
        to decide whether a handover is blocked, and "there is no such branch" is not
        a compliance problem — the composite FK on ``deal.seller_gst_registration_id``
        makes it unreachable from a real deal anyway. Reporting it as flagged would
        block a handover for a data error, which is the wrong failure.
        """
        row = await self._db.execute(
            select(
                ExporterGstin.flag_status,
                ExporterGstin.state_name,
                ExporterGstin.state_code,
            ).where(ExporterGstin.id == gst_registration_id)
        )
        found = row.one_or_none()
        if found is None:
            return (False, None)
        flagged = found.flag_status is GstRegistrationFlag.FLAGGED
        return (flagged, found.state_name or found.state_code)

    async def is_active(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]:
        """Whether this registration is still active, and how to name its branch.

        ``(True, None)`` for a registration that does not exist, for the reason
        ``is_flagged`` gives: a data error is not a reason to block a handover, and
        the composite FK makes it unreachable from a real deal.
        """
        row = await self._db.execute(
            select(
                ExporterGstin.active,
                ExporterGstin.state_name,
                ExporterGstin.state_code,
            ).where(ExporterGstin.id == gst_registration_id)
        )
        found = row.one_or_none()
        if found is None:
            return (True, None)
        return (bool(found.active), found.state_name or found.state_code)

    async def has_active_registrations(self, company_id: uuid.UUID) -> bool:
        """Whether this company has any branch it could invoice from.

        The branch-recorded rule asks a deal to say which branch it is invoiced from — but
        only of a seller that has one. A seller with no active GST registration is not
        asked, because some legitimately have none and blocking them on a field they
        cannot fill would make the rule a nuisance rather than a control.

        **Active only.** A deactivated registration is part of the record — a deal
        handed over through it still names it — but it is not a branch new trade can
        be invoiced from, so a company whose only registration is deactivated is in
        the same position as one with none.
        """
        found = await self._db.scalar(
            select(ExporterGstin.id)
            .where(
                ExporterGstin.customer_id == company_id,
                ExporterGstin.active.is_(True),
            )
            .limit(1)
        )
        return found is not None


__all__ = ["BranchFlagService"]
