"""Unit tests for `ManualEntryAdapter` — EXP-2's one shipped `VerificationAdapter`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    VerificationAdapter,
    VerificationRequest,
)
from app.modules.onboarding.exceptions import InvalidProviderPayloadError, ProviderCapabilityError
from app.modules.onboarding.infrastructure.adapters.manual_entry_adapter import (
    PROVIDER_NAME,
    ManualEntryAdapter,
)
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum


def _request(**payload) -> VerificationRequest:
    return VerificationRequest(
        verification_type=VerificationType.KYC,
        entity_type=VerificationEntityType.DIRECTOR,
        entity_reference="33333333-3333-3333-3333-333333333333",
        payload=payload,
    )


def test_manual_entry_adapter_satisfies_the_protocol():
    assert isinstance(ManualEntryAdapter(), VerificationAdapter)


def test_declare_capabilities_covers_every_type():
    declaration = ManualEntryAdapter().declare_capabilities()
    assert declaration.provider == PROVIDER_NAME == "manual"
    assert set(declaration.supported_verification_types) == set(VerificationType)
    assert set(declaration.supported_entity_types) == set(VerificationEntityType)
    assert declaration.processing_mode is KYBVendorProcessingMode.SYNCHRONOUS


def test_verify_repackages_payload_as_outcome():
    adapter = ManualEntryAdapter()
    request = _request(
        status="PASSED",
        normalized_result={"account_holder_name": "Acme Exports"},
        provider_reference="manual-ticket-42",
        risk_level="LOW",
        valid_until=datetime(2027, 6, 1, tzinfo=UTC),
    )

    outcome = adapter.verify(request)

    assert outcome.provider == "manual"
    assert outcome.provider_reference == "manual-ticket-42"
    assert outcome.status is VerificationResultStatus.PASSED
    assert outcome.normalized_result == {"account_holder_name": "Acme Exports"}
    assert outcome.risk_level is VerificationRiskLevel.LOW
    assert outcome.valid_until == datetime(2027, 6, 1, tzinfo=UTC)


def test_verify_accepts_enum_members_directly_not_only_strings():
    adapter = ManualEntryAdapter()
    request = _request(status=VerificationResultStatus.FAILED, risk_level=VerificationRiskLevel.HIGH)

    outcome = adapter.verify(request)

    assert outcome.status is VerificationResultStatus.FAILED
    assert outcome.risk_level is VerificationRiskLevel.HIGH


def test_verify_defaults_normalized_result_and_optional_fields():
    adapter = ManualEntryAdapter()
    outcome = adapter.verify(_request(status="REVIEW"))

    assert outcome.normalized_result == {}
    assert outcome.provider_reference is None
    assert outcome.risk_level is None
    assert outcome.valid_until is None


def test_verify_requires_status():
    adapter = ManualEntryAdapter()
    with pytest.raises(InvalidProviderPayloadError, match="status"):
        adapter.verify(_request())


def test_verify_rejects_invalid_status_value():
    adapter = ManualEntryAdapter()
    with pytest.raises(InvalidProviderPayloadError, match="status"):
        adapter.verify(_request(status="NOT_A_REAL_STATUS"))


def test_verify_rejects_invalid_risk_level_value():
    adapter = ManualEntryAdapter()
    with pytest.raises(InvalidProviderPayloadError, match="risk_level"):
        adapter.verify(_request(status="PASSED", risk_level="NOT_A_REAL_RISK"))


def test_verify_rejects_non_datetime_valid_until():
    adapter = ManualEntryAdapter()
    with pytest.raises(InvalidProviderPayloadError, match="valid_until"):
        adapter.verify(_request(status="PASSED", valid_until="2027-01-01"))


def test_get_verification_status_raises_capability_error():
    """A manual entry resolves synchronously in verify(); there is nothing to
    poll for, and unlike KYB's NormalisedResult, VerificationResultStatus has
    no NOT_SUPPORTED member to return gracefully instead (see the adapter's
    docstring)."""
    adapter = ManualEntryAdapter()
    with pytest.raises(ProviderCapabilityError):
        adapter.get_verification_status("some-reference")


def test_get_vendor_health_is_always_healthy():
    health = ManualEntryAdapter().get_vendor_health()
    assert health.status is VendorHealthStatusEnum.HEALTHY
    assert health.response_time_ms == 0
