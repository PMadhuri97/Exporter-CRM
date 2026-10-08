"""Read-model view types for deals and buyers.

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
from typing import Any

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
class BuyerCompanyView:
    """The deal's buyer **as a company record**, summarised.

    Distinct from ``DealBuyerView``, which is the legacy per-deal ``deal_buyer``
    row, and the two coexist on purpose: a deal written before the buyer migration
    has only the second, a deal written after it has the first, and the handover
    accepts either. A deal in the middle of the migration may briefly have
    both, with the company as the authority.

    A summary rather than the whole company: enough to recognise the buyer and
    click through to it. ``pipeline_status`` is ``None`` on a database before
    migration 0032.
    """

    #: `exporter_profile.customer_id` — the business key every CRM link uses.
    company_id: uuid.UUID
    name: str | None
    country: str | None
    #: `IN_PIPELINE` / `NOT_IN_PIPELINE`, by name. `None` before migration 0032.
    pipeline_status: str | None
    #: Masked by role in `schemas/deal.py`, by the same rule and the same helpers
    #: the company response uses — never by this layer.
    pan: str | None
    cin: str | None


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
    #: The buyer as a company record, once one is recorded; `None` on a deal whose
    #: `deal.buyer_company_id` is not set.
    buyer_company: BuyerCompanyView | None
    #: What the lending team was given, as stored: `{buyer,
    #: buyer_company_id, document_ids, snapshot_source, snapshot_at}`. `None` on a
    #: deal that has not been handed over. Served as-is, with the buyer's
    #: identifiers masked by role in `schemas/deal.py` — the stored value is never
    #: masked, because the record of a handover must not depend on who reads it.
    handover_snapshot: dict[str, Any] | None
    #: The seller's invoicing branch, once the deal records one.
    seller_gst_registration_id: uuid.UUID | None
    allowed_stage_moves: tuple[DealStageMove, ...]
    #: Why the handover is not on offer, when it is not: **every** unmet condition
    #: from `handover_conditions.HANDOVER_CONDITIONS`, joined with `"; "` — for
    #: example "the company is PROSPECT, not CUSTOMER; the background check is
    #: FLAGGED, not CLEAR". ``None`` when the handover *is* available, or when the
    #: deal is nowhere near it. The screen explains instead of offering a button
    #: that 409s (deal contract §4.1, §6.1).
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


#: The ``corridor`` filter value for deals whose corridor cannot be worked out yet:
#: no buyer recorded, or a party with no country on its record.
UNKNOWN_CORRIDOR = "UNKNOWN"


@dataclass(frozen=True)
class DealSummaryView:
    """One row of the list of every deal, across companies.

    Both parties are named, because unlike a company's own list there is no page
    whose company goes without saying. The buyer is the buyer company once the deal
    has one, and the older ``deal_buyer`` details otherwise.

    ``corridor`` is worked out, never stored: the seller's country, then the
    buyer's, as ``"IN-US"``. ``None`` while either country is unknown — most often
    because no buyer has been recorded yet. Stored, it could disagree with the
    parties it is about.
    """

    id: uuid.UUID
    reference: str
    stage: DealStage
    seller_company_id: uuid.UUID
    seller_name: str | None
    seller_country: str | None
    buyer_company_id: uuid.UUID | None
    buyer_name: str | None
    buyer_country: str | None
    corridor: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CorridorCountView:
    """A corridor some deal is on, and how many deals are. ``corridor`` is ``None``
    for the deals whose corridor is not known yet."""

    corridor: str | None
    deals: int


@dataclass(frozen=True)
class DealFilters:
    """What the list of every deal is narrowed by. Every field is optional, and the
    ones given must all hold.

    ``corridors`` may include ``UNKNOWN_CORRIDOR``. ``company_id`` matches the
    company on **either** side; a buyer that is still a ``deal_buyer`` row is not a
    company, so it cannot match. ``opened_from`` is inclusive and ``opened_before``
    exclusive, so a day is ``[midnight, next midnight)`` in whatever zone the
    caller meant.
    """

    corridors: tuple[str, ...] = ()
    stages: tuple[DealStage, ...] = ()
    search: str | None = None
    company_id: uuid.UUID | None = None
    #: One side each, and both together answer "the deals between these two". Separate
    #: from ``company_id``, which matches either side: giving that the same company
    #: twice would be the same question as giving it once, so a pair needs its own
    #: fields. Each works alone — every deal this company sold, or bought.
    seller_company_id: uuid.UUID | None = None
    buyer_company_id: uuid.UUID | None = None
    opened_from: datetime | None = None
    opened_before: datetime | None = None
