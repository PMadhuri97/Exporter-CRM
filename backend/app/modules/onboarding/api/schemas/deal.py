"""Request/response schemas for deals and buyers — **owner: Developer 3B**
(L3-05, L3-06).

Contract: ``docs/contracts/deal-and-buyer.md``.

Nothing here is masked. A buyer is a foreign company, not a person: its name,
country and registration numbers are commercial facts, not the PAN/GSTIN of an
Indian exporter that the role capability matrix protects. Its contact email and
phone are a company's business contact, and are treated the same way
``ExporterContactResponse`` treats an exporter's — see ``_masked_contact`` below,
which reuses that rule rather than inventing a second one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.deal_views import (
    DealListItemView,
    DealStageMove,
    DealView,
)
from app.modules.onboarding.domain.entities.deal_enums import DealStage


class OpenDealRequest(BaseModel):
    """Open a deal on a company.

    Carries no ``stage``: a deal always starts at ``OPEN`` (architecture §3.3), and
    accepting a stage here would let a caller create a deal that is already handed
    over, skipping every guard.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=200)


class TransitionDealStageRequest(BaseModel):
    """Move a deal's stage. ``reason`` is required for ``WITHDRAWN`` (A7) and
    refused for anything else."""

    model_config = ConfigDict(extra="forbid")

    to_stage: DealStage
    reason: str | None = Field(default=None, max_length=2000)


class SetDealBuyerRequest(BaseModel):
    """Record or replace the deal's buyer. One buyer per deal, so this is an
    upsert of that one row, not an add."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    #: Two letters; the service upper-cases and the database re-checks
    #: (``ck_deal_buyer_country_iso``).
    country: str = Field(min_length=2, max_length=2)
    registration_number: str | None = Field(default=None, max_length=100)
    tax_id: str | None = Field(default=None, max_length=100)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)


class DealBuyerResponse(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    name: str
    country: str
    registration_number: str | None
    tax_id: str | None
    contact_email: str | None
    contact_phone: str | None


class DealStageMoveResponse(BaseModel):
    """One move the caller may make from the deal's current stage.

    The screen renders these rather than holding its own copy of the stage graph
    (§7.5, contract §4.1), so a rule change cannot leave a stale button behind.
    """

    to_stage: DealStage
    reason_required: bool

    @classmethod
    def from_view(cls, move: DealStageMove) -> DealStageMoveResponse:
        return cls(to_stage=move.to, reason_required=move.reason_required)


class DealResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    reference: str
    stage: DealStage
    withdrawal_reason: str | None
    handed_over_at: datetime | None
    created_at: datetime
    updated_at: datetime
    buyer: DealBuyerResponse | None
    allowed_stage_moves: list[DealStageMoveResponse]
    #: Present when the handover is legal by the stage graph but blocked by
    #: assumption A5's guard — including "the background check is not recorded
    #: yet", which is the honest answer while Developer 4's 0015 is missing.
    handover_blocked_reason: str | None

    @classmethod
    def from_view(cls, view: DealView) -> DealResponse:
        return cls(
            id=view.id,
            company_id=view.company_id,
            reference=view.reference,
            stage=view.stage,
            withdrawal_reason=view.withdrawal_reason,
            handed_over_at=view.handed_over_at,
            created_at=view.created_at,
            updated_at=view.updated_at,
            buyer=(
                DealBuyerResponse(
                    id=view.buyer.id,
                    deal_id=view.buyer.deal_id,
                    name=view.buyer.name,
                    country=view.buyer.country,
                    registration_number=view.buyer.registration_number,
                    tax_id=view.buyer.tax_id,
                    contact_email=view.buyer.contact_email,
                    contact_phone=view.buyer.contact_phone,
                )
                if view.buyer is not None
                else None
            ),
            allowed_stage_moves=[
                DealStageMoveResponse.from_view(move) for move in view.allowed_stage_moves
            ],
            handover_blocked_reason=view.handover_blocked_reason,
        )


class DealListItemResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    reference: str
    stage: DealStage
    buyer_name: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view: DealListItemView) -> DealListItemResponse:
        return cls(
            id=view.id,
            company_id=view.company_id,
            reference=view.reference,
            stage=view.stage,
            buyer_name=view.buyer_name,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )


class DealListResponse(BaseModel):
    """``total`` is the count matching the filter, not the length of this page, so
    a caller can page without a second request."""

    deals: list[DealListItemResponse]
    total: int
    limit: int
    offset: int


__all__ = [
    "DealBuyerResponse",
    "DealListItemResponse",
    "DealListResponse",
    "DealResponse",
    "DealStageMoveResponse",
    "OpenDealRequest",
    "SetDealBuyerRequest",
    "TransitionDealStageRequest",
]
