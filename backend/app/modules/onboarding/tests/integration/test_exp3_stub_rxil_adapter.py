"""Integration tests for Exporter CRM Piece 3: `StubRxilAdapter` and
`VerificationService.trigger_verification_batch`.

Follows `test_exp2_verification_service.py`'s conventions: real Postgres, no
per-test rollback, each test mints its own fresh ids.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.workflow_dependencies import (
    VERIFICATION_ADAPTER_REGISTRY,
    BatchVerificationAdapter,
    VerificationRequest,
    get_adapter,
)
from app.modules.onboarding.exceptions import (
    InvalidProviderPayloadError,
    ProviderCapabilityError,
)
from app.modules.onboarding.infrastructure.adapters.stub_rxil_adapter import (
    PROVIDER_NAME,
    REGISTRY_KEY,
    StubRxilAdapter,
)
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


def _actor() -> str:
    return f"officer-{uuid.uuid4().hex[:8]}"


# ── Registry / Protocol shape ──────────────────────────────────────────────────


async def test_stub_rxil_adapter_is_registered_under_rxil_key():
    # No I/O here — `async def` only to match this module's `pytestmark =
    # pytest.mark.asyncio` (applied file-wide, matching every other test in
    # this suite), not because this test itself awaits anything.
    assert REGISTRY_KEY in VERIFICATION_ADAPTER_REGISTRY
    assert get_adapter(REGISTRY_KEY) is StubRxilAdapter


async def test_stub_rxil_adapter_satisfies_both_protocols():
    from app.modules.onboarding.domain.workflow_dependencies import VerificationAdapter

    adapter = StubRxilAdapter()
    assert isinstance(adapter, VerificationAdapter)
    assert isinstance(adapter, BatchVerificationAdapter)


# ── The central acceptance criterion: one payload, many results ──────────────


async def test_batch_of_three_check_types_produces_three_results_tagged_rxil():
    """The exact scenario the ticket names: one batch payload with KYB + AML
    + INVOICE_DUPLICATION produces exactly 3 VerificationResult rows, each
    with provider='RXIL' faithfully recorded."""
    exporter_id = uuid.uuid4()
    invoice_id = uuid.uuid4()

    requests = [
        VerificationRequest(
            verification_type=VerificationType.KYB,
            entity_type=VerificationEntityType.EXPORTER,
            entity_reference=str(exporter_id),
            payload={"status": "PASSED", "normalized_result": {"check": "kyb"}},
        ),
        VerificationRequest(
            verification_type=VerificationType.AML,
            entity_type=VerificationEntityType.EXPORTER,
            entity_reference=str(exporter_id),
            payload={"status": "PASSED", "normalized_result": {"check": "aml"}},
        ),
        VerificationRequest(
            verification_type=VerificationType.INVOICE_DUPLICATION,
            entity_type=VerificationEntityType.INVOICE,
            entity_reference=str(invoice_id),
            payload={"status": "FAILED", "normalized_result": {"check": "invoice_dup"}},
        ),
    ]

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        results = await svc.trigger_verification_batch(
            requests, provider=REGISTRY_KEY, actor_id=_actor()
        )

    assert len(results) == 3
    assert all(r.provider == PROVIDER_NAME for r in results)
    assert all(r.provider != REGISTRY_KEY for r in results)
    assert all(r.provider != "Internal" for r in results)

    by_type = {r.verification_type: r for r in results}
    assert by_type[VerificationType.KYB].status is VerificationResultStatus.PASSED
    assert by_type[VerificationType.AML].status is VerificationResultStatus.PASSED
    assert by_type[VerificationType.INVOICE_DUPLICATION].status is VerificationResultStatus.FAILED
    assert by_type[VerificationType.KYB].entity_reference == exporter_id
    assert by_type[VerificationType.INVOICE_DUPLICATION].entity_reference == invoice_id

    # Persisted, not just returned in-memory.
    async with db_services.AsyncSessionLocal() as db:
        for result in results:
            fetched = await db.get(VerificationResult, result.id)
            assert fetched is not None
            assert fetched.provider == PROVIDER_NAME


async def test_batch_provider_is_never_rewritten_in_the_read_path():
    """Extends EXP-2's single-result provider-fidelity guarantee to the batch
    case: a result recorded with provider="RXIL" is never observable as the
    registry key ("rxil") or anything else, anywhere in the read path."""
    entity_id = uuid.uuid4()
    requests = [
        VerificationRequest(
            verification_type=VerificationType.BUYER,
            entity_type=VerificationEntityType.BUYER,
            entity_reference=str(entity_id),
            payload={"status": "PASSED"},
        )
    ]

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        await svc.trigger_verification_batch(
            requests, provider=REGISTRY_KEY, actor_id=_actor()
        )

    async with db_services.AsyncSessionLocal() as db:
        svc2 = VerificationService(db)
        listed = await svc2.list_verification_results(VerificationEntityType.BUYER, entity_id)

    assert listed[0].provider == "RXIL"
    assert listed[0].provider != REGISTRY_KEY
    assert listed[0].provider != "Internal"


# ── Capability boundary: batch is opt-in ──────────────────────────────────────


async def test_trigger_verification_batch_rejects_provider_without_batch_support():
    """`manual` (ManualEntryAdapter) never implements BatchVerificationAdapter
    — the registry lookup succeeds, but the capability check fails cleanly
    rather than silently looping single .verify() calls."""
    requests = [
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference=str(uuid.uuid4()),
            payload={"status": "PASSED"},
        )
    ]
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(ProviderCapabilityError):
            await svc.trigger_verification_batch(
                requests, provider="manual", actor_id=_actor()
            )


async def test_trigger_verification_batch_rejects_empty_batch():
    from app.shared.exceptions import ValidationError

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(ValidationError):
            await svc.trigger_verification_batch([], provider=REGISTRY_KEY, actor_id=_actor())


async def test_rxil_batch_check_missing_status_raises_before_persisting():
    """Same validation ManualEntryAdapter applies — a malformed item in the
    batch is rejected before anything is written, not partially persisted."""
    requests = [
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference=str(uuid.uuid4()),
            payload={"status": "PASSED"},
        ),
        VerificationRequest(
            verification_type=VerificationType.AML,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference=str(uuid.uuid4()),
            payload={},  # no 'status'
        ),
    ]
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(InvalidProviderPayloadError):
            await svc.trigger_verification_batch(
                requests, provider=REGISTRY_KEY, actor_id=_actor()
            )


# ── Single-check path (StubRxilAdapter also satisfies VerificationAdapter) ───


async def test_stub_rxil_adapter_single_check_via_trigger_verification():
    entity_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        result = await svc.trigger_verification(
            VerificationType.GST,
            VerificationEntityType.EXPORTER,
            entity_id,
            provider=REGISTRY_KEY,
            payload={"status": "PASSED", "normalized_result": {"gstin_valid": True}},
            actor_id=_actor(),
        )

    assert result.provider == PROVIDER_NAME
    assert result.status is VerificationResultStatus.PASSED
    assert result.normalized_result == {"gstin_valid": True}
