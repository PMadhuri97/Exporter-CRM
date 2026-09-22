"""
Contract, registry, and dependency-injection tests for the provider framework.

These tests are the enforcement arm of the backlog's acceptance criteria:

* the mock adapters run the whole flow with no vendor credentials and no network,
* a contract test fails if an adapter misses a required method,
* core workflow imports only the contract, never a vendor module,
* two different provider names resolve to two different adapters,
* a missing / disabled / incapable provider fails with a structured 422 domain
  error *before* any external call.
"""
from __future__ import annotations

import ast
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.onboarding.domain.dto import (
    PROVIDER_CONTRACT_VERSION,
    CheckRequest,
    CheckType,
    NormalizedResult,
    OverallStatus,
    ProfileInput,
    ProviderCapability,
    ProviderCheckState,
    RiskLevel,
    SubjectInput,
    SubjectRef,
    SubjectType,
    WebhookRequest,
)
from app.modules.onboarding.domain.ports import (
    ALL_CONTRACT_METHODS,
    PROTOCOL_FOR_CAPABILITY,
    REQUIRED_METHODS,
    IdentityVerificationProvider,
    ScreeningProvider,
    SupportsWebhook,
)
from app.modules.onboarding.exceptions import (
    InvalidProviderPayloadError,
    ProviderCapabilityError,
    ProviderFailureReason,
    ProviderNormalizationError,
    ProviderNotEnabledError,
    ProviderNotRegisteredError,
)
from app.modules.onboarding.infrastructure.adapters.mock_provider import (
    _VALID_MOCK_SIGNATURE,
    MockIdentityProviderAdapter,
    MockScreeningProviderAdapter,
)
from app.modules.onboarding.infrastructure.dependencies import ProviderResolver
from app.modules.onboarding.infrastructure.registry import (
    ProviderRegistry,
    build_default_registry,
    reset_provider_registry,
)
from app.platform.configuration.config import Settings

#: The six method names the backlog names. Hardcoded rather than
#: imported, so that deleting a method from the contract fails this test instead of
#: silently shrinking the expectation.
BACKLOG_REQUIRED_METHODS = frozenset(
    {
        "create_subject",
        "submit_profile",
        "start_checks",
        "get_status",
        "parse_webhook",
        "normalize_result",
    }
)

ALL_ADAPTER_CLASSES = [MockIdentityProviderAdapter, MockScreeningProviderAdapter]


@pytest.fixture
def registry() -> ProviderRegistry:
    """A registry with both mock adapters registered and enabled."""
    return build_default_registry(
        Settings(ONBOARDING_ENABLED_PROVIDERS="mock,mock_screening")  # type: ignore[call-arg]
    )


@pytest.fixture(autouse=True)
def _reset_global_registry():
    """Keep the process-wide registry from leaking configuration between tests."""
    reset_provider_registry()
    yield
    reset_provider_registry()


def _subject_ref(provider: str = "mock") -> SubjectRef:
    return SubjectRef(
        provider_name=provider,
        provider_subject_id=f"{provider}-subject-abc",
        external_subject_id="abc",
    )


def _check_request(provider: str = "mock") -> CheckRequest:
    return CheckRequest(
        case_id=uuid.uuid4(),
        subject_ref=_subject_ref(provider),
        check_types=(CheckType.IDENTITY,),
        country_code="IN",
    )


# ── The contract itself ──────────────────────────────────────────────────────


def test_contract_covers_exactly_the_six_backlog_methods():
    """The union of all capabilities is the six methods the backlog names."""
    assert ALL_CONTRACT_METHODS == BACKLOG_REQUIRED_METHODS


def test_screening_capability_excludes_subject_lifecycle_methods():
    """
    The reason the contract is composed rather than flat: a screening provider has
    no subject to open and no profile to submit.
    """
    screening = REQUIRED_METHODS[ProviderCapability.SCREENING]
    assert "create_subject" not in screening
    assert "submit_profile" not in screening
    assert {"start_checks", "get_status", "parse_webhook", "normalize_result"} <= screening


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_every_adapter_declares_a_name_and_capabilities(adapter_cls):
    adapter = adapter_cls()
    assert isinstance(adapter.name, str) and adapter.name
    assert adapter.capabilities
    assert all(isinstance(c, ProviderCapability) for c in adapter.capabilities)


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_every_adapter_implements_every_method_its_capabilities_require(adapter_cls):
    """
    The acceptance criterion: 'contract tests fail if an adapter misses a required
    method'. Reported per-method, so a failure names what is missing.
    """
    adapter = adapter_cls()
    for capability in adapter.capabilities:
        for method in REQUIRED_METHODS[capability]:
            assert callable(getattr(adapter, method, None)), (
                f"{adapter_cls.__name__} declares {capability.value} "
                f"but is missing required method '{method}'"
            )


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_every_adapter_structurally_satisfies_its_declared_protocols(adapter_cls):
    adapter = adapter_cls()
    assert isinstance(adapter, SupportsWebhook)
    for capability in adapter.capabilities:
        assert isinstance(adapter, PROTOCOL_FOR_CAPABILITY[capability])


