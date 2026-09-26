"""Integration tests for EXP-1's `ExporterProfileService`.

Follows `test_s7t1_onboarding_service_api.py`'s conventions: real Postgres, no
per-test rollback, each test opens its own `AsyncSessionLocal()` session(s)
directly. Isolation comes from every test minting its own fresh `customer_id`
(and, where needed, `tenant_id`), never from a shared prefix + wipe fixture.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    ExporterSourceImmutableError,
)
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


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
    assert profile.journey is ExporterJourney.LEAD
    assert profile.qualification is QualificationState.NOT_YET_REVIEWED


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


# ── create_lead ("Add Exporter": a named company) ─────────────────────────────


async def test_create_lead_stores_name_and_country_as_the_company_identity():
    """A named company is created with just a name and a country — no
    contact email is asked for — and reads back with that identity."""
    name = f"Cold Lead Exports {uuid.uuid4().hex[:8]}"
    async with db_services.AsyncSessionLocal() as db:
        profile, created = await ExporterProfileService(db).create_lead(
            name=name,
            country="US",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
        )

    assert created is True
    assert profile.name == name
    assert profile.country == "US"
    assert profile.source == ExporterSource.SALES
    assert profile.journey is ExporterJourney.LEAD
    assert profile.qualification is QualificationState.NOT_YET_REVIEWED

    async with db_services.AsyncSessionLocal() as db:
        detail = await ExporterProfileService(db).get_profile_detail(profile.customer_id)
    assert (detail.name, detail.country) == (name, "US")


async def test_search_profiles_finds_named_company_by_name():
    """A company created with a name is findable by it immediately."""
    name = f"Findable Bare Lead {uuid.uuid4().hex[:8]}"
    async with db_services.AsyncSessionLocal() as db:
        profile, _created = await ExporterProfileService(db).create_lead(
            name=name,
            country="US",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
        )

    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(name_contains=name[5:15])

    match = [p for p in results if p.customer_id == profile.customer_id]
    assert len(match) == 1
    assert (match[0].name, match[0].country) == (name, "US")


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
                customer_id, {"source": ExporterSource.MANUAL}, actor_id="agent_1"
            )


async def test_update_profile_rejects_the_journey_field():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await ExporterProfileService(db).update_profile(
                customer_id,
                {"journey": ExporterJourney.CUSTOMER},
                actor_id="agent_1",
            )


async def test_update_profile_updates_mutable_fields():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        updated = await ExporterProfileService(db).update_profile(
            customer_id,
            {"industry": "Textiles", "gstins": ["27AAAPL1234C1ZV"]},
            actor_id="agent_1",
        )

    assert updated.industry == "Textiles"
    assert updated.gstins == ["27AAAPL1234C1ZV"]
    assert updated.source == ExporterSource.SALES  # untouched


async def test_update_profile_not_found_raises():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterProfileService(db).update_profile(
                uuid.uuid4(), {"industry": "X"}, actor_id="agent_1"
            )


# ── search_profiles ────────────────────────────────────────────────────────────


async def test_search_profiles_by_gstin():
    customer_id = uuid.uuid4()
    # A well-formed GSTIN, unique per run so the exact-match search finds one.
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    gstin = f"27{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}1ZV"
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, gstins=[gstin]
        )

    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(gstin=gstin)

    assert len(results) == 1
    assert results[0].customer_id == customer_id


async def test_search_profiles_by_name_contains_case_insensitive():
    """The name search matches the company's own name, ignoring case."""
    legal_name = f"Acme Exports {uuid.uuid4().hex[:8]} Pvt Ltd"
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name=legal_name, country="US"
        )

    search_fragment = legal_name[5:15].upper()  # deliberately wrong case
    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(
            name_contains=search_fragment
        )

    assert any(p.customer_id == customer_id for p in results)


async def test_search_profiles_by_name_contains_no_match_returns_empty():
    async with db_services.AsyncSessionLocal() as db:
        results = await ExporterProfileService(db).search_profiles(
            name_contains=f"NoSuchExporter{uuid.uuid4().hex}"
        )

    assert results == []


# ── the journey is never moved by hand ────────────────────────────────────────


async def test_the_service_has_no_way_to_move_the_journey_by_hand():
    """L2-04: the ten-status transition is gone. The journey moves only
    through qualification (and, later, the background check)."""
    assert not hasattr(ExporterProfileService, "transition_lifecycle_status")


# ── get_profile_detail ────────────────────────────────────────────────────────


async def test_get_profile_detail_carries_the_company_identity():
    """The detail's name and country come from the company identity. There
    is no onboarding-request history on it any more."""
    legal_name = f"Detail Test Exporter {uuid.uuid4().hex[:8]}"
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name=legal_name, country="us"
        )

    async with db_services.AsyncSessionLocal() as db:
        detail = await ExporterProfileService(db).get_profile_detail(customer_id)

    assert detail.customer_id == customer_id
    assert detail.name == legal_name
    assert detail.country == "US"
    assert not hasattr(detail, "onboarding_history")
    assert detail.contacts == ()
    assert detail.recent_activities == ()


async def test_get_profile_detail_not_found_raises():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await ExporterProfileService(db).get_profile_detail(uuid.uuid4())
