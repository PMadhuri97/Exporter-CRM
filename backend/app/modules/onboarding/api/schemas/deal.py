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
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema

from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_email,
    mask_identifier,
    mask_phone,
)
from app.modules.onboarding.domain.deal_views import (
    BuyerCompanyView,
    DealListItemView,
    DealStageMove,
    DealView,
)
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.deal_required_document import (
    DealRequiredDocument,
)
from app.modules.onboarding.domain.entities.document_enums import DocumentCategory
from app.platform.authentication.models import User, UserRole

#: Who may move a deal — the roles `_STAFF` admits on the move routes
#: (`deal_router.py`). Anyone else is served no moves and no blocked reason: they
#: could not act on either, and the reason names the company's background check,
#: which decision D8 keeps from DEVELOPER.
_MOVING_ROLES = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN})

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


class BuyerCompanyResponse(BaseModel):
    """The deal's buyer as a company record (plan P4-4), summarised.

    `pan` and `cin` are masked for OPERATIONS and DEVELOPER by exactly the rule
    the company response uses — the buyer being a company does not make its
    identifiers more visible than the seller's.

    `pipeline_status` is `null` until Developer 3's F3 column exists. The field is
    in the shape from F2 on purpose: the company screens are built against this
    response, and adding a field to it later would be a contract change.
    """

    company_id: uuid.UUID
    name: str | None
    country: str | None
    pipeline_status: str | None
    pan: str | None
    cin: str | None

    @classmethod
    def from_view(cls, view: BuyerCompanyView, viewer: User) -> BuyerCompanyResponse:
        reveal = can_reveal_identifiers(viewer)
        return cls(
            company_id=view.company_id,
            name=view.name,
            country=view.country,
            pipeline_status=view.pipeline_status,
            pan=view.pan if reveal else mask_identifier(view.pan),
            cin=view.cin if reveal else mask_identifier(view.cin),
        )


#: The stored handover snapshot, as the API serves it: an **open** map.
#:
#: Pydantic writes a bare ``{"type": "object"}`` for a ``dict``, and
#: ``openapi-typescript`` renders that as the uninhabited ``Record<string,
#: never>`` — a generated client that cannot read a single key. Attaching the
#: schema to the ``dict`` itself (rather than to the field, where it would land
#: outside the ``anyOf`` branch and be ignored) makes it
#: ``{ [key: string]: unknown }``, which is what the deal page actually reads.
HandoverSnapshot = Annotated[
    dict[str, Any],
    WithJsonSchema({"type": "object", "additionalProperties": True}),
]