def test_an_adapter_missing_a_method_fails_the_contract_check():
    """The contract test must actually be able to fail. This proves it."""

    class BrokenAdapter:
        name = "broken"
        capabilities = frozenset({ProviderCapability.IDENTITY_VERIFICATION})

        # create_subject deliberately absent.
        async def submit_profile(self, profile): ...
        async def start_checks(self, request): ...
        async def get_status(self, provider_reference): ...
        def parse_webhook(self, request): ...
        def normalize_result(self, *, raw_payload, provider_run_id=None): ...

    broken = BrokenAdapter()
    missing = [
        m
        for m in REQUIRED_METHODS[ProviderCapability.IDENTITY_VERIFICATION]
        if not callable(getattr(broken, m, None))
    ]
    assert missing == ["create_subject"]
    assert not isinstance(broken, IdentityVerificationProvider)


def test_screening_adapter_does_not_satisfy_the_identity_protocol():
    assert not isinstance(MockScreeningProviderAdapter(), IdentityVerificationProvider)
    assert isinstance(MockScreeningProviderAdapter(), ScreeningProvider)


def test_dtos_are_version_stamped_and_immutable():
    ref = _subject_ref()
    assert ref.contract_version == PROVIDER_CONTRACT_VERSION
    with pytest.raises(Exception):  # pydantic ValidationError on a frozen model
        ref.provider_subject_id = "tampered"


def test_profile_input_never_reprs_its_pii():
    """
    ProfileInput.attributes is repr=False. A traceback or a log line that captures
    this DTO must not leak the subject's personal data.
    """
    profile = ProfileInput(
        subject_ref=_subject_ref(),
        attributes={"first_name": "Ada", "national_id": "SECRET-1234"},
    )
    rendered = repr(profile)
    assert "SECRET-1234" not in rendered
    assert "Ada" not in rendered


def test_webhook_event_exposes_no_verdict():
    """
    The old WebhookParseResult had .approved / .rejected, and that is exactly how a
    provider's verdict became the platform's verdict. The new DTO has neither.
    """
    from app.modules.onboarding.domain.dto import WebhookEvent

    assert "approved" not in WebhookEvent.model_fields
    assert "rejected" not in WebhookEvent.model_fields
    assert not hasattr(WebhookEvent, "approved")
    assert not hasattr(WebhookEvent, "rejected")


# ── Mock adapters run credential-free ────────────────────────────────────────


async def test_identity_adapter_runs_the_full_flow_without_credentials():
    """AC: the mock runs the lifecycle with no real vendor credentials."""
    adapter = MockIdentityProviderAdapter()
    case_id = uuid.uuid4()

    subject = await adapter.create_subject(
        SubjectInput(
            case_id=case_id,
            external_subject_id="abc",
            subject_type=SubjectType.INDIVIDUAL,
            country_code="IN",
        )
    )
    assert subject.provider_name == "mock"

    profile = await adapter.submit_profile(
        ProfileInput(subject_ref=subject, attributes={"first_name": "Ada"})
    )
    assert profile.provider_subject_id == subject.provider_subject_id

    run = await adapter.start_checks(
        CheckRequest(
            case_id=case_id,
            subject_ref=subject,
            check_types=(CheckType.IDENTITY, CheckType.DOCUMENT),
            country_code="IN",
        )
    )
    assert run.state is ProviderCheckState.IN_PROGRESS

    status = await adapter.get_status(run.provider_reference)
    assert status.state is ProviderCheckState.COMPLETED


