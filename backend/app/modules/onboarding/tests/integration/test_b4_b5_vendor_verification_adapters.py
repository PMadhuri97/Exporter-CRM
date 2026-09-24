"""B4/B5 — the two vendor-integration adapters, and the routing that reaches them.

Middesk, Trulioo and Sumsub were all fully built and called by nothing. These
tests cover the wrappers that give them a caller:

  • each adapter satisfies the `VerificationAdapter` Protocol;
  • country routing picks the right vendor, and an uncovered country returns a
    manual-review indicator rather than a vendor call;
  • absent credentials fail loudly — never as a pass;
  • a vendor result normalises into `verification_result` with the vendor that
    actually answered recorded as `provider`.

The vendors themselves are never contacted. Every test either stops before the
network call (credentials absent is the *default* state of this suite, which is
the point) or substitutes a fake `KYBAdapter` through
`_VENDOR_LOADERS`/`monkeypatch`. Nothing under `app/modules/kyb/` is imported
directly here either — the same `kyb-internals-are-private` contract the adapter
observes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.modules.onboarding.application.kyb_vendor_registry_service import (
    KybVendorRegistryService,
)
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    VerificationAdapter,
    VerificationRequest,
    get_adapter,
)
from app.modules.onboarding.exceptions import (
    InvalidProviderPayloadError,
    ProviderCapabilityError,
    ProviderNotEnabledError,
)
from app.modules.onboarding.infrastructure.adapters import kyb_verification_adapter as kyb_mod
from app.modules.onboarding.infrastructure.adapters import (
    sumsub_verification_adapter as sumsub_mod,
)
from app.modules.onboarding.infrastructure.adapters.kyb_verification_adapter import (
    REGISTRY_KEY,
    KybVerificationAdapter,
    known_vendor_declarations,
    resolve_vendor_id,
)
from app.modules.onboarding.infrastructure.adapters.sumsub_verification_adapter import (
    PROVIDER_NAME as SUMSUB_PROVIDER,
)
from app.modules.onboarding.infrastructure.adapters.sumsub_verification_adapter import (
    SumsubVerificationAdapter,
)
from app.modules.onboarding.infrastructure.kyb_vendor_seed_loader import (
    load_kyb_vendor_registry,
)
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.contracts.kyb import (
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.enums.kyb import (
    KYBVendorProcessingMode,
    NormalisedResult,
    VendorHealthStatusEnum,
)

pytestmark = pytest.mark.asyncio

#: The real vendor ids this file registers into the shared KYB registry.
_REAL_VENDOR_IDS = ("middesk", "trulioo")


async def _clear_real_vendor_registrations() -> None:
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM onboarding.kyb_vendor_registration WHERE vendor_id = ANY(:ids)"),
            {"ids": list(_REAL_VENDOR_IDS)},
        )
        await db.commit()


@pytest.fixture(autouse=True)
async def _isolate_real_vendor_registry():
    """Register the real vendors only for the duration of a test in this file.

    Two tests here seed Middesk and Trulioo for real, and the registry table is
    shared across the whole session. Left behind, those rows change the answers
    other suites get: `test_s1t4_kyb_vendor_registry` asserts that an
    unsupported country returns manual review and that its own fakes are the
    only candidates, and its `_wipe` only removes rows with its own prefix — so
    real vendors survive it and silently break eight of its tests.

    Mirrors that file's own isolation fixture, wiping before as well as after so
    a previous crashed run cannot poison this one either.
    """
    await _clear_real_vendor_registrations()
    yield
    await _clear_real_vendor_registrations()

_KYB_ADAPTER_PATH = (
    "app.modules.onboarding.infrastructure.adapters."
    "kyb_verification_adapter.KybVerificationAdapter"
)
_SUMSUB_ADAPTER_PATH = (
    "app.modules.onboarding.infrastructure.adapters."
    "sumsub_verification_adapter.SumsubVerificationAdapter"
)


def _entity_payload(country: str, **extra: object) -> dict:
    return {
        "legal_name": "Acme Exports Pvt Ltd",
        "registration_country": country,
        "registration_number": "U74999KA2020PTC000000",
        "registered_address": "1 Industrial Estate, Bengaluru",
        **extra,
    }


class _FakeKybVendor:
    """A `KYBAdapter`-shaped stand-in. Structural, so no kyb import is needed.

    `declare_capabilities` is real, not a stub: routing reads the declarations
    of *every* registered loader, so a fake substituted for one vendor is asked
    to declare alongside the others. It mirrors the vendor it stands in for so
    that substituting it does not change which country routes where.
    """

    vendor_id = "middesk"
    country = "US"
    normalised = NormalisedResult.VERIFIED
    discrepancies: list[str] = []

    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        return KYBVendorCapabilityDeclaration(
            vendor_id=self.vendor_id,
            vendor_name=f"Fake {self.vendor_id}",
            supported_countries=[self.country],
            supported_entity_types=["corporation"],
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify_entity(self, entity) -> KYBVerificationResult:
        return KYBVerificationResult(
            vendor_id=self.vendor_id,
            vendor_reference="vendor-ref-9001",
            normalised_result=self.normalised,
            verified_legal_name=entity.legal_name,
            verified_registration_number=entity.registration_number,
            verified_address=entity.registered_address,
            discrepancies=list(self.discrepancies),
            raw_response_reference="s3://vendor-raw/9001.json",
            retrieved_at=datetime.now(UTC),
        )

    def get_verification_status(self, vendor_reference):  # pragma: no cover
        raise NotImplementedError

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=1)


# ── Protocol conformance ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "adapter",
    [KybVerificationAdapter(), SumsubVerificationAdapter()],
    ids=["kyb", "sumsub"],
)
async def test_adapter_satisfies_the_verification_adapter_protocol(adapter):
    assert isinstance(adapter, VerificationAdapter)
    for method in ("declare_capabilities", "verify", "get_verification_status", "get_vendor_health"):
        assert callable(getattr(adapter, method))


@pytest.mark.parametrize(
    ("path", "expected"),
    [(_KYB_ADAPTER_PATH, KybVerificationAdapter), (_SUMSUB_ADAPTER_PATH, SumsubVerificationAdapter)],
    ids=["kyb", "sumsub"],
)
async def test_adapter_resolves_by_dotted_path_through_the_allowlist(path, expected):
    """The adapters package does not import these modules (another lane owns
    that file), so the dotted path is how they are reached today. It works
    because their package is already in `ADAPTER_MODULE_ALLOWLIST`."""
    assert get_adapter(path) is expected


async def test_resolving_by_dotted_path_also_registers_the_short_name():
    """Importing the module runs its `register_adapter` call, so the short name
    works from then on — which is why no edit to `adapters/__init__.py` is
    required for these to be usable."""
    get_adapter(_KYB_ADAPTER_PATH)
    assert get_adapter(REGISTRY_KEY) is KybVerificationAdapter
    get_adapter(_SUMSUB_ADAPTER_PATH)
    assert get_adapter(SUMSUB_PROVIDER) is SumsubVerificationAdapter


async def test_declared_capabilities_are_honest_about_being_asynchronous():
    """Middesk answers by webhook and Sumsub answers by webhook. A caller told
    SYNCHRONOUS would treat `verify()` as final, which for both is untrue."""
    for adapter in (KybVerificationAdapter(), SumsubVerificationAdapter()):
        assert (
            adapter.declare_capabilities().processing_mode
            is KYBVendorProcessingMode.ASYNCHRONOUS
        )


# ── Country routing ──────────────────────────────────────────────────────────

async def test_vendor_declarations_cover_us_and_india():
    declarations = known_vendor_declarations()
    assert "US" in declarations["middesk"].supported_countries
    assert "IN" in declarations["trulioo"].supported_countries


@pytest.mark.parametrize(
    ("country", "expected_vendor"),
    [("US", "middesk"), ("IN", "trulioo"), ("GB", "trulioo")],
)
async def test_country_routes_to_the_right_vendor(monkeypatch, country, expected_vendor):
    """Routing is proved by *which vendor* the credential check refuses for.

    Neither vendor has credentials in this suite, so `verify()` stops at
    `_require_credentials`. The vendor named in that error is the vendor
    routing chose — a stronger assertion than calling the private resolver,
    because it goes through `verify()`'s real path.
    """
    adapter = KybVerificationAdapter()
    request = VerificationRequest(
        verification_type=VerificationType.KYB,
        entity_type=VerificationEntityType.EXPORTER,
        entity_reference=str(uuid.uuid4()),
        payload=_entity_payload(country),
    )
    with pytest.raises(ProviderNotEnabledError) as excinfo:
        adapter.verify(request)
    assert excinfo.value.provider_name == expected_vendor


async def test_an_uncovered_country_returns_manual_review_not_a_failure():
    """The registry's manual_review indicator, in this Protocol's vocabulary.

    REVIEW, not FAILED: nothing about the entity was disproved. And emphatically
    not PASSED.
    """
    outcome = KybVerificationAdapter().verify(
        VerificationRequest(
            verification_type=VerificationType.KYB,
            entity_type=VerificationEntityType.EXPORTER,
            entity_reference=str(uuid.uuid4()),
            payload=_entity_payload("ZZ"),
        )
    )
    assert outcome.status is VerificationResultStatus.REVIEW
    assert outcome.normalized_result["routing"] == "manual_review"
    assert outcome.provider == REGISTRY_KEY


async def test_routing_reads_the_kyb_entity_vocabulary_not_the_subject_one():
    """`VerificationEntityType.EXPORTER` and Middesk's `"corporation"` are
    different axes. Routing on the former matches no declared type and sends
    every country to manual review — a units error that looks like a coverage
    gap. This pins the distinction.
    """
    assert kyb_mod._resolve_from_declarations("US", "corporation") == "middesk"
    assert kyb_mod._resolve_from_declarations("US", "EXPORTER") is None
    # …and verify() must therefore not pass the subject type through.
    with pytest.raises(ProviderNotEnabledError) as excinfo:
        KybVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYB,
                entity_type=VerificationEntityType.EXPORTER,
                entity_reference=str(uuid.uuid4()),
                payload=_entity_payload("US"),
            )
        )
    assert excinfo.value.provider_name == "middesk"


async def test_an_explicit_vendor_from_the_registry_overrides_declaration_routing():
    """`payload["kyb_vendor_id"]` is the health-aware answer an async caller
    resolved; it must win over the in-process fallback."""
    with pytest.raises(ProviderNotEnabledError) as excinfo:
        KybVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYB,
                entity_type=VerificationEntityType.EXPORTER,
                entity_reference=str(uuid.uuid4()),
                # US would route to middesk; the caller says trulioo.
                payload=_entity_payload("US", kyb_vendor_id="trulioo"),
            )
        )
    assert excinfo.value.provider_name == "trulioo"


# ── The registry itself (seeded from the same declarations) ──────────────────

async def test_the_seed_loader_registers_both_vendors_and_routing_resolves():
    """The loader was a no-op with `KNOWN_KYB_ADAPTERS = ()`, so the registry
    was empty and every country resolved to manual review. Registering the real
    declarations is what makes `get_vendor_for_country` answer."""
    async with db_services.AsyncSessionLocal() as db:
        registered = await load_kyb_vendor_registry(db)
        assert {r.vendor_id for r in registered} >= {"middesk", "trulioo"}

        service = KybVendorRegistryService(db)
        us = await service.get_vendor_for_country("US", "corporation")
        india = await service.get_vendor_for_country("IN", "CORPORATION")
        nowhere = await service.get_vendor_for_country("ZZ", "corporation")

    assert us.vendor is not None and us.vendor.vendor_id == "middesk"
    assert india.vendor is not None and india.vendor.vendor_id == "trulioo"
    assert nowhere.vendor is None, "an unsupported country must be manual review"


async def test_resolve_vendor_id_helper_matches_the_registry():
    """The async helper an async caller uses to fill `payload["kyb_vendor_id"]`."""
    async with db_services.AsyncSessionLocal() as db:
        await load_kyb_vendor_registry(db)
        assert (
            await resolve_vendor_id(db, registration_country="US", entity_type="corporation")
            == "middesk"
        )
        assert (
            await resolve_vendor_id(db, registration_country="IN", entity_type="CORPORATION")
            == "trulioo"
        )
        assert (
            await resolve_vendor_id(db, registration_country="ZZ", entity_type="corporation")
            is None
        )


# ── Credentials fail loudly ──────────────────────────────────────────────────

@pytest.mark.parametrize("country,vendor", [("US", "middesk"), ("IN", "trulioo")])
async def test_absent_credentials_raise_and_never_pass(country, vendor):
    """The single worst outcome available here is a missing credential reading
    as a verified entity. This asserts the failure, and asserts it is a 422
    configuration error rather than a 502 that would read as a vendor outage."""
    with pytest.raises(ProviderNotEnabledError) as excinfo:
        KybVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYB,
                entity_type=VerificationEntityType.EXPORTER,
                entity_reference=str(uuid.uuid4()),
                payload=_entity_payload(country),
            )
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.provider_name == vendor


async def test_an_enabled_vendor_with_a_blank_key_still_refuses(monkeypatch):
    """`TRULIOO_ENABLED=true` with an empty key is the dangerous middle state:
    the client would send `x-trulioo-api-key: ` and fail at the vendor as a 401.
    Caught here instead."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TRULIOO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TRULIOO_API_KEY", "   ", raising=False)
    with pytest.raises(ProviderNotEnabledError):
        KybVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYB,
                entity_type=VerificationEntityType.EXPORTER,
                entity_reference=str(uuid.uuid4()),
                payload=_entity_payload("IN"),
            )
        )


