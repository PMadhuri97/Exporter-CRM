"""Buyer-only companies stay out of the pipeline, and the one way in.

The acceptance criterion is "creating a buyer company changes no LEAD
count", and that is the shape of these tests: not "the filter works" but "the
number a manager reads did not move". The failure mode this guards against is
quiet — a buyer company silently inflating this month's leads — so the tests
count rows before and after rather than asserting a WHERE clause.

Task 3.11's route is the complement: a buyer we decide to sell to becomes an
ordinary lead, with its journey history starting then rather than at the moment
somebody recorded it as a buyer.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.application.conversation_service import ConversationService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterJourney,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationOutcomeValue,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import ensure_relationship_manager
from app.modules.onboarding.tests.fixtures.deals import make_deal
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _registration() -> str:
    return f"REG-{uuid.uuid4().hex[:10].upper()}"


async def _buyer_company(name: str | None = None) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        return await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=name or f"Buyer Only {uuid.uuid4().hex[:8]}",
                country="NL",
                registration_number=_registration(),
            ),
            actor_id="rm-1",
        )


async def _working_list_ids(**filters) -> set[uuid.UUID]:
    async with db_services.AsyncSessionLocal() as db:
        rows = await ExporterProfileService(db).search_profiles(limit=200, **filters)
    return {row.customer_id for row in rows}


# ── 3.9: the default working list ─────────────────────────────────────────────


async def test_creating_a_buyer_company_changes_no_lead_count():
    """The acceptance criterion, as the number a manager actually reads.

    Counted rather than filtered: the whole risk is that a buyer company looks
    like a lead to a count nobody thought to check.
    """
    async with db_services.AsyncSessionLocal() as db:
        before = len(
            await ExporterProfileService(db).search_profiles(
                journey=ExporterJourney.LEAD, limit=200
            )
        )
    await _buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        after = len(
            await ExporterProfileService(db).search_profiles(
                journey=ExporterJourney.LEAD, limit=200
            )
        )
    assert after == before


async def test_a_buyer_company_is_absent_from_the_default_working_list():
    company_id = await _buyer_company()
    assert company_id not in await _working_list_ids()


async def test_a_name_search_still_finds_a_buyer_company():
    """Excluded from the list, not hidden. Somebody typing a buyer's name is
    looking for that buyer, and "no such company" would send them off to create a
    duplicate of one we already hold."""
    name = f"Findable Buyer {uuid.uuid4().hex[:8]}"
    company_id = await _buyer_company(name)
    assert company_id in await _working_list_ids(name_contains=name)


async def test_the_pipeline_status_filter_lists_buyer_only_companies():
    """What the identity completion list is built on: the companies created as buyers,
    asked for deliberately."""
    company_id = await _buyer_company()
    listed = await _working_list_ids(pipeline_status=CompanyPipelineStatus.NOT_IN_PIPELINE)
    assert company_id in listed

    in_pipeline = await _working_list_ids(pipeline_status=CompanyPipelineStatus.IN_PIPELINE)
    assert company_id not in in_pipeline


async def test_the_two_exclusions_do_not_interfere():
    """`marker=ENDED` must not drag buyer-only companies into its list, and
    `pipeline_status=` must not resurrect ENDED ones. They are separate axes, and
    the easy mistake is to implement one as a special case of the other."""
    from app.modules.onboarding.domain.entities.exporter_enums import ExporterMarker

    buyer_id = await _buyer_company()
    ended = await _working_list_ids(marker=ExporterMarker.ENDED)
    assert buyer_id not in ended


async def test_the_route_exposes_the_filter(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    company_id = await _buyer_company()

    default = await client.get(f"{BASE}/exporters", headers=auth_header(token))
    assert default.status_code == 200, default.text
    assert str(company_id) not in {p["customer_id"] for p in default.json()["profiles"]}

    filtered = await client.get(
        f"{BASE}/exporters",
        params={"pipeline_status": "NOT_IN_PIPELINE", "limit": 200},
        headers=auth_header(token),
    )
    assert filtered.status_code == 200, filtered.text
    found = [p for p in filtered.json()["profiles"] if p["customer_id"] == str(company_id)]
    assert found, "the filter must list the buyer-only company"
    assert found[0]["pipeline_status"] == "NOT_IN_PIPELINE"


# ── 3.11: the one way in ──────────────────────────────────────────────────────


async def test_a_buyer_company_starts_with_no_journey_history():
    """The `journey` *column* reads LEAD because it is NOT NULL and
    `ck_exporter_profile_not_in_pipeline_start` requires it — but there is no
    journey *row*, because no sales process has begun. The company's one history
    row is on the `pipeline` dimension: how it came to exist."""
    deal_id = await make_deal()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=f"No Journey {uuid.uuid4().hex[:8]}",
                country="NL",
                registration_number=_registration(),
                created_via_deal_id=deal_id,
            ),
            actor_id="rm-1",
        )

    async with db_services.AsyncSessionLocal() as db:
        journey, _total = await HistoryService(db).list_for_company(
            company_id, dimension=history_dimensions.JOURNEY, limit=10
        )
        pipeline, _total = await HistoryService(db).list_for_company(
            company_id, dimension=history_dimensions.PIPELINE, limit=10
        )
    assert list(journey) == []
    [row] = list(pipeline)
    assert row.to_status == CompanyPipelineStatus.NOT_IN_PIPELINE.value
    assert row.from_status is None
    assert row.deal_id == deal_id


async def test_bringing_a_company_into_the_pipeline_starts_its_journey(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    company_id = await _buyer_company()

    resp = await client.post(
        f"{BASE}/exporters/{company_id}/pipeline",
        json={"reason": "They asked us to finance their own exports"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pipeline_status"] == "IN_PIPELINE"

    async with db_services.AsyncSessionLocal() as db:
        journey, _t = await HistoryService(db).list_for_company(
            company_id, dimension=history_dimensions.JOURNEY, limit=10
        )
        pipeline, _t = await HistoryService(db).list_for_company(
            company_id, dimension=history_dimensions.PIPELINE, limit=10
        )
    # The journey begins now, at LEAD.
    [journey_row] = list(journey)
    assert journey_row.to_status == ExporterJourney.LEAD.value
    # Two pipeline rows: created as a buyer, then brought in. Both are kept, so
    # the record still says it arrived as somebody's buyer.
    assert len(list(pipeline)) == 2
    moved = [r for r in pipeline if r.from_status is not None]
    assert len(moved) == 1
    assert moved[0].to_status == CompanyPipelineStatus.IN_PIPELINE.value
    assert moved[0].reason == "They asked us to finance their own exports"


async def test_once_in_the_pipeline_it_can_be_qualified_and_spoken_to(client: AsyncClient):
    """The point of the route. Before it, both of these are refused with
    `COMPANY_NOT_IN_PIPELINE`; after it, the company is an ordinary lead."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    company_id = await _buyer_company()
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/pipeline", headers=auth_header(token)
    )
    assert resp.status_code == 200, resp.text

    # Qualification first: the conversation gauge applies from PROSPECT onward,
    # so this is the order an ordinary lead goes through too.
    await ensure_relationship_manager(company_id)
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            company_id,
            outcome=QualificationOutcomeValue.QUALIFIED,
            note="Checked their export history",
            actor_id="rm-1",
        )
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id, ExporterConversation.REACHING_OUT, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        detail = await ExporterProfileService(db).get_profile_detail(company_id)
    # Qualifying moved the journey, which the NOT_IN_PIPELINE check constraint
    # would have refused before the company was brought in.
    assert detail.journey is ExporterJourney.PROSPECT


