"""Request and response shapes for a company's addresses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from app.modules.onboarding.domain.entities.exporter_enums import CompanyAddressType

_Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
_Optional120 = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)]
_Postal = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20)]


def _country(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    if len(cleaned) != 2 or not cleaned.isascii() or not cleaned.isalpha():
        raise ValueError("country must be a two-letter ISO 3166-1 code, e.g. IN")
    return cleaned


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class AddCompanyAddressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address_type: CompanyAddressType
    line1: _Line
    line2: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=255)] = None
    city: _City
    state: _Optional120 = None
    postal_code: _Postal = None
    country: str = Field(description="ISO 3166-1 alpha-2, e.g. IN")
    #: Make it its type's default. The first active address of a type is its default
    #: whatever this says.
    is_default: bool = False
    #: Link the new address to this GST registration of the same company.
    gst_registration_id: uuid.UUID | None = None

    @field_validator("country")
    @classmethod
    def _clean_country(cls, value: str | None) -> str | None:
        return _country(value)

    @field_validator("line2", "state", "postal_code", mode="before")
    @classmethod
    def _blanks(cls, value: object) -> object:
        return _blank_to_none(value)


class UpdateCompanyAddressRequest(BaseModel):
    """A partial edit: only the fields sent change. ``line1``, ``city``, ``country`` and
    ``address_type`` may change but not be cleared."""

    model_config = ConfigDict(extra="forbid")

    address_type: CompanyAddressType | None = None
    line1: _Line | None = None
    line2: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=255)] = None
    city: _City | None = None
    state: _Optional120 = None
    postal_code: _Postal = None
    country: str | None = None

    @field_validator("address_type", "line1", "city", "country", mode="before")
    @classmethod
    def _not_null(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be cleared")
        return value

    @field_validator("country")
    @classmethod
    def _clean_country(cls, value: str | None) -> str | None:
        return _country(value)

    @field_validator("line2", "state", "postal_code", mode="before")
    @classmethod
    def _blanks(cls, value: object) -> object:
        return _blank_to_none(value)

    def changes(self) -> dict[str, object]:
        return {
            name: (value.value if isinstance(value, CompanyAddressType) else value)
            for name in self.model_fields_set
            for value in [getattr(self, name)]
        }


class DeactivateCompanyAddressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class CompanyAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    address_type: CompanyAddressType
    line1: str
    line2: str | None
    city: str
    state: str | None
    postal_code: str | None
    country: str
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CompanyAddressListResponse(BaseModel):
    addresses: list[CompanyAddressResponse]
    #: When the company's background check was last cleared, if ever.
    last_clear_at: datetime | None
    #: The default registered address was added or changed after that Clear.
    registered_changed_since_clear: bool