async def test_middesk_accepts_either_vault_or_an_env_key(monkeypatch):
    """Middesk reads its key from Vault, falling back to `MIDDESK_API_KEY`.
    Either satisfies the precheck; neither is a hard stop."""
    settings = get_settings()
    monkeypatch.setattr(settings, "MIDDESK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MIDDESK_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "VAULT_ADDR", "", raising=False)
    monkeypatch.setattr(settings, "VAULT_TOKEN", "", raising=False)
    with pytest.raises(ProviderNotEnabledError):
        kyb_mod._require_credentials("middesk")

    monkeypatch.setattr(settings, "MIDDESK_API_KEY", "mk-live-123", raising=False)
    kyb_mod._require_credentials("middesk")  # must not raise

    monkeypatch.setattr(settings, "MIDDESK_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "VAULT_ADDR", "https://vault.internal", raising=False)
    monkeypatch.setattr(settings, "VAULT_TOKEN", "s.token", raising=False)
    kyb_mod._require_credentials("middesk")  # must not raise


async def test_sumsub_refuses_while_the_flag_is_off():
    """`SUMSUB_ENABLED` defaults false. It is honoured, not bypassed, and there
    is no fallback to the mock — a mock answer in `verification_result` would be
    a fabricated KYC record."""
    assert get_settings().SUMSUB_ENABLED is False
    with pytest.raises(ProviderNotEnabledError) as excinfo:
        SumsubVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYC,
                entity_type=VerificationEntityType.DIRECTOR,
                entity_reference=str(uuid.uuid4()),
                payload={"applicant_id": "sumsub-applicant-1"},
            )
        )
    assert excinfo.value.status_code == 422


