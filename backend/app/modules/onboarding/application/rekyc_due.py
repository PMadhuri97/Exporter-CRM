"""The "Re-KYC due" list — companies whose Clear has expired or soon will — **owner:
Developer 1** (compliance engine; plan P3-3c, allocation §1 adjustment 3).

Its own read, in the background-check area, rather than a filter on Developer 3's
``search_profiles`` (allocation §1, adjustment 3).

**What it lists.** Companies whose background check is ``CLEAR`` and whose current
Clear expires before ``before``: the ones already expired first, then the soonest. It
reads ``exporter_profile.background_check_expires_at`` — the current value
``BackgroundCheckService`` sets on every ``CLEAR`` and clears on every move away, and
migration 0027 backfilled for the companies already cleared (BQ-5) — through its
partial index.

**Company- and cycle-aware.** One row per company (the subject of the check, whatever
role it plays in a deal), with the number of its current check cycle. A company whose
Re-KYC has started is not listed: starting a cycle on a ``CLEAR`` company reopens it
(IQ-3), which clears the expiry.

**No automatic move.** An expired Clear stays ``CLEAR`` (P3-3b); this list, the
company's gauge badge and the facts its consumers read are how it shows.

Read-only: never commits, flushes, writes or locks. No identifier is read: the
company's name, journey and expiry only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile


@dataclass(frozen=True)
class ReKycDueCompany:
    company_id: uuid.UUID
    company_name: str | None
    journey: str
    background_check: BackgroundCheckState
    expires_at: datetime
    is_expired: bool
    current_cycle_number: int | None
    #: Whether the company is in the sales pipeline or exists only as a buyer (R-29):
    #: a buyer-only company's Re-KYC is about trade it is bought on, not a lead.
    pipeline_status: str


async def rekyc_due(
    db: AsyncSession,
    *,
    before: datetime,
    now: datetime,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ReKycDueCompany], int]:
    """CLEAR companies whose Clear expires before ``before``, soonest (or longest
    expired) first, and how many there are. ``is_expired`` is relative to ``now``."""
    if before.tzinfo is None or now.tzinfo is None:
        raise ValueError("rekyc_due needs timezone-aware `before` and `now`")
    expires = ExporterProfile.background_check_expires_at
    conditions = (
        ExporterProfile.background_check == BackgroundCheckState.CLEAR,
        expires.is_not(None),
        expires < before,
    )
    current_cycle = (
        select(func.max(CheckCycle.number))
        .where(CheckCycle.company_id == ExporterProfile.customer_id)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(
                ExporterProfile.customer_id,
                ExporterProfile.name,
                ExporterProfile.journey,
                ExporterProfile.background_check,
                expires,
                current_cycle,
                ExporterProfile.pipeline_status,
            )
            .where(*conditions)
            .order_by(expires.asc(), ExporterProfile.customer_id.asc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = await db.scalar(
        select(func.count()).select_from(ExporterProfile).where(*conditions)
    )
    return (
        [
            ReKycDueCompany(
                company_id=row[0],
                company_name=row[1],
                journey=str(getattr(row[2], "value", row[2])),
                background_check=row[3],
                expires_at=row[4],
                is_expired=row[4] <= now,
                current_cycle_number=row[5],
                pipeline_status=str(getattr(row[6], "value", row[6])),
            )
            for row in rows
        ],
        int(total or 0),
    )


__all__ = ["ReKycDueCompany", "rekyc_due"]