async def test_create_subject_is_idempotent_for_the_same_external_id():
    adapter = MockIdentityProviderAdapter()
    payload = SubjectInput(
        case_id=uuid.uuid4(),
        external_subject_id="abc",
        subject_type=SubjectType.INDIVIDUAL,
        country_code="IN",
    )
    first = await adapter.create_subject(payload)
    second = await adapter.create_subject(payload)
    assert first.provider_subject_id == second.provider_subject_id


async def test_screening_adapter_runs_checks_without_a_subject_lifecycle():
    adapter = MockScreeningProviderAdapter()
    run = await adapter.start_checks(
        CheckRequest(
            case_id=uuid.uuid4(),
            subject_ref=_subject_ref("mock_screening"),
            check_types=(CheckType.SANCTIONS, CheckType.PEP),
            country_code="IN",
        )
    )
    assert run.provider_name == "mock_screening"
    assert not hasattr(adapter, "create_subject")


# ── Webhook parsing ──────────────────────────────────────────────────────────


def test_parse_webhook_marks_a_signed_event_verified():
    adapter = MockIdentityProviderAdapter()
    event = adapter.parse_webhook(
        WebhookRequest(
            body=json.dumps({"state": "COMPLETED", "reference": "r1"}).encode(),
            headers={"x-mock-signature": _VALID_MOCK_SIGNATURE},
        )
    )
    assert event.signature_verified is True
    assert event.state is ProviderCheckState.COMPLETED
    assert event.provider_reference == "r1"


def test_parse_webhook_marks_an_unsigned_event_unverified():
    """An unverified event is rejected and audited by the caller, never processed."""
    adapter = MockIdentityProviderAdapter()
    event = adapter.parse_webhook(
        WebhookRequest(body=json.dumps({"state": "COMPLETED"}).encode(), headers={})
    )
    assert event.signature_verified is False


def test_parse_webhook_rejects_a_malformed_body():
    adapter = MockIdentityProviderAdapter()
    with pytest.raises(InvalidProviderPayloadError) as exc:
        adapter.parse_webhook(WebhookRequest(body=b"not json", headers={}))
    assert exc.value.failure_reason is ProviderFailureReason.INVALID_PAYLOAD
    assert exc.value.status_code == 422


# ── Normalization ────────────────────────────────────────────────────────────


def test_both_providers_normalize_into_the_same_structure():
    """
    The shape the contract demands: an identity fixture and a screening fixture produce
    the same NormalizedResult structure.
    """
    identity = MockIdentityProviderAdapter().normalize_result(
        raw_payload={"state": "COMPLETED", "risk": "LOW", "checks": {"IDENTITY": "LOW"}}
    )
    screening = MockScreeningProviderAdapter().normalize_result(
        raw_payload={"state": "COMPLETED", "risk": "LOW", "checks": {"SANCTIONS": "LOW"}}
    )

    assert isinstance(identity, NormalizedResult)
    assert isinstance(screening, NormalizedResult)
    assert set(identity.model_fields) == set(screening.model_fields)
    assert identity.overall_status is screening.overall_status is OverallStatus.CLEAR
    assert identity.provider_name != screening.provider_name


def test_normalized_result_never_carries_the_raw_payload():
    """Evidence references point at raw payload records without exposing raw data."""
    raw = {"state": "COMPLETED", "risk": "LOW", "secret_document_url": "https://vendor/doc/1"}
    result = MockIdentityProviderAdapter().normalize_result(raw_payload=raw)

    serialized = result.model_dump_json()
    assert "secret_document_url" not in serialized
    assert "https://vendor/doc/1" not in serialized
    assert result.evidence_refs
    assert result.evidence_refs[0].uri.startswith("evidence://")


def test_an_unknown_check_type_round_trips_without_a_migration():
    """The schema supports future check types with no migration churn."""
    result = MockIdentityProviderAdapter().normalize_result(
        raw_payload={"state": "COMPLETED", "risk": "LOW", "checks": {"QUANTUM_BIOMETRICS": "LOW"}}
    )
    assert [o.check_type for o in result.check_outcomes] == ["QUANTUM_BIOMETRICS"]


def test_a_provider_failure_normalizes_to_failed_and_never_to_a_rejection():
    result = MockIdentityProviderAdapter().normalize_result(
        raw_payload={"state": "FAILED", "failure_reason": "TIMEOUT"}
    )
    assert result.overall_status is OverallStatus.FAILED
    assert result.failure_details is not None
    assert result.failure_details.reason is ProviderFailureReason.TIMEOUT
    assert result.failure_details.retryable is True
    assert result.recommended_action.value != "REJECT"