async def test_sumsub_reports_down_when_unconfigured():
    health = SumsubVerificationAdapter().get_vendor_health()
    assert health.status is VendorHealthStatusEnum.DOWN
    assert "SUMSUB_ENABLED" in (health.known_issues or "")


# ── Normalisation into verification_result ───────────────────────────────────

async def test_a_vendor_result_lands_in_verification_result_with_the_real_vendor(monkeypatch):
    """The acceptance test for provenance: one registry entry (`"kyb"`) fronts
    two vendors, and the row must record the vendor that answered — not `"kyb"`,
    which would make Middesk and Trulioo indistinguishable on a compliance
    record.
    """
    fake = _FakeKybVendor()
    fake.vendor_id = "trulioo"
    fake.country = "IN"
    monkeypatch.setitem(kyb_mod._VENDOR_LOADERS, "trulioo", lambda: (lambda: fake))
    monkeypatch.setattr(kyb_mod, "_require_credentials", lambda vendor_id: None)

    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        result = await VerificationService(db).trigger_verification(
            VerificationType.KYB,
            VerificationEntityType.EXPORTER,
            customer_id,
            provider=REGISTRY_KEY,
            payload=_entity_payload("IN"),
            actor_id="tester",
        )
        result_id = result.id

    assert result.provider == "trulioo", "provenance must survive the wrapper"
    assert result.status is VerificationResultStatus.PASSED
    assert result.provider_reference == "vendor-ref-9001"
    assert result.normalized_result["normalised_result"] == "VERIFIED"
    assert result.normalized_result["raw_response_reference"] == "s3://vendor-raw/9001.json"

    # It is one row in the table the CRM already reads — not a second store.
    async with db_services.AsyncSessionLocal() as db:
        listed = await VerificationService(db).list_verification_results(
            VerificationEntityType.EXPORTER, customer_id
        )
    assert [r.id for r in listed] == [result_id]
    assert listed[0].provider == "trulioo"