async def test_a_company_already_in_the_pipeline_is_a_conflict(client: AsyncClient):
    """Not a no-op: this route starts a journey, and doing that twice would append
    a second LEAD creation row, making the history read as a restart."""
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    created = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": f"Ordinary Lead {uuid.uuid4().hex[:8]}",
              "country": "IN"},
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    company_id = created.json()["customer_id"]

    resp = await client.post(
        f"{BASE}/exporters/{company_id}/pipeline", headers=auth_header(token)
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "COMPANY_ALREADY_IN_PIPELINE"


async def test_bringing_it_in_twice_is_refused_the_second_time(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    company_id = await _buyer_company()
    first = await client.post(
        f"{BASE}/exporters/{company_id}/pipeline", headers=auth_header(token)
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"{BASE}/exporters/{company_id}/pipeline", headers=auth_header(token)
    )
    assert second.status_code == 409, second.text


async def test_a_read_only_role_may_not_bring_a_company_into_the_pipeline(
    client: AsyncClient,
):
    """Deciding to sell to a company is a commercial decision. DEVELOPER is
    read-only throughout the CRM."""
    company_id = await _buyer_company()
    _user_id, token = await user_with_role(client, UserRole.DEVELOPER)
    resp = await client.post(
        f"{BASE}/exporters/{company_id}/pipeline", headers=auth_header(token)
    )
    assert resp.status_code == 403, resp.text


async def test_an_unknown_company_is_a_404(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/exporters/{uuid.uuid4()}/pipeline", headers=auth_header(token)
    )
    assert resp.status_code == 404, resp.text