def _masked_snapshot(
    snapshot: dict[str, Any] | None, viewer: User
) -> dict[str, Any] | None:
    """The handover snapshot as this viewer may see it.

    The **stored** snapshot is never masked: it is the record of what the lending
    team was given, and a record that changed shape with its reader would be
    useless. Masking happens here, on the way out, over the same fields
    `DealBuyerResponse` masks and through the same helpers — so a buyer's tax
    identifiers are no more visible inside a snapshot than outside one.

    Anything in the snapshot this function does not recognise is passed through
    untouched: `snapshot_source`, `snapshot_at`, `document_ids` and
    `buyer_company_id` carry no identifiers. A new identifier-bearing key would
    have to be added here deliberately, which is the point of listing them.
    """
    if snapshot is None or can_reveal_identifiers(viewer):
        return snapshot

    buyer = snapshot.get("buyer")
    if not isinstance(buyer, dict):
        return snapshot
    return {
        **snapshot,
        "buyer": {
            **buyer,
            "registration_number": mask_identifier(buyer.get("registration_number")),
            "tax_id": mask_identifier(buyer.get("tax_id")),
            "contact_email": mask_email(buyer.get("contact_email")),
            "contact_phone": mask_phone(buyer.get("contact_phone")),
        },
    }


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
    #: The buyer as a company record (P4-4). `null` on every deal whose buyer is
    #: still a `deal_buyer` row, which is every deal until P4-6 runs.
    buyer_company: BuyerCompanyResponse | None
    #: What the lending team was given, frozen at the moment of the handover
    #: (P2-7): `{buyer, buyer_company_id, document_ids, snapshot_source,
    #: snapshot_at}`. `null` until the deal is handed over. The buyer's
    #: identifiers inside it are masked by the same rule as `buyer`'s.
    #:
    #: `snapshot_source` is `taken_at_handover` for a snapshot written by the
    #: handover itself and `backfilled_from_deal_buyer` for one reconstructed by
    #: migration 0026 from the records that existed — so a reader can tell a
    #: record from a reconstruction.
    #:
    #: An open map rather than a model on purpose: it is served **as stored**, and
    #: migration 0026's backfill builds its `buyer` from `to_jsonb(deal_buyer)`,
    #: so a buyer column added later appears in new snapshots. A fixed model would
    #: silently drop that from the response — hiding part of the very record this
    #: field exists to preserve.
    #:
    #: Typed as `HandoverSnapshot` rather than `dict`: see that alias for why.
    handover_snapshot: HandoverSnapshot | None
    #: The seller's GST registration this deal is invoiced from (P6-6). `null` on
    #: every deal until that task records one.
    seller_gst_registration_id: uuid.UUID | None
    allowed_stage_moves: list[DealStageMoveResponse]
    #: Present when the handover is legal by the stage graph but blocked by
    #: assumption A5's guard; it names every unmet condition, journey first.
    handover_blocked_reason: str | None

    @classmethod
    def from_view(cls, view: DealView, viewer: User) -> DealResponse:
        """``viewer`` decides whether the buyer's identifiers and contact details
        are shown in full, and whether the stage moves and the blocked reason are
        served at all (only to a role that may move the deal) — required, so no
        route can forget to pass it."""
        may_move = viewer.role in _MOVING_ROLES
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
            buyer_company=(
                BuyerCompanyResponse.from_view(view.buyer_company, viewer)
                if view.buyer_company is not None
                else None
            ),
            handover_snapshot=_masked_snapshot(view.handover_snapshot, viewer),
            seller_gst_registration_id=view.seller_gst_registration_id,
            allowed_stage_moves=[
                DealStageMoveResponse.from_view(move) for move in view.allowed_stage_moves
            ]
            if may_move
            else [],
            handover_blocked_reason=view.handover_blocked_reason if may_move else None,
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


class SetDealRequiredDocumentRequest(BaseModel):
    """Add a required document category to a deal's handover rule, or stop
    requiring it. ADMIN only.

    There is no delete: the table is append-only, so "stop requiring it" is
    `active: false`, which writes a new version. The record of what was required
    when is part of the point (plan P2-5a).
    """

    model_config = ConfigDict(extra="forbid")

    category: DocumentCategory
    #: Leave out or send `null` for "any document in this category" — the shape
    #: the seeded `PRE_SHIPMENT` requirement uses. Name a type to narrow it.
    document_type: str | None = Field(default=None, max_length=100)
    active: bool = Field(
        default=True,
        description=(
            "`true` requires the category, `false` stops requiring it. Either way "
            "a new version is written; nothing is updated or deleted."
        ),
    )


class DealRequiredDocumentResponse(BaseModel):
    """One version of one requirement."""

    id: uuid.UUID
    category: DocumentCategory
    #: `null` for "any document in this category". The stored sentinel (`''`)
    #: never reaches a caller.
    document_type: str | None
    version: int
    active: bool
    created_by: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, row: DealRequiredDocument) -> DealRequiredDocumentResponse:
        return cls(
            id=row.id,
            category=row.category,
            document_type=row.document_type or None,
            version=row.version,
            active=row.active,
            created_by=row.created_by,
            created_at=row.created_at,
        )


class DealRequiredDocumentsResponse(BaseModel):
    """The handover rule as it stands, and how it got there.

    `requirements` is the current version of every key, `active` or not, so a
    screen can show that something was removed rather than merely not showing it.
    `history` is every version ever written, newest first per key.
    """

    requirements: list[DealRequiredDocumentResponse]
    history: list[DealRequiredDocumentResponse]
    can_edit: bool = Field(
        default=False,
        description=(
            "Whether **this** caller may change the rule (ADMIN). The screen "
            "offers the controls from this rather than checking the role itself "
            "(§7.5)."
        ),
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
    "BuyerCompanyResponse",
    "DealBuyerResponse",
    "DealRequiredDocumentResponse",
    "DealRequiredDocumentsResponse",
    "DealListItemResponse",
    "DealListResponse",
    "DealResponse",
    "DealStageMoveResponse",
    "OpenDealRequest",
    "SetDealBuyerRequest",
    "SetDealRequiredDocumentRequest",
    "TransitionDealStageRequest",
]
