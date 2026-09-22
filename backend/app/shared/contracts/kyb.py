from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.shared.enums.kyb import KYBVendorProcessingMode, NormalisedResult, VendorHealthStatusEnum


class KYBVendorCapabilityDeclaration(BaseModel):
    """The capability declaration of a KYB vendor adapter."""

    model_config = ConfigDict(from_attributes=True)

    vendor_id: str
    vendor_name: str
    supported_countries: list[str]
    supported_entity_types: list[str]
    processing_mode: KYBVendorProcessingMode


class EntityVerificationRequest(BaseModel):
    """Request structure for verifying a business entity."""

    model_config = ConfigDict(from_attributes=True)

    legal_name: str
    trading_name: str | None = None
    registration_country: str
    registration_number: str
    registered_address: str
    tax_identification_number: str | None = None


class KYBVerificationResult(BaseModel):
    """Result structure returned by the KYB vendor adapter."""

    model_config = ConfigDict(from_attributes=True)

    vendor_id: str
    vendor_reference: str
    normalised_result: NormalisedResult
    verified_legal_name: str | None = None
    verified_registration_number: str | None = None
    verified_address: str | None = None
    discrepancies: list[str]
    raw_response_reference: str
    retrieved_at: datetime


class VendorHealthStatus(BaseModel):
    """Structured health status returned by the KYB vendor adapter."""

    model_config = ConfigDict(from_attributes=True)

    status: VendorHealthStatusEnum
    response_time_ms: int
    last_successful_verification_at: datetime | None = None
    known_issues: str | None = None
