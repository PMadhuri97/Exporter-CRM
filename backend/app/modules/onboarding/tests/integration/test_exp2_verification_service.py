"""Integration tests for EXP-2's `VerificationService` against real Postgres.

Follows `test_s1t4_kyb_vendor_registry.py` / `test_s7t1_onboarding_service_api.py`'s
conventions: real Postgres, no per-test rollback, each test opens its own
`AsyncSessionLocal()` session(s) directly, and isolation comes from every test
minting its own fresh ids rather than a shared prefix + wipe fixture.

Fake adapters, registered/unregistered per test
------------------------------------------------
Several tests register a small local `VerificationAdapter` double directly
into `VERIFICATION_ADAPTER_REGISTRY` under a unique, test-scoped provider
name, and remove it again in a `finally` block — the same registry
`ManualEntryAdapter` self-registers into at import time, so these tests prove
the service works with *any* conforming adapter, not just the one this ticket
ships. `RxilAdapter` doesn't exist until the next ticket, so
`test_provider_is_never_rewritten` uses exactly this mechanism to prove the
guarantee ahead of that integration landing (this was the ticket's own
prescribed approach — the retired EXP-2 ticket's acceptance criteria).

Dev4B (4B-2, 4B-4, 4B-5): EXPORTER and BUYER subjects must exist, so those tests
create a real company / deal buyer; a manual PASSED carries evidence; and the
one-review-only rule is replaced by superseding reviews
(`test_record_review_supersedes_the_current_review_instead_of_overwriting_it`).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.domain.workflow_dependencies import (
    VERIFICATION_ADAPTER_REGISTRY,
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    register_adapter,
)
from app.modules.onboarding.exceptions import (
    VerificationResultNotReviewableError,
    VerificationReviewStaleError,
)
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.database import services as db_services
from app.shared.contracts.kyb import VendorHealthStatus
from app.shared.enums.kyb import KYBVendorProcessingMode, VendorHealthStatusEnum
from app.shared.exceptions import NotFoundError, ValidationError


def _actor() -> str:
    return f"officer-{uuid.uuid4().hex[:8]}"


_NOTE = VerificationEvidence(note="Checked against the source document.")


async def _deal_buyer() -> uuid.UUID:
    company_id = await make_prospect()  # a deal needs a prospect
    async with db_services.AsyncSessionLocal() as db:
        deal = await DealService(db).open_deal(company_id, reference="EXP-2", actor_id="t")
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).set_buyer(deal.id, actor_id="t", name="Buyer BV", country="NL")
    return view.buyer.id


class _FakeAlwaysPassAdapter:
    """A structurally-conforming double used to prove
    `trigger_verification` treats every `verification_type`/`entity_type`
    combination identically — it has no idea what any of them mean."""

    PROVIDER = "fake_always_pass"

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider=self.PROVIDER,
            supported_verification_types=tuple(VerificationType),
            supported_entity_types=tuple(VerificationEntityType),
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify(self, request) -> VerificationOutcome:
        return VerificationOutcome(
            provider=self.PROVIDER,
            provider_reference=f"ref-{request.verification_type.value}-{request.entity_type.value}",
            status=VerificationResultStatus.PASSED,
            normalized_result={"echoed_payload": dict(request.payload)},
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        raise NotImplementedError

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=1)


class _FakeRxilAdapter:
    """Simulates a real vendor whose *registry key* differs from its own
    self-reported `provider` name — exactly the scenario the "provider is
    never rewritten" acceptance criterion needs, since RxilAdapter itself
    isn't built until the next ticket. Registered under
    `"fake_rxil_registry_key"`, but every `VerificationOutcome` it returns
    reports `provider="RXIL"`.
    """

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider="RXIL",
            supported_verification_types=(VerificationType.BUYER,),
            supported_entity_types=(VerificationEntityType.BUYER,),
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify(self, request) -> VerificationOutcome:
        return VerificationOutcome(
            provider="RXIL",
            provider_reference="rxil-ext-ref-1",
            status=VerificationResultStatus.PASSED,
            normalized_result={"buyer_rating": "A"},
        )

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        return VerificationOutcome(
            provider="RXIL",
            provider_reference=provider_reference,
            status=VerificationResultStatus.PASSED,
            normalized_result={"buyer_rating": "A"},
        )

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=1)


class _FakeAsyncVendorAdapter:
    """Simulates an asynchronous vendor: `verify()` reports PENDING, and
    `get_verification_status()` later reports whatever this test-controlled,
    class-level state dict says — used to prove `get_verification_status`
    updates the stored row when (and only when) the answer has changed."""

    PROVIDER = "fake_async_vendor"
    STATE: dict[str, VerificationOutcome] = {}

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        return VerificationCapabilityDeclaration(
            provider=self.PROVIDER,
            supported_verification_types=(VerificationType.KYC,),
            supported_entity_types=(VerificationEntityType.DIRECTOR,),
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify(self, request) -> VerificationOutcome:
        ref = request.payload["provider_reference"]
        outcome = VerificationOutcome(
            provider=self.PROVIDER,
            provider_reference=ref,
            status=VerificationResultStatus.PENDING,
            normalized_result={"stage": "submitted"},
        )
        self.STATE[ref] = outcome
        return outcome

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        return self.STATE[provider_reference]

    def get_vendor_health(self) -> VendorHealthStatus:
        return VendorHealthStatus(status=VendorHealthStatusEnum.HEALTHY, response_time_ms=1)


@pytest.fixture
def registered_fake_always_pass():
    register_adapter(_FakeAlwaysPassAdapter.PROVIDER, _FakeAlwaysPassAdapter)
    yield _FakeAlwaysPassAdapter.PROVIDER
    VERIFICATION_ADAPTER_REGISTRY.pop(_FakeAlwaysPassAdapter.PROVIDER, None)


@pytest.fixture
def registered_fake_rxil():
    register_adapter("fake_rxil_registry_key", _FakeRxilAdapter)
    yield "fake_rxil_registry_key"
    VERIFICATION_ADAPTER_REGISTRY.pop("fake_rxil_registry_key", None)


@pytest.fixture
def registered_fake_async_vendor():
    register_adapter(_FakeAsyncVendorAdapter.PROVIDER, _FakeAsyncVendorAdapter)
    yield _FakeAsyncVendorAdapter.PROVIDER
    VERIFICATION_ADAPTER_REGISTRY.pop(_FakeAsyncVendorAdapter.PROVIDER, None)


# ── ManualEntryAdapter round-trip ─────────────────────────────────────────────


async def test_manual_entry_adapter_round_trips_trigger_to_list():
    entity_reference = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        result = await svc.trigger_verification(
            VerificationType.BANK_ACCOUNT,
            VerificationEntityType.EXPORTER,
            entity_reference,
            provider="manual",
            payload={
                "status": "PASSED",
                "normalized_result": {"account_holder_name": "Acme Exports"},
                "provider_reference": f"manual-{uuid.uuid4().hex[:8]}",
            },
            actor_id=_actor(),
            evidence=_NOTE,
        )

    assert result.provider == "manual"
    assert result.status is VerificationResultStatus.PASSED
    assert result.verification_type is VerificationType.BANK_ACCOUNT
    assert result.entity_type is VerificationEntityType.EXPORTER
    assert result.entity_reference == entity_reference
    assert result.normalized_result == {"account_holder_name": "Acme Exports"}
    # raw_result is the payload the caller supplied to the adapter (see
    # verification_service.py's _result_from_outcome docstring).
    assert result.raw_result["status"] == "PASSED"

    async with db_services.AsyncSessionLocal() as db:
        svc2 = VerificationService(db)
        listed = await svc2.list_verification_results(
            VerificationEntityType.EXPORTER, entity_reference
        )

    assert len(listed) == 1
    assert listed[0].id == result.id


async def test_manual_entry_adapter_rejects_missing_status_before_persisting():
    from app.modules.onboarding.exceptions import InvalidProviderPayloadError

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(InvalidProviderPayloadError):
            await svc.trigger_verification(
                VerificationType.KYC,
                VerificationEntityType.DIRECTOR,
                uuid.uuid4(),
                provider="manual",
                payload={},  # no 'status'
                actor_id=_actor(),
            )


# ── The central acceptance criterion: identical code path ────────────────────


async def test_kyc_director_and_bank_account_exporter_share_identical_code_path(
    registered_fake_always_pass,
):
    """A KYC check on a DIRECTOR and a BANK_ACCOUNT check on an EXPORTER both
    go through the exact same `trigger_verification` call and the exact same
    registry lookup. `_FakeAlwaysPassAdapter` has no type-specific logic at
    all — if the service special-cased `verification_type` anywhere, one of
    these two calls would either fail (the special case wouldn't recognize
    the fake provider/type combination) or silently diverge in shape from
    the other. Both succeed, and both come back with exactly the fields their
    own request named — nothing more, nothing type-specific bolted on.
    """
    director_id = uuid.uuid4()
    exporter_id = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        kyc_result = await svc.trigger_verification(
            VerificationType.KYC,
            VerificationEntityType.DIRECTOR,
            director_id,
            provider=registered_fake_always_pass,
            payload={"first_name": "Jane"},
            actor_id=_actor(),
        )
        bank_result = await svc.trigger_verification(
            VerificationType.BANK_ACCOUNT,
            VerificationEntityType.EXPORTER,
            exporter_id,
            provider=registered_fake_always_pass,
            payload={"account_number": "0001"},
            actor_id=_actor(),
        )

    for result, vtype, etype, entity_id, payload_key in (
        (kyc_result, VerificationType.KYC, VerificationEntityType.DIRECTOR, director_id, "first_name"),
        (bank_result, VerificationType.BANK_ACCOUNT, VerificationEntityType.EXPORTER, exporter_id, "account_number"),
    ):
        assert result.verification_type is vtype
        assert result.entity_type is etype
        assert result.entity_reference == entity_id
        assert result.provider == _FakeAlwaysPassAdapter.PROVIDER
        assert result.status is VerificationResultStatus.PASSED
        assert payload_key in result.normalized_result["echoed_payload"]


# ── Provider fidelity ─────────────────────────────────────────────────────────


async def test_provider_is_never_rewritten(registered_fake_rxil):
    """A result recorded with provider="RXIL" is never observable as anything
    else — not "Internal", not the registry key ("fake_rxil_registry_key")
    the caller passed as `provider=`, anywhere in the read path."""
    buyer_id = await _deal_buyer()

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        triggered = await svc.trigger_verification(
            VerificationType.BUYER,
            VerificationEntityType.BUYER,
            buyer_id,
            provider=registered_fake_rxil,
            payload={},
            actor_id=_actor(),
        )

    assert triggered.provider == "RXIL"
    assert triggered.provider != registered_fake_rxil
    assert triggered.provider != "Internal"

    async with db_services.AsyncSessionLocal() as db:
        svc2 = VerificationService(db)
        listed = await svc2.list_verification_results(VerificationEntityType.BUYER, buyer_id)
        fetched = await db.get(type(triggered), triggered.id)

    assert listed[0].provider == "RXIL"
    assert fetched.provider == "RXIL"


# ── Polling / status updates ──────────────────────────────────────────────────


async def test_get_verification_status_updates_row_when_status_changes(
    registered_fake_async_vendor,
):
    director_id = uuid.uuid4()
    provider_reference = f"async-ref-{uuid.uuid4().hex[:8]}"

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        triggered = await svc.trigger_verification(
            VerificationType.KYC,
            VerificationEntityType.DIRECTOR,
            director_id,
            provider=registered_fake_async_vendor,
            payload={"provider_reference": provider_reference},
            actor_id=_actor(),
        )

    assert triggered.status is VerificationResultStatus.PENDING

    # The external vendor now reports a final answer.
    _FakeAsyncVendorAdapter.STATE[provider_reference] = VerificationOutcome(
        provider=_FakeAsyncVendorAdapter.PROVIDER,
        provider_reference=provider_reference,
        status=VerificationResultStatus.PASSED,
        normalized_result={"stage": "final"},
        risk_level=VerificationRiskLevel.LOW,
    )

    async with db_services.AsyncSessionLocal() as db:
        svc2 = VerificationService(db)
        polled = await svc2.get_verification_status(provider_reference)

    assert polled.status is VerificationResultStatus.PASSED
    assert polled.normalized_result == {"stage": "final"}
    assert polled.risk_level is VerificationRiskLevel.LOW

    # Persisted, not just returned in-memory.
    async with db_services.AsyncSessionLocal() as db:
        refreshed = await db.get(type(polled), polled.id)
    assert refreshed.status is VerificationResultStatus.PASSED


async def test_get_verification_status_raises_not_found_for_unknown_reference():
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(NotFoundError):
            await svc.get_verification_status(f"no-such-ref-{uuid.uuid4().hex}")


# ── list_verification_results ────────────────────────────────────────────────


async def test_list_verification_results_scoped_to_entity():
    entity_a = uuid.uuid4()
    entity_b = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        await svc.trigger_verification(
            VerificationType.KYC, VerificationEntityType.DIRECTOR, entity_a,
            payload={"status": "PASSED"}, actor_id=_actor(), evidence=_NOTE,
        )
        await svc.trigger_verification(
            VerificationType.AML, VerificationEntityType.DIRECTOR, entity_a,
            payload={"status": "FAILED"}, actor_id=_actor(),
        )
        await svc.trigger_verification(
            VerificationType.KYC, VerificationEntityType.DIRECTOR, entity_b,
            payload={"status": "PASSED"}, actor_id=_actor(), evidence=_NOTE,
        )

        results_a = await svc.list_verification_results(VerificationEntityType.DIRECTOR, entity_a)
        results_b = await svc.list_verification_results(VerificationEntityType.DIRECTOR, entity_b)

    assert len(results_a) == 2
    assert len(results_b) == 1
    assert {r.entity_reference for r in results_a} == {entity_a}


# ── record_review ─────────────────────────────────────────────────────────────


async def test_record_review_adds_the_first_review():
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        triggered = await svc.trigger_verification(
            VerificationType.KYC, VerificationEntityType.DIRECTOR, uuid.uuid4(),
            payload={"status": "REVIEW"}, actor_id=_actor(),
        )

        review = await svc.record_review(
            triggered.id, reviewed_by="compliance_officer_1",
            review_status=VerificationReviewStatus.ACCEPTED,
        )

    assert review.verification_result_id == triggered.id
    assert review.reviewed_by == "compliance_officer_1"
    assert review.review_status is VerificationReviewStatus.ACCEPTED
    assert review.supersedes_review_id is None
    assert review.reviewed_at is not None

    async with db_services.AsyncSessionLocal() as db:
        view = await VerificationService(db).get_result_view(triggered.id)
    assert [r.id for r in view.reviews] == [review.id]
    # The legacy columns are no longer written (4B-2).
    assert view.result.reviewed_by is None
    assert view.result.review_status is None


async def test_record_review_supersedes_the_current_review_instead_of_overwriting_it():
    """Rewritten for 4B-2 (4b-task.md §5.1). The old rule — a second review is
    refused outright — is replaced by superseding reviews: a later review must name
    the current review, and a stale or missing name is refused (409) rather than
    silently overwriting. The earlier review is never edited."""
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        triggered = await svc.trigger_verification(
            VerificationType.KYC, VerificationEntityType.DIRECTOR, uuid.uuid4(),
            payload={"status": "REVIEW"}, actor_id=_actor(),
        )
        first = await svc.record_review(
            triggered.id, reviewed_by="compliance_officer_1",
            review_status=VerificationReviewStatus.ACCEPTED,
        )

    # A second review that does not name the current one is stale.
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(VerificationReviewStaleError) as stale:
            await VerificationService(db).record_review(
                triggered.id, reviewed_by="compliance_officer_2",
                review_status=VerificationReviewStatus.REJECTED,
                note="Disagree",
            )
    assert stale.value.status_code == 409
    assert stale.value.current_review_id == first.id

    async with db_services.AsyncSessionLocal() as db:
        second = await VerificationService(db).record_review(
            triggered.id, reviewed_by="compliance_officer_2",
            review_status=VerificationReviewStatus.REJECTED,
            note="Registry extract contradicts the director list.",
            supersedes_review_id=first.id,
        )

    async with db_services.AsyncSessionLocal() as db:
        view = await VerificationService(db).get_result_view(triggered.id)
    assert [r.id for r in view.reviews] == [first.id, second.id]
    assert view.latest_review.review_status is VerificationReviewStatus.REJECTED
    # The first decision is untouched.
    assert view.reviews[0].reviewed_by == "compliance_officer_1"
    assert view.reviews[0].review_status is VerificationReviewStatus.ACCEPTED


async def test_record_review_refuses_a_pending_result(registered_fake_async_vendor):
    """A PENDING check has no finding yet, and a review stays on the record — so
    the service refuses it (422) rather than recording a decision about nothing.
    A manual entry can no longer be PENDING (4B-6), so the PENDING row comes from
    an asynchronous vendor double."""
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        triggered = await svc.trigger_verification(
            VerificationType.KYC, VerificationEntityType.DIRECTOR, uuid.uuid4(),
            provider=registered_fake_async_vendor,
            payload={"provider_reference": f"pending-{uuid.uuid4().hex[:8]}"},
            actor_id=_actor(),
        )
        assert triggered.status is VerificationResultStatus.PENDING

        with pytest.raises(VerificationResultNotReviewableError) as refused:
            await svc.record_review(
                triggered.id, reviewed_by="compliance_officer_1",
                review_status=VerificationReviewStatus.ACCEPTED,
            )
    assert refused.value.status_code == 422

    async with db_services.AsyncSessionLocal() as db:
        view = await VerificationService(db).get_result_view(triggered.id)
    assert view.reviews == ()


async def test_record_review_raises_not_found_for_unknown_id():
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(NotFoundError):
            await svc.record_review(
                uuid.uuid4(), reviewed_by="someone",
                review_status=VerificationReviewStatus.ACCEPTED,
            )


# ── verification_type / entity_type cross-validation ─────────────────────────
#
# The pair table itself is unit-tested in
# `tests/unit/test_verification_type_pairs.py`; this is the service wiring.


async def test_trigger_verification_rejects_an_uninterpretable_pair():
    """The service rejects before resolving or calling any adapter."""
    async with db_services.AsyncSessionLocal() as db:
        svc = VerificationService(db)
        with pytest.raises(ValidationError):
            await svc.trigger_verification(
                VerificationType.VESSEL,
                VerificationEntityType.DIRECTOR,
                uuid.uuid4(),
                provider="manual",
                payload={"status": "PASSED"},
                actor_id=uuid.uuid4(),
            )
