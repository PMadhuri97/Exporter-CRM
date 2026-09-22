"""Integration tests for EXP-1's `ExporterProfileService`.

Follows `test_s7t1_onboarding_service_api.py`'s conventions: real Postgres, no
per-test rollback, each test opens its own `AsyncSessionLocal()` session(s)
directly. Isolation comes from every test minting its own fresh `customer_id`
(and, where needed, `tenant_id`), never from a shared prefix + wipe fixture.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.application.exporter_profile_service import (
    PERMITTED_LIFECYCLE_TRANSITIONS,
    ExporterProfileService,
)
from app.modules.onboarding.application.onboarding_request_service import (
    OnboardingRequestService,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRequestStatus,
)
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    ExporterSourceImmutableError,
    InvalidExporterLifecycleTransitionError,
)
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


def _empty_document_requirements() -> DocumentRequirementsService:
    return DocumentRequirementsService(
        {"version": "1.0", "profiles": [], "conditional_rules": [], "validity_periods": {}}
    )


def _address() -> dict:
    return {"street": "1 Test St", "city": "Testville", "state": "CA", "postal_code": "00000", "country": "US"}


async def _create_onboarding_request_for(customer_id_placeholder: str, legal_name: str) -> uuid.UUID:
    """Create an OnboardingRequest and return its `customer_id`.

    `ExporterProfileService.search_profiles`'s `legal_name_contains` filter
    joins against `OnboardingRequest.legal_name`, which is only ever set by
    initiating a real onboarding request — there is no shortcut that writes
    just the column this test needs.
    """
    async with db_services.AsyncSessionLocal() as db:
        svc = OnboardingRequestService(db, document_requirements=_empty_document_requirements())
        request, _ = await svc.initiate_onboarding(
            tenant_id=uuid.uuid4(),
            entity_type=OnboardingEntityType.CORPORATION,
            legal_name=legal_name,
            registration_number=f"REG-{uuid.uuid4().hex[:8]}",
            incorporation_country="US",
            registered_address=_address(),
            initial_user_email=f"{uuid.uuid4().hex[:8]}@example.com",
            idempotency_key=str(uuid.uuid4()),
        )
    return request.customer_id


# ── create_or_get_profile ─────────────────────────────────────────────────────


async def test_create_or_get_profile_creates_new():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        profile, created = await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    assert created is True
    assert profile.customer_id == customer_id
    assert profile.source == ExporterSource.SALES
    assert profile.lifecycle_status == ExporterLifecycleStatus.LEAD


async def test_create_or_get_profile_repeat_call_returns_existing_without_key():
    """No idempotency_key supplied: `uq_exporter_profile_customer_id` alone
    makes a repeat call for the same customer_id safe."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        first, first_created = await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )
    async with db_services.AsyncSessionLocal() as db:
        second, second_created = await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.MANUAL
        )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    # The second call's differing `source` argument is ignored: the row
    # already existed and is returned as-is, proving `source` cannot be
    # changed via a second create call either.
    assert second.source == ExporterSource.SALES


async def test_create_or_get_profile_idempotent_replay_with_key():
    customer_id = uuid.uuid4()
    idem_key = str(uuid.uuid4())
    async with db_services.AsyncSessionLocal() as db:
        first, first_created = await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.RXIL, idempotency_key=idem_key
        )
    async with db_services.AsyncSessionLocal() as db:
        second, second_created = await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.RXIL, idempotency_key=idem_key
        )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id


# ── create_lead (Piece 1: "Add Exporter" bare-Lead creation) ──────────────────


async def test_create_lead_creates_minimal_onboarding_request_and_profile():
    """A Lead can be created with just legal_name + incorporation_country
    (beyond the usual onboarding_request plumbing) — no registration_number,
    no registered_address."""
    legal_name = f"Cold Lead Exports {uuid.uuid4().hex[:8]}"
    async with db_services.AsyncSessionLocal() as db:
        request, profile, _created = await ExporterProfileService(db).create_lead(
            tenant_id=uuid.uuid4(),
            legal_name=legal_name,
            incorporation_country="US",
            initial_user_email=f"{uuid.uuid4().hex[:8]}@example.com",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
        )

    assert request.legal_name == legal_name
    assert request.registration_number is None
    assert request.registered_address is None
    assert request.incorporation_country == "US"
    assert request.status == OnboardingRequestStatus.DRAFT
    assert profile.customer_id == request.customer_id
    assert profile.source == ExporterSource.SALES
    assert profile.lifecycle_status == ExporterLifecycleStatus.LEAD


async def test_create_lead_then_submit_entity_details_fills_in_registration():
    """`submit_entity_details` — already built for exactly this purpose — can
    later fill in what a bare Lead didn't know at creation. `submit_entity_details`
    itself doesn't accept registration_number/registered_address (those aren't
    part of its own contract), but the record it completes is the very one
    `create_lead` created with them NULL, proving the two paths connect."""
    async with db_services.AsyncSessionLocal() as db:
        request, _profile, _created = await ExporterProfileService(db).create_lead(
            tenant_id=uuid.uuid4(),
            legal_name=f"Later Details Co {uuid.uuid4().hex[:8]}",
            incorporation_country="IN",
            initial_user_email=f"{uuid.uuid4().hex[:8]}@example.com",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
        )
    assert request.status == OnboardingRequestStatus.DRAFT

    async with db_services.AsyncSessionLocal() as db:
        updated = await OnboardingRequestService(
            db, document_requirements=_empty_document_requirements()
        ).submit_entity_details(request.id, trading_name="Later Details Trading Co")

    assert updated.status == OnboardingRequestStatus.ENTITY_VERIFICATION_IN_PROGRESS
    assert updated.trading_name == "Later Details Trading Co"
    # registration_number/registered_address remain NULL: submit_entity_details
    # doesn't set them, and nothing about this path required them.
    assert updated.registration_number is None
    assert updated.registered_address is None


