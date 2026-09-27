"""Read-model view types for deals and buyers — **owner: Developer 3B** (L3-05,
L3-06).

Pure data structures — no I/O, no session — the same pattern as
``engagement_views.py`` and ``exporter_profile_views.py``. ``DealService``
assembles them.

``DealStageMove`` is the rules as data: the screen asks the server which moves it
may offer rather than keeping a copy of the table (§7.5, deal contract §4.1), so
a rule change here cannot leave a stale button behind in ``DealDetailPage.tsx``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.onboarding.domain.entities.deal_enums import DealStage


@dataclass(frozen=True)
class DealBuyerView:
    id: uuid.UUID
    deal_id: uuid.UUID
    name: str
    country: str
    registration_number: str | None
    tax_id: str | None
    contact_email: str | None
    contact_phone: str | None


@dataclass(frozen=True)
class DealStageMove:
    """One move this viewer may make, and what it needs.

    ``reason_required`` lets the screen ask for the withdrawal reason *before*
    submitting, rather than showing a 422 afterwards.
    """

    to: DealStage
    reason_required: bool


@dataclass(frozen=True)
class DealView:
    """One deal, its buyer, and what may be done to it next."""

    id: uuid.UUID
    company_id: uuid.UUID
    reference: str
    stage: DealStage
    withdrawal_reason: str | None
    handed_over_at: datetime | None
    created_at: datetime
    updated_at: datetime
    buyer: DealBuyerView | None
    allowed_stage_moves: tuple[DealStageMove, ...]
    #: Why the handover is not on offer, when it is not: "the company is not a
    #: CUSTOMER", "the background check is not CLEAR", or — while Developer 4's
    #: migration 0015 is missing — "the background check is not recorded yet".
    #: ``None`` when the handover *is* available, or when the deal is nowhere near
    #: it. The screen explains instead of offering a button that 409s
    #: (deal contract §4.1).
    handover_blocked_reason: str | None


@dataclass(frozen=True)
class DealListItemView:
    """One row of a company's deal list.

    Carries the buyer's name rather than the whole buyer: a list wants something
    readable per row, and the full buyer is one request away.
    """

    id: uuid.UUID
    company_id: uuid.UUID
    reference: str
    stage: DealStage
    buyer_name: str | None
    created_at: datetime
    updated_at: datetime