@pytest.mark.parametrize(
    ("normalised", "expected_status"),
    [
        (NormalisedResult.VERIFIED, VerificationResultStatus.PASSED),
        (NormalisedResult.REJECTED, VerificationResultStatus.FAILED),
        (NormalisedResult.PENDING, VerificationResultStatus.PENDING),
        (NormalisedResult.NOT_FOUND, VerificationResultStatus.REVIEW),
        (NormalisedResult.REQUIRES_MANUAL_REVIEW, VerificationResultStatus.REVIEW),
        (NormalisedResult.NOT_SUPPORTED, VerificationResultStatus.REVIEW),
    ],
)
async def test_every_vendor_answer_maps_to_a_status(monkeypatch, normalised, expected_status):
    """Exhaustive over `NormalisedResult`. Nothing a vendor can say falls
    through to a default, and only VERIFIED becomes PASSED."""
    fake = _FakeKybVendor()
    fake.normalised = normalised
    monkeypatch.setitem(kyb_mod._VENDOR_LOADERS, "middesk", lambda: (lambda: fake))
    monkeypatch.setattr(kyb_mod, "_require_credentials", lambda vendor_id: None)

    outcome = KybVerificationAdapter().verify(
        VerificationRequest(
            verification_type=VerificationType.KYB,
            entity_type=VerificationEntityType.EXPORTER,
            entity_reference=str(uuid.uuid4()),
            payload=_entity_payload("US"),
        )
    )
    assert outcome.status is expected_status
    assert outcome.provider == "middesk"


