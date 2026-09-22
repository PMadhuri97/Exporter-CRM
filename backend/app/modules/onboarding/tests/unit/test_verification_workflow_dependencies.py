"""Unit tests for EXP-2's `VerificationAdapter` Protocol, its dataclasses, and
the generalized registry in `workflow_dependencies.py`.

Deliberately does not import `ManualEntryAdapter` here — these tests exercise
the Protocol/registry machinery itself against small local doubles, so a
regression in `ManualEntryAdapter` never masks (or is masked by) a regression
in the registry it's registered into.
"""

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
    VERIFICATION_ADAPTER_REGISTRY,
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    VerificationRequest,
    get_adapter,
    register_adapter,
)
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum


class _DummyAdapter:
    """A minimal, structurally-conforming `VerificationAdapter` double."""

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider="dummy",
            supported_verification_types=(VerificationType.KYC,),
            supported_entity_types=(VerificationEntityType.DIRECTOR,),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        return VerificationOutcome(
            provider="dummy",
            provider_reference="dummy-ref",
            status=VerificationResultStatus.PASSED,
            normalized_result={"ok": True},
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        return VerificationOutcome(
            provider="dummy",
            provider_reference=provider_reference,
            status=VerificationResultStatus.PASSED,
            normalized_result={"ok": True},
        )

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=5)


# ── VerificationRequest ───────────────────────────────────────────────────────


def test_verification_request_accepts_valid_construction():
    req = VerificationRequest(
        verification_type=VerificationType.KYC,
        entity_type=VerificationEntityType.DIRECTOR,
        entity_reference="11111111-1111-1111-1111-111111111111",
        payload={"first_name": "Jane"},
    )
    assert req.verification_type is VerificationType.KYC
    assert req.entity_type is VerificationEntityType.DIRECTOR
    assert req.payload == {"first_name": "Jane"}


def test_verification_request_defaults_payload_to_empty_dict():
    req = VerificationRequest(
        verification_type=VerificationType.BANK_ACCOUNT,
        entity_type=VerificationEntityType.EXPORTER,
        entity_reference="22222222-2222-2222-2222-222222222222",
    )
    assert req.payload == {}


def test_verification_request_rejects_blank_entity_reference():
    with pytest.raises(ValueError, match="entity_reference"):
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference="   ",
        )


def test_verification_request_rejects_non_enum_verification_type():
    with pytest.raises(ValueError, match="verification_type"):
        VerificationRequest(
            verification_type="KYC",  # a plain string is not a VerificationType
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference="ref",
        )


def test_verification_request_rejects_non_enum_entity_type():
    with pytest.raises(ValueError, match="entity_type"):
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type="DIRECTOR",  # a plain string is not a VerificationEntityType
            entity_reference="ref",
        )


# ── VerificationOutcome ───────────────────────────────────────────────────────


def test_verification_outcome_accepts_valid_construction():
    outcome = VerificationOutcome(
        provider="RXIL",
        provider_reference="rxil-123",
        status=VerificationResultStatus.PASSED,
        normalized_result={"score": 10},
        risk_level=VerificationRiskLevel.LOW,
        valid_until=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert outcome.provider == "RXIL"
    assert outcome.risk_level is VerificationRiskLevel.LOW


def test_verification_outcome_rejects_blank_provider():
    with pytest.raises(ValueError, match="provider"):
        VerificationOutcome(
            provider="   ",
            provider_reference=None,
            status=VerificationResultStatus.PASSED,
            normalized_result={},
        )


def test_verification_outcome_rejects_non_enum_status():
    with pytest.raises(ValueError, match="status"):
        VerificationOutcome(
            provider="manual",
            provider_reference=None,
            status="PASSED",  # a plain string is not a VerificationResultStatus
            normalized_result={},
        )


def test_verification_outcome_rejects_non_enum_risk_level():
    with pytest.raises(ValueError, match="risk_level"):
        VerificationOutcome(
            provider="manual",
            provider_reference=None,
            status=VerificationResultStatus.PASSED,
            normalized_result={},
            risk_level="LOW",  # a plain string is not a VerificationRiskLevel
        )


# ── VerificationCapabilityDeclaration ────────────────────────────────────────


def test_capability_declaration_rejects_empty_verification_types():
    with pytest.raises(ValueError, match="supported_verification_types"):
        VerificationCapabilityDeclaration(
            provider="dummy",
            supported_verification_types=(),
            supported_entity_types=(VerificationEntityType.DIRECTOR,),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )


def test_capability_declaration_rejects_empty_entity_types():
    with pytest.raises(ValueError, match="supported_entity_types"):
        VerificationCapabilityDeclaration(
            provider="dummy",
            supported_verification_types=(VerificationType.KYC,),
            supported_entity_types=(),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_register_and_get_round_trip():
    register_adapter("dummy_verification_adapter", _DummyAdapter)
    try:
        adapter_cls = get_adapter("dummy_verification_adapter")
        assert adapter_cls is _DummyAdapter

        adapter = adapter_cls()
        assert isinstance(adapter, _DummyAdapter)
        # Structural conformance to the Protocol — no explicit subclassing needed.
        from app.modules.onboarding.domain.workflow_dependencies import VerificationAdapter

        assert isinstance(adapter, VerificationAdapter)
    finally:
        VERIFICATION_ADAPTER_REGISTRY.pop("dummy_verification_adapter", None)


def test_get_adapter_raises_for_unknown_unqualified_name():
    with pytest.raises(ValueError, match="not found in registry"):
        get_adapter("no_such_verification_adapter")


def test_get_adapter_resolves_fully_qualified_class_path_when_unregistered():
    """The registry falls back to importing a dotted class path — the same
    escape hatch `kyb.domain.ports.get_adapter` provides."""
    assert "tests.unit.test_verification_workflow_dependencies._DummyAdapter" not in (
        VERIFICATION_ADAPTER_REGISTRY
    )
    resolved = get_adapter(
        "app.modules.onboarding.tests.unit.test_verification_workflow_dependencies._DummyAdapter"
    )
    assert resolved is _DummyAdapter
