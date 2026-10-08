"""Request/response schemas for the company record (architecture §8.1, §9.2).

This file used to carry every Exporter CRM shape. It is now split by area:

  exporter.py    the company record and journey
  engagement.py  contacts and the activity log
  screening.py   screening checklist, bank activity
  masking.py     tax-ID and contact masking

The detail response still embeds the contact and activity shapes, because the
company detail page shows them; it imports them rather than restating them.

Tax identifiers (PAN, GSTINs, CIN) are **checked by the service**
(`domain/tax_identifiers.py`), not here: these shapes only bound their length
generously enough to let the service normalise surrounding spaces and case,
and refuse a value that carries the mask character (`NotMasked`).
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
from app.modules.onboarding.domain.company_identity import REGISTRATION_NUMBER_MAX
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyTradeRole,
    CompanyIdentityType,
    CompanyPipelineStatus,
    ExporterJourney,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.platform.authentication.models import User

#: Room for surrounding spaces the service strips before checking the format.
_IDENTIFIER_MAX = 32

#: A GSTIN as a request may carry it.
_GstinIn = Annotated[str, NotMasked, Field(max_length=_IDENTIFIER_MAX)]


def _clean_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("name must not be blank")
    return cleaned


def _clean_country(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    if len(cleaned) != 2 or not cleaned.isascii() or not cleaned.isalpha():
        raise ValueError("country must be a two-letter ISO 3166-1 code, e.g. IN")
    return cleaned


class _IdentifierMasking:
    """Mixin for the company responses carrying PAN, GSTINs, IEC, CIN and the
    foreign registration number (and, on the detail response, contacts and
    GSTIN warnings). Every route returning one of them must pass it through
    `masked_for(current_user)` before returning it."""

    def masked_for(self, viewer: User) -> Self:
        if can_reveal_identifiers(viewer):
            return self
        update: dict[str, object] = {
            "gstins": [mask_identifier(g) for g in self.gstins],
            "pan": mask_identifier(self.pan),
            "iec": mask_identifier(self.iec),
            "cin": mask_identifier(self.cin),
            # Masked like CIN: a registration number names the company
            # in its own registrar's public index, so it carries the same risk.
            "registration_number": mask_identifier(self.registration_number),
        }
        fields = type(self).model_fields
        if "contacts" in fields:
            update["contacts"] = [contact.masked() for contact in self.contacts]
        if "gstin_warnings" in fields:
            update["gstin_warnings"] = [w.masked() for w in self.gstin_warnings]
        return self.model_copy(update=update)


class DuplicateGstinWarningResponse(BaseModel):
    """One of this company's GSTINs is also held by other companies — a
    warning, never a refusal (architecture decision 4). The other companies
    are named so staff can check they are not entering a duplicate."""

    model_config = ConfigDict(from_attributes=True)

    gstin: str
    other_customer_ids: list[uuid.UUID]

    def masked(self) -> DuplicateGstinWarningResponse:
        return self.model_copy(update={"gstin": mask_identifier(self.gstin)})


class MarkerMoveResponse(BaseModel):
    """A marker move the viewer may make now — served by the server from the
    same table `set_marker` enforces, so no screen keeps its own copy."""

    to: ExporterMarker
    reason_required: bool


class CreateExporterProfileRequest(BaseModel):
    """Create a company. `source` becomes immutable the moment this
    succeeds (see `ExporterSourceImmutableError`). Every company starts as a
    `LEAD`, `NOT_YET_REVIEWED`, with no marker: the journey moves through
    qualification, never through a field set here.

    `name` and `country` are the company's identity
    (`docs/contracts/company-record.md` §2.1). Supplying them — always
    together — creates a named company through
    `ExporterProfileService.create_lead`, and requires the `Idempotency-Key`
    header so a retried submit returns the first company rather than a
    second. The creator's contact details are never asked for.

    Omitting both keeps the older unnamed path (`create_or_get_profile`),
    which some callers still use to open a company by `customer_id` alone.

    `pan` must not already belong to another company (409). `gstins` may
    hold several registrations; each must carry the PAN when one is given, and
    one already held by another company is reported in `gstin_warnings`, not
    refused. A company starts with no marker.

    `customer_id` is optional: when omitted, the API mints a fresh one.

    `website` is **not** a field here any more: with
    `extra="forbid"`, sending one is a 422. The column and every value already
    stored stay as they are — nothing is destroyed, and nothing is shown.
    Only the CSV importer still tolerates the old header, because those files
    come from somebody's machine rather than from this application's own form.
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: uuid.UUID | None = None
    source: ExporterSource
    pan: Annotated[str | None, NotMasked] = Field(default=None, max_length=_IDENTIFIER_MAX)
    gstins: list[_GstinIn] | None = None
    iec: Annotated[str | None, NotMasked] = Field(default=None, max_length=10)
    cin: Annotated[str | None, NotMasked] = Field(default=None, max_length=_IDENTIFIER_MAX)
    #: Whatever the company's own registrar issued, for a company that is not
    #: identified by a PAN. Required for a company outside India;
    #: stored as the registrar writes it and compared without punctuation, so one
    #: number cannot be entered twice per country.
    registration_number: Annotated[str | None, NotMasked] = Field(
        default=None, max_length=REGISTRATION_NUMBER_MAX
    )
    relationship_manager: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    export_markets: list[str] | None = None
    products: list[str] | None = None
    year_established: int | None = None

    #: The company's legal name.
    name: str | None = Field(default=None, max_length=255)
    #: Country of incorporation, ISO 3166-1 alpha-2 (`IN`).
    country: str | None = Field(default=None, max_length=2)

    @field_validator("source")
    @classmethod
    def _not_a_deal_buyer(cls, value: ExporterSource) -> ExporterSource:
        """``DEAL_BUYER`` means "this company exists because it was somebody's
        buyer": it is set by the buyer-company path, which creates the company
        ``NOT_IN_PIPELINE``. Here it would make an in-pipeline lead with a journey
        row — a buyer that is not one."""
        if value is ExporterSource.DEAL_BUYER:
            raise ValueError(
                "source DEAL_BUYER is set only when a company is created as a deal's "
                "buyer; a company added here is a lead, so choose how it reached us"
            )
        return value

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _clean_name(value)

    @field_validator("country")
    @classmethod
    def _country_is_alpha2(cls, value: str | None) -> str | None:
        return _clean_country(value)

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
    two apart with `exclude_unset=True`. `name` and `country` can be
    corrected but not cleared. Every change
    is recorded in the company's history, with the signed-in user as the
    actor; there is no actor field here, and `extra="forbid"` refuses one.

    `source`, the journey, the qualification gauge and the marker are
    deliberately not fields on this model at all — with `extra="forbid"`, sending any of them is
    rejected at the API boundary (422). The marker has its own route. `website`
    joined them when the website field was retired: it can no longer be set or cleared
    here, and a stored value is left untouched.

    **`gstins` joined them.** It used to replace the company's whole
    list, which deleted the row of every GSTIN dropped — and a GST registration is a
    branch the company traded through, named by any deal that invoiced from it.
    Adding one, deactivating one and flagging one are now three decisions with three
    routes under `/exporters/{id}/gst-registrations`, each leaving its own history
    row.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=2)
    pan: Annotated[str | None, NotMasked] = Field(default=None, max_length=_IDENTIFIER_MAX)
    iec: Annotated[str | None, NotMasked] = Field(default=None, max_length=10)
    cin: Annotated[str | None, NotMasked] = Field(default=None, max_length=_IDENTIFIER_MAX)
    #: Whatever the company's own registrar issued, for a company that is not
    #: identified by a PAN. Required for a company outside India;
    #: stored as the registrar writes it and compared without punctuation, so one
    #: number cannot be entered twice per country.
    registration_number: Annotated[str | None, NotMasked] = Field(
        default=None, max_length=REGISTRATION_NUMBER_MAX
    )
    relationship_manager: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    export_markets: list[str] | None = None
    products: list[str] | None = None
    year_established: int | None = None

    @field_validator("country")
    @classmethod
    def _country_is_alpha2(cls, value: str | None) -> str | None:
        # Blank means "clear", which the service refuses with a clear message.
        if value is not None and not value.strip():
            return value
        return _clean_country(value)