async def test_discrepancies_drive_the_risk_band(monkeypatch):
    fake = _FakeKybVendor()
    monkeypatch.setitem(kyb_mod._VENDOR_LOADERS, "middesk", lambda: (lambda: fake))
    monkeypatch.setattr(kyb_mod, "_require_credentials", lambda vendor_id: None)
    adapter = KybVerificationAdapter()

    def run():
        return adapter.verify(
            VerificationRequest(
                verification_type=VerificationType.KYB,
                entity_type=VerificationEntityType.EXPORTER,
                entity_reference=str(uuid.uuid4()),
                payload=_entity_payload("US"),
            )
        )

    fake.discrepancies = []
    assert run().risk_level is None, "a clean KYB answer bands no risk"

    fake.discrepancies = ["address mismatch"]
    assert run().risk_level is VerificationRiskLevel.MEDIUM

    fake.discrepancies = ["a", "b", "c", "d"]
    assert run().risk_level is VerificationRiskLevel.HIGH


async def test_a_payload_that_cannot_describe_an_entity_is_rejected():
    with pytest.raises(InvalidProviderPayloadError) as excinfo:
        KybVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYB,
                entity_type=VerificationEntityType.EXPORTER,
                entity_reference=str(uuid.uuid4()),
                payload={"registration_country": "US"},  # no legal_name etc.
            )
        )
    assert excinfo.value.status_code == 422
    assert "legal_name" in excinfo.value.detail


# ── Sumsub webhook translation ───────────────────────────────────────────────

