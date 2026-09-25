"""Request/response schemas for the company record — **owner: Developer 2**
(architecture §8.1, §9.2).

This file used to carry every Exporter CRM shape. L2-01 split it by owner:

  exporter.py    the company record and journey      Developer 2
  engagement.py  contacts and the activity log       Developer 3
  screening.py   screening checklist, bank activity  Developer 4
  masking.py     tax-ID and contact masking (L1-10)  Developer 1

The detail response still embeds the contact and activity shapes, because the
company detail page shows them; it imports them rather than restating them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.onboarding.api.schemas.engagement import (
    ExporterActivityResponse,
    ExporterContactResponse,
)
from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_identifier,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRejectionCategory,
    OnboardingRequestStatus,
)
from app.platform.authentication.models import User


class _IdentifierMasking:
    """Mixin for the exporter responses carrying gstin/pan/iec (and, on the
    detail response, contacts). Every route returning one of them must pass it
    through `masked_for(current_user)` before returning it."""

    def masked_for(self, viewer: User) -> Self:
        if can_reveal_identifiers(viewer):
            return self
        update = {
            "gstin": mask_identifier(self.gstin),
            "pan": mask_identifier(self.pan),
            "iec": mask_identifier(self.iec),
        }
        if "contacts" in type(self).model_fields:
            update["contacts"] = [contact.masked() for contact in self.contacts]
        return self.model_copy(update=update)


class CreateExporterProfileRequest(BaseModel):
    """Create a profile. `source` and `lifecycle_status` are the only
    lifecycle-relevant fields the caller may set at creation — `source`
    becomes immutable the moment this succeeds (see
    `ExporterSourceImmutableError`); `lifecycle_status` after creation can
    only move through `POST .../transition`.

    `customer_id` is optional: when omitted, the API mints a fresh one — the
    common case for a brand-new Lead, which has no prior `OnboardingRequest`
    or other identity to anchor to. A caller onboarding an *existing*
    `OnboardingRequest.customer_id` (backfilling a profile for a customer who
    already has verification history) supplies it explicitly.

    `legal_name`/`incorporation_country`/`initial_user_email` (EXP-3, "Add
    Exporter"): supplying all three routes this request through
    `ExporterProfileService.create_lead` instead of `create_or_get_profile`,
    creating a minimal `OnboardingRequest` alongside the profile so the new
    Lead actually has a name — see `create_lead`'s own docstring for why
    `create_or_get_profile` alone can never give a Lead a `legal_name`. All
    three are required together (enforced below) or none at all; omitting
    all three keeps this request on the `create_or_get_profile` path exactly
    as before. `initial_user_email` is a reachable contact for the Lead (the
    Sales rep's own address, a lead-intake mailbox, whatever channel sourced
    it) — not necessarily the exporter's own future platform login; see
    `OnboardingRequestService.initiate_onboarding`'s docstring for the full
    reasoning (`create_lead` reuses the same field for the same reason).
    Creating a Lead this way also requires the `Idempotency-Key` header
    (unlike the `create_or_get_profile` path, where it's optional) — a fresh
    `OnboardingRequest` row has a `NOT NULL` idempotency key with no other
    natural uniqueness to fall back on the way `exporter_profile.customer_id`
    provides for the other path.
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: uuid.UUID | None = None
    source: ExporterSource
    lifecycle_status: ExporterLifecycleStatus = ExporterLifecycleStatus.LEAD
    gstin: Annotated[str | None, NotMasked] = Field(default=None, max_length=15)
    pan: Annotated[str | None, NotMasked] = Field(default=None, max_length=10)
    iec: Annotated[str | None, NotMasked] = Field(default=None, max_length=10)
    relationship_manager: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    export_markets: list[str] | None = None
    products: list[str] | None = None
    year_established: int | None = None
    website: str | None = Field(default=None, max_length=2048)

    legal_name: str | None = Field(default=None, min_length=1, max_length=500)
    incorporation_country: str | None = Field(default=None, min_length=2, max_length=2)
    initial_user_email: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _lead_fields_all_or_nothing(self) -> CreateExporterProfileRequest:
        lead_fields = (self.legal_name, self.incorporation_country, self.initial_user_email)
        if any(lead_fields) and not all(lead_fields):
            raise ValueError(
                "legal_name, incorporation_country and initial_user_email must be "
                "supplied together (to create a new Lead) or not at all"
            )
        return self


class UpdateExporterProfileRequest(BaseModel):
    """Update mutable CRM fields. `source` and `lifecycle_status` are
    deliberately not fields on this model at all — with `extra="forbid"`,
    sending either is rejected at the API boundary (422) before the request
    ever reaches `ExporterProfileService.update_profile`'s own guard.
    """

    model_config = ConfigDict(extra="forbid")

    gstin: Annotated[str | None, NotMasked] = Field(default=None, max_length=15)
    pan: Annotated[str | None, NotMasked] = Field(default=None, max_length=10)
    iec: Annotated[str | None, NotMasked] = Field(default=None, max_length=10)
    relationship_manager: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    export_markets: list[str] | None = None
    products: list[str] | None = None
    year_established: int | None = None
    website: str | None = Field(default=None, max_length=2048)


class TransitionLifecycleStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: ExporterLifecycleStatus


class ExporterProfileResponse(_IdentifierMasking, BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    gstin: str | None
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    #: Which `auth.users` row `relationship_manager` refers to, when known —
    #: `None` today for every existing profile (nothing sets it yet; see
    #: `onboarding_0009_relationship_manager_user`). The frontend uses this,
    #: not the display string, to decide whether the current user may reveal
    #: this exporter's masked PAN/GSTIN/IEC.
    relationship_manager_user_id: uuid.UUID | None
    lifecycle_status: ExporterLifecycleStatus
    industry: str | None
    export_markets: list[str] | None
    products: list[str] | None
    year_established: int | None
    website: str | None
    date_added: datetime
    created_at: datetime
    updated_at: datetime


class OnboardingHistoryEntryResponse(BaseModel):
    onboarding_id: uuid.UUID
    status: OnboardingRequestStatus
    legal_name: str
    initiated_at: datetime | None
    completed_at: datetime | None
    rejection_category: OnboardingRejectionCategory | None


class ExporterProfileDetailResponse(_IdentifierMasking, BaseModel):
    customer_id: uuid.UUID
    gstin: str | None
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    relationship_manager_user_id: uuid.UUID | None
    lifecycle_status: ExporterLifecycleStatus
    industry: str | None
    export_markets: list[str] | None
    products: list[str] | None
    year_established: int | None
    website: str | None
    date_added: datetime
    created_at: datetime
    updated_at: datetime
    contacts: list[ExporterContactResponse]
    recent_activities: list[ExporterActivityResponse]
    onboarding_history: list[OnboardingHistoryEntryResponse]

    @classmethod
    def from_detail(cls, detail) -> ExporterProfileDetailResponse:
        return cls(
            customer_id=detail.customer_id,
            gstin=detail.gstin,
            pan=detail.pan,
            iec=detail.iec,
            source=detail.source,
            relationship_manager=detail.relationship_manager,
            relationship_manager_user_id=detail.relationship_manager_user_id,
            lifecycle_status=detail.lifecycle_status,
            industry=detail.industry,
            export_markets=detail.export_markets,
            products=detail.products,
            year_established=detail.year_established,
            website=detail.website,
            date_added=detail.date_added,
            created_at=detail.created_at,
            updated_at=detail.updated_at,
            contacts=[ExporterContactResponse.model_validate(c) for c in detail.contacts],
            recent_activities=[
                ExporterActivityResponse.model_validate(a) for a in detail.recent_activities
            ],
            onboarding_history=[
                OnboardingHistoryEntryResponse(
                    onboarding_id=h.onboarding_id,
                    status=h.status,
                    legal_name=h.legal_name,
                    initiated_at=h.initiated_at,
                    completed_at=h.completed_at,
                    rejection_category=h.rejection_category,
                )
                for h in detail.onboarding_history
            ],
        )


class ExporterProfileListItemResponse(_IdentifierMasking, BaseModel):
    """One row of `GET /onboarding/exporters` — `ExporterProfileResponse`
    plus `legal_name`, resolved server-side via a join against the
    exporter's most recent `OnboardingRequest` (see
    `ExporterProfileRepository.search`) so a list screen never needs a
    second, per-row lookup just to show a company name."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    legal_name: str | None
    gstin: str | None
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    relationship_manager_user_id: uuid.UUID | None
    lifecycle_status: ExporterLifecycleStatus
    industry: str | None
    year_established: int | None
    date_added: datetime
    created_at: datetime
    updated_at: datetime


class ExporterProfileSearchResponse(BaseModel):
    profiles: list[ExporterProfileListItemResponse]
    limit: int
    offset: int
