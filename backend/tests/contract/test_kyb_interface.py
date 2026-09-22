import datetime

import pytest
from pydantic import ValidationError

from app.modules.kyb.domain.ports import KYBAdapter, get_adapter, register_adapter
from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.enums.kyb import KYBVendorProcessingMode, NormalisedResult, VendorHealthStatusEnum


class DummyKYBAdapter(KYBAdapter):
    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        return KYBVendorCapabilityDeclaration(
            vendor_id="dummy",
            vendor_name="Dummy Vendor",
            supported_countries=["US", "UK"],
            supported_entity_types=["LLC", "INC"],
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify_entity(self, entity: EntityVerificationRequest) -> KYBVerificationResult:
        return KYBVerificationResult(
            vendor_id="dummy",
            vendor_reference="ref-123",
            normalised_result=NormalisedResult.VERIFIED,
            discrepancies=[],
            raw_response_reference="raw-ref",
            retrieved_at=datetime.datetime.now(),
        )

    def get_verification_status(self, vendor_reference: str) -> KYBVerificationResult:
        return KYBVerificationResult(
            vendor_id="dummy",
            vendor_reference=vendor_reference,
            normalised_result=NormalisedResult.PENDING,
            discrepancies=[],
            raw_response_reference="raw-ref",
            retrieved_at=datetime.datetime.now(),
        )

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(
            status=VendorHealthStatusEnum.HEALTHY,
            response_time_ms=150,
        )


def test_kyb_adapter_registry():
    register_adapter("dummy_kyb", DummyKYBAdapter)
    adapter_cls = get_adapter("dummy_kyb")
    assert adapter_cls is DummyKYBAdapter

    adapter = adapter_cls()
    assert isinstance(adapter, KYBAdapter)

    with pytest.raises(ValueError, match="not found in registry"):
        get_adapter("unknown_kyb")


def test_kyb_entity_verification_request():
    req = EntityVerificationRequest(
        legal_name="Acme Corp",
        registration_country="US",
        registration_number="12345",
        registered_address="123 Main St",
    )
    assert req.legal_name == "Acme Corp"
    assert req.trading_name is None
    assert req.tax_identification_number is None

    with pytest.raises(ValidationError):
        EntityVerificationRequest(legal_name="Acme Corp")  # Missing required fields


def test_kyb_verification_result():
    res = KYBVerificationResult(
        vendor_id="test",
        vendor_reference="ref",
        normalised_result=NormalisedResult.NOT_FOUND,
        discrepancies=["Address mismatch"],
        raw_response_reference="ev-1",
        retrieved_at=datetime.datetime.now(),
    )
    assert res.normalised_result == NormalisedResult.NOT_FOUND
    assert len(res.discrepancies) == 1
    assert res.verified_legal_name is None


def test_kyb_adapter_methods():
    adapter = DummyKYBAdapter()

    cap = adapter.declare_capabilities()
    assert cap.processing_mode == KYBVendorProcessingMode.SYNCHRONOUS

    req = EntityVerificationRequest(
        legal_name="Test LLC",
        registration_country="US",
        registration_number="123",
        registered_address="Test",
    )
    res = adapter.verify_entity(req)
    assert res.vendor_id == "dummy"

    status_res = adapter.get_verification_status("ref-456")
    assert status_res.vendor_reference == "ref-456"
    assert status_res.normalised_result == NormalisedResult.PENDING

    health = adapter.get_vendor_health()
    assert health.status == VendorHealthStatusEnum.HEALTHY
    assert health.response_time_ms == 150