def test_an_unmappable_payload_raises_a_structured_normalization_error():
    with pytest.raises(ProviderNormalizationError) as exc:
        MockIdentityProviderAdapter().normalize_result(raw_payload={"state": "WAT"})
    assert exc.value.failure_reason is ProviderFailureReason.NORMALIZATION_ERROR


def test_critical_risk_recommends_escalation_not_automatic_rejection():
    result = MockIdentityProviderAdapter().normalize_result(
        raw_payload={"state": "COMPLETED", "risk": "CRITICAL"}
    )
    assert result.risk_level is RiskLevel.CRITICAL
    assert result.overall_status is OverallStatus.MANUAL_REVIEW


# ── Registry ─────────────────────────────────────────────────────────────────


def test_registry_resolves_two_different_names_to_two_different_adapters(registry):
    identity = registry.create("mock")
    screening = registry.create("mock_screening")
    assert type(identity) is not type(screening)
    assert identity.name != screening.name


def test_registry_rejects_an_unknown_provider_name(registry):
    with pytest.raises(ProviderNotRegisteredError) as exc:
        registry.create("does_not_exist")
    assert exc.value.error_code == "PROVIDER_NOT_REGISTERED"
    assert exc.value.status_code == 422


def test_registry_distinguishes_disabled_from_unknown():
    """
    A disabled provider is a configuration problem and says so, rather than
    masquerading as a typo.
    """
    reg = build_default_registry(Settings(ONBOARDING_ENABLED_PROVIDERS="mock"))  # type: ignore[call-arg]
    assert reg.create("mock").name == "mock"
    with pytest.raises(ProviderNotEnabledError) as exc:
        reg.create("mock_screening")
    assert exc.value.error_code == "PROVIDER_NOT_ENABLED"
    assert "mock_screening" in reg.registered_names()
    assert "mock_screening" not in reg.enabled_names()


def test_registry_refuses_an_adapter_that_lacks_the_requested_capability(registry):
    with pytest.raises(ProviderCapabilityError) as exc:
        registry.create_for_capability("mock_screening", ProviderCapability.IDENTITY_VERIFICATION)
    assert exc.value.error_code == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert exc.value.status_code == 422


def test_registry_capability_check_uses_declaration_not_just_structure(registry):
    """
    The identity adapter structurally satisfies ScreeningProvider — screening's
    method set is a subset of identity's — but it does not *declare* SCREENING, so
    the registry must refuse it. Structure alone is not enough.
    """
    assert isinstance(MockIdentityProviderAdapter(), ScreeningProvider)
    with pytest.raises(ProviderCapabilityError):
        registry.create_for_capability("mock", ProviderCapability.SCREENING)


def test_registry_lists_names_by_capability(registry):
    assert registry.names_for_capability(ProviderCapability.IDENTITY_VERIFICATION) == ("mock",)
    assert registry.names_for_capability(ProviderCapability.SCREENING) == ("mock_screening",)


def test_registry_returns_a_fresh_adapter_per_call(registry):
    """Adapters own HTTP clients; they must not be shared across event loops."""
    assert registry.create("mock") is not registry.create("mock")


def test_registry_refuses_duplicate_registration_unless_replacing():
    reg = ProviderRegistry()
    reg.register("x", lambda: MockIdentityProviderAdapter())
    with pytest.raises(ValueError, match="already registered"):
        reg.register("x", lambda: MockIdentityProviderAdapter())
    reg.register("x", lambda: MockScreeningProviderAdapter(), replace=True)


def test_a_new_provider_needs_no_change_to_existing_business_logic():
    """
    The extensibility requirement, made executable: registering a brand-new adapter
    and enabling it is enough for resolve-by-name to find it.
    """

    class FutureProviderAdapter(MockIdentityProviderAdapter):
        name = "future_vendor"

    reg = ProviderRegistry()
    reg.register("future_vendor", FutureProviderAdapter)
    reg.enable("future_vendor")

    adapter = reg.create_for_capability("future_vendor", ProviderCapability.IDENTITY_VERIFICATION)
    assert adapter.name == "future_vendor"


