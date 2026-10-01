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
    """The deal's buyer **as a company record** (plan P4-4), summarised.

    Distinct from ``DealBuyerView``, which is the legacy per-deal ``deal_buyer``
    row, and the two coexist on purpose: a deal written before the buyer migration
    (P4-6) has only the second, a deal written after it has the first, and the
    handover guard accepts either. A deal in the middle of the migration may
    briefly have both, with the company as the authority.

    A summary rather than the whole company: enough to recognise the buyer and
    click through to it. ``pipeline_status`` is ``None`` until Developer 3's F3
    column exists.
    """

    #: `exporter_profile.customer_id` — the business key every CRM link uses.
    company_id: uuid.UUID
    name: str | None
    country: str | None
    #: `IN_PIPELINE` / `NOT_IN_PIPELINE`, by name. `None` before F3.
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
    #: The buyer as a company record, once one is recorded (P4-4). The shape is
    #: fixed from F2 so the company screens can be built against it; it is `None`
    #: on every deal until P4-4 starts writing `deal.buyer_company_id`.
    buyer_company: BuyerCompanyView | None
    #: What the lending team was given, as stored (P2-7): `{buyer,
    #: buyer_company_id, document_ids, snapshot_source, snapshot_at}`. `None` on a
    #: deal that has not been handed over. Served as-is, with the buyer's
    #: identifiers masked by role in `schemas/deal.py` — the stored value is never
    #: masked, because the record of a handover must not depend on who reads it.
    handover_snapshot: dict[str, Any] | None
    #: The seller's invoicing branch, once P6-6 records one.
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
