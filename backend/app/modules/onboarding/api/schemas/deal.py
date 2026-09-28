"""Request/response schemas for deals and buyers — **owner: Developer 3B**
(L3-05, L3-06).

Contract: ``docs/contracts/deal-and-buyer.md``.

**The buyer's identifiers and contact details are masked** for every role that
may not see an exporter's PAN/GSTIN — the same rule, through the same helpers
(``masking.py``, ``can_reveal_identifiers``): COMPLIANCE and ADMIN see them in
full; OPERATIONS and DEVELOPER see ``registration_number`` and ``tax_id`` with
only the last four characters, the email as ``a•••@domain`` and the phone with
its last four digits. The buyer's name and country stay visible to everyone: a
deal is unrecognisable without them.

(This module used to say nothing here was masked and point at a
``_masked_contact`` helper that was never written, so the contact details — and
the tax identifiers — reached every reader in full.)

The write side mirrors the company record: a masked value is refused rather than
saved (``NotMasked``), and a masked field **left out** of the buyer request keeps
its stored value, so a role that only ever sees the masked form can still edit
the rest of the buyer without erasing what it cannot see.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_email,
    mask_identifier,
    mask_phone,
)
from app.modules.onboarding.domain.deal_views import (
    DealListItemView,
    DealStageMove,
    DealView,
)
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.platform.authentication.models import User

#: The buyer fields a masked role never sees in full, and which a buyer request
#: may therefore leave out to mean "keep what is stored".
BUYER_MASKED_FIELDS: tuple[str, ...] = (
    "registration_number",
    "tax_id",
    "contact_email",
    "contact_phone",
)


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
    upsert of that one row, not an add.

    ``registration_number``, ``tax_id``, ``contact_email`` and ``contact_phone``
    are masked for OPERATIONS and DEVELOPER. Leave one out to keep its stored
    value; send ``null`` or an empty string to clear it; a masked value is
    refused (422)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    #: Two letters; the service upper-cases and the database re-checks
    #: (``ck_deal_buyer_country_iso``).
    country: str = Field(min_length=2, max_length=2)
    registration_number: Annotated[str | None, NotMasked] = Field(default=None, max_length=100)
    tax_id: Annotated[str | None, NotMasked] = Field(default=None, max_length=100)
    contact_email: Annotated[str | None, NotMasked] = Field(default=None, max_length=255)
    contact_phone: Annotated[str | None, NotMasked] = Field(default=None, max_length=50)

    def fields_to_keep(self) -> frozenset[str]:
        """The masked fields the caller left out — their stored values stay."""
        return frozenset(BUYER_MASKED_FIELDS) - self.model_fields_set


class DealBuyerResponse(BaseModel):
    """The deal's buyer. The identifiers and contact details are masked for
    OPERATIONS and DEVELOPER; COMPLIANCE and ADMIN see them in full."""

    id: uuid.UUID
    deal_id: uuid.UUID
    name: str
    country: str
    registration_number: str | None
    tax_id: str | None
    contact_email: str | None
    contact_phone: str | None

    def masked_for(self, viewer: User) -> DealBuyerResponse:
        """The same reveal rule as the exporter's identifiers and contacts."""
        if can_reveal_identifiers(viewer):
            return self
        return self.model_copy(
            update={
                "registration_number": mask_identifier(self.registration_number),
                "tax_id": mask_identifier(self.tax_id),
                "contact_email": mask_email(self.contact_email),
                "contact_phone": mask_phone(self.contact_phone),
            }
        )


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
    def from_view(cls, view: DealView, viewer: User) -> DealResponse:
        """``viewer`` decides whether the buyer's identifiers and contact details
        are shown in full — required, so no route can forget to pass it."""
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
                ).masked_for(viewer)
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
    can_open_deal: bool = Field(
        default=False,
        description=(
            "Whether **this** caller may open a deal on this company now: a staff role, "
            "and the company is a `PROSPECT` or `CUSTOMER` (a `LEAD` is refused with "
            "409 `DEAL_COMPANY_NOT_READY`). The screen offers the action from this "
            "rather than keeping its own copy of the rule (§7.5)."
        ),
    )


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