def test_an_enabled_but_unregistered_name_does_not_break_startup():
    """A stale env var must not stop the application booting."""
    reg = build_default_registry(
        Settings(ONBOARDING_ENABLED_PROVIDERS="mock,ghost_vendor")  # type: ignore[call-arg]
    )
    assert reg.enabled_names() == ("mock",)
    with pytest.raises(ProviderNotRegisteredError):
        reg.create("ghost_vendor")


# ── Configuration ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mock", ("mock",)),
        ("mock,mock_screening", ("mock", "mock_screening")),
        (" mock , mock_screening ", ("mock", "mock_screening")),
        ("mock,,mock", ("mock",)),
        ("", ()),
    ],
)
def test_enabled_provider_names_are_parsed_from_configuration(raw, expected):
    assert Settings(ONBOARDING_ENABLED_PROVIDERS=raw).onboarding_enabled_provider_names == expected  # type: ignore[call-arg]


# ── Dependency injection ─────────────────────────────────────────────────────


def test_resolver_returns_capability_checked_adapters(registry):
    resolver = ProviderResolver(registry)
    assert resolver.identity("mock").name == "mock"
    assert resolver.screening("mock_screening").name == "mock_screening"
    assert resolver.any_provider("mock").name == "mock"


def test_resolver_reports_enabled_names_by_capability(registry):
    resolver = ProviderResolver(registry)
    assert set(resolver.enabled_names()) == {"mock", "mock_screening"}
    assert resolver.enabled_names(ProviderCapability.SCREENING) == ("mock_screening",)


def test_resolver_raises_before_any_external_call(registry):
    """
    Every resolution failure is a 422 domain error raised before a provider_run row
    could exist — the discipline the contract requires.
    """
    resolver = ProviderResolver(registry)
    for bad_call in (
        lambda: resolver.identity("nope"),
        lambda: resolver.identity("mock_screening"),
        lambda: resolver.screening("mock"),
    ):
        with pytest.raises((ProviderNotRegisteredError, ProviderCapabilityError)) as exc:
            bad_call()
        assert exc.value.status_code == 422


# ── Architectural boundary ───────────────────────────────────────────────────

# The test now lives at <module>/tests/unit/, so the module root is two levels up.
_ONBOARDING_DIR = Path(__file__).resolve().parents[2]

#: Modules that make up the framework. None may import a vendor adapter: the
#: registry constructs adapters lazily, inside factory callables.
#: (Paths are module-relative: the framework was split across the §6 domain template.)
_FRAMEWORK_MODULES = [
    "domain/ports.py",
    "domain/dto.py",
    "exceptions.py",
    "infrastructure/dependencies.py",
]


def _module_level_imports(path: Path) -> set[str]:
    """Every module imported at import time — ignores imports inside functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in tree.body:  # top level only
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


@pytest.mark.parametrize("module_name", _FRAMEWORK_MODULES)
def test_framework_modules_never_import_a_vendor_adapter(module_name):
    """
    AC: 'core workflow imports only the provider contract, not
    Sumsub/ComplyAdvantage modules.'
    """
    imports = _module_level_imports(_ONBOARDING_DIR / module_name)
    offenders = [
        i for i in imports if "sumsub" in i.lower() or "comply" in i.lower() or ".adapters" in i
    ]
    assert offenders == [], f"{module_name} imports vendor modules: {offenders}"


def test_the_registry_imports_no_vendor_adapter_at_module_level():
    """
    The registry names adapters only inside factory callables, so a disabled
    provider is never imported and its credentials are never read.
    """
    imports = _module_level_imports(_ONBOARDING_DIR / "infrastructure" / "registry.py")
    assert not any("adapters" in i for i in imports)
    assert not any("sumsub" in i.lower() for i in imports)


def test_contract_is_still_marked_unfrozen():
    """
    Escalation E1 is open: Tejasvi must ratify the capability split before the
    contract freezes. When he does, drop the '-draft' suffix and delete this test.
    """
    assert PROVIDER_CONTRACT_VERSION.endswith("-draft")


def test_evidence_ref_digest_is_stable_and_content_addressed():
    adapter = MockIdentityProviderAdapter()
    payload = {"state": "COMPLETED", "risk": "LOW"}
    first = adapter.normalize_result(raw_payload=payload).evidence_refs[0]
    second = adapter.normalize_result(raw_payload=dict(reversed(list(payload.items())))).evidence_refs[0]
    assert first.sha256 == second.sha256  # key order must not change the digest
    assert first.captured_at <= datetime.now(tz=UTC)