async def test_search_profiles_finds_bare_lead_by_legal_name():
    """`search_profiles`'s `legal_name_contains` join now has something to
    match for every profile, not just ones that went through full onboarding
    — a bare Lead created via `create_lead` is findable by name immediately."""
    legal_name = f"Findable Bare Lead {uuid.uuid4().hex[:8]}"
    async with db_services.AsyncSessionLocal() as db:
        request, profile, _created = await ExporterProfileService(db).create_lead(
            tenant_id=uuid.uuid4(),
            legal_name=legal_name,
            incorporation_country="US",
            initial_user_email=f"{uuid.uuid4().hex[:8]}@example.com",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
        )

    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(
            legal_name_contains=legal_name[5:15]
        )

    assert any(p.customer_id == profile.customer_id == request.customer_id for p in results)


# ── update_profile ────────────────────────────────────────────────────────────


async def test_update_profile_rejects_source_change():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterSourceImmutableError):
            await ExporterProfileService(db).update_profile(
                customer_id, source=ExporterSource.MANUAL
            )


async def test_update_profile_rejects_lifecycle_status_field():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await ExporterProfileService(db).update_profile(
                customer_id, lifecycle_status=ExporterLifecycleStatus.ACTIVE
            )


async def test_update_profile_updates_mutable_fields():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        updated = await ExporterProfileService(db).update_profile(
            customer_id, industry="Textiles", gstin="27AAAPL1234C1ZV"
        )

    assert updated.industry == "Textiles"
    assert updated.gstin == "27AAAPL1234C1ZV"
    assert updated.source == ExporterSource.SALES  # untouched


async def test_update_profile_not_found_raises():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterProfileService(db).update_profile(uuid.uuid4(), industry="X")


# ── search_profiles ────────────────────────────────────────────────────────────


async def test_search_profiles_by_gstin():
    customer_id = uuid.uuid4()
    gstin = f"27AAAPL{uuid.uuid4().hex[:4].upper()}C1ZV"
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, gstin=gstin
        )

    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(gstin=gstin)

    assert len(results) == 1
    assert results[0].customer_id == customer_id


async def test_search_profiles_by_legal_name_contains_case_insensitive():
    legal_name = f"Acme Exports {uuid.uuid4().hex[:8]} Pvt Ltd"
    customer_id = await _create_onboarding_request_for("_", legal_name)

    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    search_fragment = legal_name[5:15].upper()  # deliberately wrong case
    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(
            legal_name_contains=search_fragment
        )

    assert any(p.customer_id == customer_id for p in results)


async def test_search_profiles_by_legal_name_contains_no_match_returns_empty():
    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(
            legal_name_contains=f"NoSuchExporter{uuid.uuid4().hex}"
        )

    assert results == []


# ── transition_lifecycle_status ────────────────────────────────────────────────


async def test_transition_lifecycle_status_valid_transition():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        updated = await ExporterProfileService(db).transition_lifecycle_status(
            customer_id, ExporterLifecycleStatus.CONTACTED, actor_id="agent_1"
        )

    assert updated.lifecycle_status == ExporterLifecycleStatus.CONTACTED


async def test_transition_lifecycle_status_rejects_invalid_transition():
    """The acceptance criterion's own example: LEAD -> ACTIVE directly is
    not a permitted edge, and the raised exception names both statuses."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )
    assert (
        ExporterLifecycleStatus.LEAD,
        ExporterLifecycleStatus.ACTIVE,
    ) not in PERMITTED_LIFECYCLE_TRANSITIONS

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(InvalidExporterLifecycleTransitionError) as exc:
            await ExporterProfileService(db).transition_lifecycle_status(
                customer_id, ExporterLifecycleStatus.ACTIVE, actor_id="agent_1"
            )

    assert "LEAD" in str(exc.value.detail)
    assert "ACTIVE" in str(exc.value.detail)


async def test_transition_lifecycle_status_same_status_rejected():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(InvalidExporterLifecycleTransitionError):
            await ExporterProfileService(db).transition_lifecycle_status(
                customer_id, ExporterLifecycleStatus.LEAD, actor_id="agent_1"
            )


async def test_transition_lifecycle_status_not_found_raises():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterProfileService(db).transition_lifecycle_status(
                uuid.uuid4(), ExporterLifecycleStatus.CONTACTED, actor_id="agent_1"
            )


# ── get_profile_detail ────────────────────────────────────────────────────────


async def test_get_profile_detail_includes_onboarding_history():
    legal_name = f"Detail Test Exporter {uuid.uuid4().hex[:8]}"
    customer_id = await _create_onboarding_request_for("_", legal_name)

    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        detail = await ExporterProfileService(db).get_profile_detail(customer_id)

    assert detail.customer_id == customer_id
    assert len(detail.onboarding_history) == 1
    assert detail.onboarding_history[0].legal_name == legal_name
    assert detail.contacts == ()
    assert detail.recent_activities == ()


async def test_get_profile_detail_not_found_raises():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterProfileService(db).get_profile_detail(uuid.uuid4())