class SetMarkerRequest(BaseModel):
    """Set or clear the company's commercial marker (company-record contract
    §3.3). `reason` is required for `PAUSED` and `ENDED`, optional when
    clearing to `NONE`. The marker never moves the journey."""

    model_config = ConfigDict(extra="forbid")

    marker: ExporterMarker
    reason: str | None = Field(default=None, max_length=2000)


class BringIntoPipelineRequest(BaseModel):
    """Bring a buyer-only company into the sales pipeline.

    Only a reason, and it is optional: the decision is the request itself, and
    there is nothing to choose — a company is either in the pipeline or not, and
    this route only moves it in. A reason is worth asking for anyway, because
    "why did we start selling to our buyer" is the question the history row will
    be read to answer.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class ExporterProfileResponse(_IdentifierMasking, BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    name: str | None
    country: str | None
    cin: str | None
    gstins: list[str]
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
    journey: ExporterJourney
    qualification: QualificationState
    marker: ExporterMarker
    marker_reason: str | None
    industry: str | None
    export_markets: list[str] | None
    products: list[str] | None
    year_established: int | None
    #: Masked for a role that may not reveal identifiers, like CIN.
    registration_number: str | None
    #: Which registration identifies the company, or `null` when it holds neither
    #: — a question left open rather than guessed.
    identity_type: CompanyIdentityType | None
    #: Whether the company is in the sales pipeline. A buyer-only company is
    #: `NOT_IN_PIPELINE`, and its journey and gauges do not apply.
    pipeline_status: CompanyPipelineStatus
    date_added: datetime
    created_at: datetime
    updated_at: datetime
    #: GSTINs of this company another company also holds. Filled on create
    #: and edit responses; a warning, never an error.
    gstin_warnings: list[DuplicateGstinWarningResponse] = Field(default_factory=list)
    #: The marker moves the signed-in user may make now; empty for a role
    #: that may not set markers.
    allowed_marker_moves: list[MarkerMoveResponse] = Field(default_factory=list)


class ExporterProfileDetailResponse(_IdentifierMasking, BaseModel):
    customer_id: uuid.UUID
    name: str | None
    country: str | None
    cin: str | None
    gstins: list[str]
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    relationship_manager_user_id: uuid.UUID | None
    journey: ExporterJourney
    qualification: QualificationState
    marker: ExporterMarker
    marker_reason: str | None
    industry: str | None
    export_markets: list[str] | None
    products: list[str] | None
    year_established: int | None
    #: Masked for a role that may not reveal identifiers, like CIN.
    registration_number: str | None
    #: Which registration identifies the company, or `null` when it holds neither
    #: — a question left open rather than guessed.
    identity_type: CompanyIdentityType | None
    #: Whether the company is in the sales pipeline. A buyer-only company is
    #: `NOT_IN_PIPELINE`, and its journey and gauges do not apply.
    pipeline_status: CompanyPipelineStatus
    date_added: datetime
    created_at: datetime
    updated_at: datetime
    contacts: list[ExporterContactResponse]
    recent_activities: list[ExporterActivityResponse]
    gstin_warnings: list[DuplicateGstinWarningResponse]
    #: The marker moves the signed-in user may make now; empty for a role
    #: that may not set markers.
    allowed_marker_moves: list[MarkerMoveResponse] = Field(default_factory=list)

    @classmethod
    def from_detail(cls, detail) -> ExporterProfileDetailResponse:
        return cls(
            customer_id=detail.customer_id,
            name=detail.name,
            country=detail.country,
            cin=detail.cin,
            gstins=list(detail.gstins),
            pan=detail.pan,
            iec=detail.iec,
            source=detail.source,
            relationship_manager=detail.relationship_manager,
            relationship_manager_user_id=detail.relationship_manager_user_id,
            journey=detail.journey,
            qualification=detail.qualification,
            marker=detail.marker,
            marker_reason=detail.marker_reason,
            industry=detail.industry,
            export_markets=detail.export_markets,
            products=detail.products,
            year_established=detail.year_established,
            registration_number=detail.registration_number,
            identity_type=detail.identity_type,
            pipeline_status=detail.pipeline_status,
            date_added=detail.date_added,
            created_at=detail.created_at,
            updated_at=detail.updated_at,
            contacts=[ExporterContactResponse.model_validate(c) for c in detail.contacts],
            recent_activities=[
                ExporterActivityResponse.model_validate(a) for a in detail.recent_activities
            ],
            gstin_warnings=[
                DuplicateGstinWarningResponse(
                    gstin=w.gstin, other_customer_ids=list(w.other_customer_ids)
                )
                for w in detail.gstin_warnings
            ],
        )


class ExporterProfileListItemResponse(_IdentifierMasking, BaseModel):
    """One row of `GET /onboarding/exporters` — `ExporterProfileResponse`
    without the per-company collections, so a list screen never needs a
    second, per-row lookup just to show a company."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    name: str | None
    country: str | None
    cin: str | None
    gstins: list[str]
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    relationship_manager_user_id: uuid.UUID | None
    journey: ExporterJourney
    qualification: QualificationState
    marker: ExporterMarker
    marker_reason: str | None
    industry: str | None
    export_markets: list[str] | None = None
    products: list[str] | None = None
    trade_role: CompanyTradeRole | None = None
    year_established: int | None
    #: Masked for a role that may not reveal identifiers, like CIN.
    registration_number: str | None
    #: Which registration identifies the company, or `null` when it holds neither
    #: — a question left open rather than guessed.
    identity_type: CompanyIdentityType | None
    #: Whether the company is in the sales pipeline. A buyer-only company is
    #: `NOT_IN_PIPELINE`, and its journey and gauges do not apply.
    pipeline_status: CompanyPipelineStatus
    date_added: datetime
    created_at: datetime
    updated_at: datetime


class ExporterProfileSearchResponse(BaseModel):
    profiles: list[ExporterProfileListItemResponse]
    limit: int
    offset: int