@pytest.mark.parametrize(
    ("review_answer", "expected_status"),
    [
        ("GREEN", VerificationResultStatus.PASSED),
        ("RED", VerificationResultStatus.FAILED),
        ("", VerificationResultStatus.REVIEW),
        (None, VerificationResultStatus.REVIEW),
        ("SOMETHING_NEW", VerificationResultStatus.REVIEW),
    ],
)
async def test_a_sumsub_webhook_becomes_a_verification_outcome(
    monkeypatch, review_answer, expected_status
):
    """The translation half of getting Sumsub answers into `verification_result`.

    Note what is *not* here: no unrecognised answer becomes PASSED.
    """
    monkeypatch.setattr(sumsub_mod, "_require_enabled", lambda: None)

    class _Provider:
        def parse_webhook(self, payload):
            from app.shared.contracts.identity import WebhookParseResult

            return WebhookParseResult(
                event_type="applicantReviewed",
                applicant_id="app-77",
                external_user_id="cust-9",
                review_status="completed",
                review_answer=review_answer,
            )

    monkeypatch.setattr(sumsub_mod, "_live_provider", lambda: _Provider())

    outcome = SumsubVerificationAdapter().verify(
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference=str(uuid.uuid4()),
            payload={"webhook": {"applicantId": "app-77"}, "subject_role": "UBO"},
        )
    )
    assert outcome.status is expected_status
    assert outcome.provider == SUMSUB_PROVIDER
    assert outcome.provider_reference == "app-77"
    # VerificationEntityType has no UBO member; the distinction is preserved here.
    assert outcome.normalized_result["subject_role"] == "UBO"


async def test_a_known_applicant_records_pending(monkeypatch):
    monkeypatch.setattr(sumsub_mod, "_require_enabled", lambda: None)
    outcome = SumsubVerificationAdapter().verify(
        VerificationRequest(
            verification_type=VerificationType.KYC,
            entity_type=VerificationEntityType.DIRECTOR,
            entity_reference=str(uuid.uuid4()),
            payload={"applicant_id": "app-42"},
        )
    )
    assert outcome.status is VerificationResultStatus.PENDING
    assert outcome.provider_reference == "app-42"
    assert outcome.normalized_result["awaiting"] == "sumsub_webhook"


async def test_sumsub_without_a_webhook_or_applicant_says_what_to_do(monkeypatch):
    monkeypatch.setattr(sumsub_mod, "_require_enabled", lambda: None)
    with pytest.raises(InvalidProviderPayloadError) as excinfo:
        SumsubVerificationAdapter().verify(
            VerificationRequest(
                verification_type=VerificationType.KYC,
                entity_type=VerificationEntityType.DIRECTOR,
                entity_reference=str(uuid.uuid4()),
                payload={},
            )
        )
    assert "create_applicant_for" in excinfo.value.detail


async def test_a_sumsub_webhook_result_persists_with_sumsub_as_provider(monkeypatch):
    monkeypatch.setattr(sumsub_mod, "_require_enabled", lambda: None)

    class _Provider:
        def parse_webhook(self, payload):
            from app.shared.contracts.identity import WebhookParseResult

            return WebhookParseResult(
                event_type="applicantReviewed",
                applicant_id="app-101",
                external_user_id="cust-1",
                review_status="completed",
                review_answer="GREEN",
            )

    monkeypatch.setattr(sumsub_mod, "_live_provider", lambda: _Provider())

    async with db_services.AsyncSessionLocal() as db:
        result = await VerificationService(db).trigger_verification(
            VerificationType.KYC,
            VerificationEntityType.DIRECTOR,
            uuid.uuid4(),
            provider=SUMSUB_PROVIDER,
            payload={"webhook": {"applicantId": "app-101"}},
            actor_id="tester",
        )

    assert result.provider == SUMSUB_PROVIDER
    assert result.status is VerificationResultStatus.PASSED
    assert result.provider_reference == "app-101"


# ── Polling is not available on either adapter ───────────────────────────────

@pytest.mark.parametrize(
    "adapter", [KybVerificationAdapter(), SumsubVerificationAdapter()], ids=["kyb", "sumsub"]
)
async def test_polling_raises_rather_than_inventing_a_status(adapter):
    """Neither can poll today — the KYB wrapper cannot tell which vendor issued
    a bare reference, and `SumsubProvider` has no status-fetch call at all.
    Raising beats returning a status that misrepresents an unknown as an answer.
    """
    with pytest.raises(ProviderCapabilityError) as excinfo:
        adapter.get_verification_status("some-reference")
    assert excinfo.value.status_code == 422
