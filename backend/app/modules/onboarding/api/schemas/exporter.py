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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    """Create a company. `source` and `lifecycle_status` are the only
    lifecycle-relevant fields the caller may set at creation — `source`
    becomes immutable the moment this succeeds (see
    `ExporterSourceImmutableError`); `lifecycle_status` after creation can
    only move through `POST .../transition`.

    `name` and `country` are the company's identity
    (`docs/contracts/company-record.md` §2.1). Supplying them — always
    together — creates a named company through
    `ExporterProfileService.create_lead`, and requires the `Idempotency-Key`
    header so a retried submit returns the first company rather than a
    second. The creator's contact details are never asked for: the service
    takes them from the signed-in user.

    Omitting both keeps the older unnamed path (`create_or_get_profile`),
    which some callers still use to open a company by `customer_id` alone.
    Migration 0014 makes the name a required column on the company record,
    at which point this path either takes a name too or goes.

    `customer_id` is optional: when omitted, the API mints a fresh one.
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

    #: The company's legal name. 255 characters: the most the store behind it
    #: holds today (the old 500 here was more than it could keep).
    name: str | None = Field(default=None, max_length=255)
    #: Country of incorporation, ISO 3166-1 alpha-2 (`IN`).
    country: str | None = Field(default=None, max_length=2)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("country")
    @classmethod
    def _country_is_alpha2(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if len(cleaned) != 2 or not cleaned.isascii() or not cleaned.isalpha():
            raise ValueError("country must be a two-letter ISO 3166-1 code, e.g. IN")
        return cleaned

    @model_validator(mode="after")
    def _identity_both_or_neither(self) -> CreateExporterProfileRequest:
        if (self.name is None) != (self.country is None):
            raise ValueError(
                "name and country must be supplied together (to create a named "
                "company) or not at all"
            )
        return self


class UpdateExporterProfileRequest(BaseModel):
    """Update mutable CRM fields. A field left out is unchanged; a field sent
    as `null` (or an empty string or list) is cleared — the router keeps the
    two apart with `exclude_unset=True`. Every change is recorded in the
    company's history, with the signed-in user as the actor; there is no actor
    field here, and `extra="forbid"` refuses one.

    `source` and `lifecycle_status` are deliberately not fields on this model
    at all — with `extra="forbid"`, sending either is rejected at the API
    boundary (422) before the request ever reaches
    `ExporterProfileService.update_profile`'s own guard.
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


class ExporterProfileDetailResponse(_IdentifierMasking, BaseModel):
    customer_id: uuid.UUID
    name: str | None
    country: str | None
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

    @classmethod
    def from_detail(cls, detail) -> ExporterProfileDetailResponse:
        return cls(
            customer_id=detail.customer_id,
            name=detail.name,
            country=detail.country,
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
        )


class ExporterProfileListItemResponse(_IdentifierMasking, BaseModel):
    """One row of `GET /onboarding/exporters` — `ExporterProfileResponse`
    plus the company's `name` and `country`, fetched for the whole page at
    once (see `ExporterProfileService.search_profiles`), so a list screen never
    needs a second, per-row lookup just to show a company name."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    name: str | None
    country: str | None
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
