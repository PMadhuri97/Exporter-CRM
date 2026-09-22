"""Contract test for EXP-2's `VerificationAdapter` Protocol and registry.

Mirrors `test_kyb_interface.py`'s shape for `KYBAdapter`: a small dummy
adapter proves the Protocol's shape and the registry's round-trip, without
depending on `ManualEntryAdapter` (the one adapter under test elsewhere in
`app/modules/onboarding/tests/unit/test_manual_entry_adapter.py`).
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationType,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    VERIFICATION_ADAPTER_REGISTRY,
    BatchVerificationAdapter,
    VerificationAdapter,
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    VerificationRequest,
    get_adapter,
    register_adapter,
)
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum


class DummyVerificationAdapter:
    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider="dummy_contract_adapter",
            supported_verification_types=(VerificationType.KYC, VerificationType.BANK_ACCOUNT),
            supported_entity_types=(VerificationEntityType.DIRECTOR, VerificationEntityType.EXPORTER),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        return VerificationOutcome(
            provider="dummy_contract_adapter",
            provider_reference="ref-123",
            status=VerificationResultStatus.PASSED,
            normalized_result={"ok": True},
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        return VerificationOutcome(
            provider="dummy_contract_adapter",
            provider_reference=provider_reference,
            status=VerificationResultStatus.PENDING,
            normalized_result={},
        )

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=150)


def test_verification_adapter_registry():
    register_adapter("dummy_verification", DummyVerificationAdapter)
    try:
        adapter_cls = get_adapter("dummy_verification")
        assert adapter_cls is DummyVerificationAdapter

        adapter = adapter_cls()
        assert isinstance(adapter, VerificationAdapter)

        with pytest.raises(ValueError, match="not found in registry"):
            get_adapter("unknown_verification_adapter")
    finally:
        VERIFICATION_ADAPTER_REGISTRY.pop("dummy_verification", None)


def test_verification_request_and_outcome_are_validated():
    req = VerificationRequest(
        verification_type=VerificationType.KYC,
        entity_type=VerificationEntityType.DIRECTOR,
        entity_reference="ref-1",
    )
    assert req.payload == {}

    with pytest.raises(ValueError):
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference="",  # blank
        )


def test_verification_adapter_methods():
    adapter = DummyVerificationAdapter()

    cap = adapter.declare_capabilities()
    assert cap.processing_mode == KYBVendorProcessingMode.SYNCHRONOUS
    assert VerificationType.KYC in cap.supported_verification_types

    req = VerificationRequest(
        verification_type=VerificationType.KYC,
        entity_type=VerificationEntityType.DIRECTOR,
        entity_reference="ref-1",
    )
    res = adapter.verify(req)
    assert res.provider == "dummy_contract_adapter"

    status_res = adapter.get_verification_status("ref-456")
    assert status_res.provider_reference == "ref-456"
    assert status_res.status == VerificationResultStatus.PENDING

    health = adapter.get_vendor_health()
    assert health.status == VendorHealthStatusEnum.HEALTHY
    assert health.response_time_ms == 150


# ── Piece 3: BatchVerificationAdapter — a second, independent Protocol ────────


class DummyBatchOnlyAdapter:
    """A double that implements *only* `BatchVerificationAdapter`, not the
    full `VerificationAdapter` — proving the two Protocols are structurally
    independent, exactly as `workflow_dependencies.BatchVerificationAdapter`'s
    docstring claims (nothing requires an adapter to implement both)."""

    def verify_batch(self, requests: list[VerificationRequest]) -> list[VerificationOutcome]:
        return [
            VerificationOutcome(
                provider="dummy_batch_only",
                provider_reference=None,
                status=VerificationResultStatus.PASSED,
                normalized_result={},
            )
            for _ in requests
        ]


def test_batch_verification_adapter_is_a_distinct_protocol_from_verification_adapter():
    adapter = DummyBatchOnlyAdapter()
    assert isinstance(adapter, BatchVerificationAdapter)
    assert not isinstance(adapter, VerificationAdapter)


def test_dummy_contract_adapter_does_not_implement_batch_verification_adapter():
    """The boundary in the other direction: an ordinary single-check adapter
    (this file's own `DummyVerificationAdapter`) does not accidentally
    satisfy `BatchVerificationAdapter` just by existing — batch support is
    opt-in, not the default."""
    adapter = DummyVerificationAdapter()
    assert isinstance(adapter, VerificationAdapter)
    assert not isinstance(adapter, BatchVerificationAdapter)


def test_vendor_health_status_is_the_shared_kyb_contract_type():
    """VendorHealthStatus is deliberately reused verbatim from
    app.shared.contracts.kyb rather than re-declared for verification: the
    concept (status/response_time_ms/last_successful_verification_at/
    known_issues) isn't actually KYB-specific."""
    health = VendorHealthStatus(status=VendorHealthStatusEnum.DEGRADED, response_time_ms=999)
    assert health.status == VendorHealthStatusEnum.DEGRADED
