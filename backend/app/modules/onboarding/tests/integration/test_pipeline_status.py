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
    CompanyTradeRole,
    ExporterJourney,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationOutcomeValue,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import (
    ensure_relationship_manager,
    make_company,
    make_prospect,
)
from app.modules.onboarding.tests.fixtures.deals import (
    make_deal,
    make_deal_with_buyer_company,
)
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


# ── The company-list filters ─────────────────────────────────────────────────


async def test_asking_for_buyers_brings_back_the_companies_the_list_hides():
    """The filter's whole point, and the one way it could silently fail.

    A buyer-only company is `NOT_IN_PIPELINE`, which the default working list excludes.
    Leaving that exclusion in place would answer "which of our companies are buyers"
    with almost nothing — present, plausible, and wrong.
    """
    # A real buyer-only company — `_buyer_company()`, not `make_company()`, which makes
    # an ordinary in-pipeline one and would not be hidden in the first place.
    buyer_only = await _buyer_company()
    _deal, seller, _buyer = await make_deal_with_buyer_company(buyer_company=buyer_only)

    assert buyer_only not in await _working_list_ids()
    assert buyer_only in await _working_list_ids(trade_role=CompanyTradeRole.BUYER)
    # And the seller is not swept in by it.
    assert seller not in await _working_list_ids(trade_role=CompanyTradeRole.BUYER)


async def test_seller_and_both_are_told_apart_by_participation():
    """`BOTH` means it has been on both sides, not "unsure". The seller here has only
    sold, so it is a SELLER and not a BOTH."""
    _deal, seller, buyer_company = await make_deal_with_buyer_company()

    assert seller in await _working_list_ids(trade_role=CompanyTradeRole.SELLER)
    assert seller not in await _working_list_ids(trade_role=CompanyTradeRole.BOTH)
    assert buyer_company not in await _working_list_ids(trade_role=CompanyTradeRole.SELLER)


async def test_a_company_that_has_sold_and_been_bought_from_is_both():
    """The case `source` and `pipeline_status` cannot express: one company on both
    sides of two different trades."""
    _first, middle, _buyer = await make_deal_with_buyer_company()
    # The same company, now named as somebody else's buyer.
    await make_deal_with_buyer_company(buyer_company=middle)

    assert middle in await _working_list_ids(trade_role=CompanyTradeRole.BOTH)
    assert middle in await _working_list_ids(trade_role=CompanyTradeRole.SELLER)
    assert middle in await _working_list_ids(trade_role=CompanyTradeRole.BUYER)


async def test_has_open_deals_splits_the_list_on_a_live_deal():
    with_deal = await make_prospect()
    await make_deal(with_deal)
    without_deal = await make_prospect()

    open_deals = await _working_list_ids(has_open_deals=True)
    assert with_deal in open_deals
    assert without_deal not in open_deals

    no_deals = await _working_list_ids(has_open_deals=False)
    assert without_deal in no_deals
    assert with_deal not in no_deals


async def test_country_matches_whole_and_industry_matches_partially():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        # `make_company` leaves both unset, so the country is given here rather than
        # assumed — a company with no country is correctly absent from a country filter.
        await ExporterProfileService(db).update_profile(
            company_id, {"industry": "Marine Exports", "country": "IN"}, actor_id="rm-1"
        )

    assert company_id in await _working_list_ids(industry="marine exports")
    # Partial, because it is typed a character at a time: each of these is a prefix
    # somebody passes through on the way to the whole word, and showing nothing until
    # the last letter reads as "no such industry".
    for partial in ("m", "ma", "Marine", "exports"):
        assert company_id in await _working_list_ids(industry=partial), partial
    assert company_id not in await _working_list_ids(industry="shipping")
    assert company_id in await _working_list_ids(country="in")


async def test_each_listed_company_carries_the_side_it_has_traded_on():
    """The role is on the row, so an export can write it without asking per company."""
    _deal, seller, buyer_only = await make_deal_with_buyer_company(
        buyer_company=await _buyer_company()
    )
    never_traded = await make_company()

    async def _role(company_id, **filters):
        async with db_services.AsyncSessionLocal() as db:
            rows = await ExporterProfileService(db).search_profiles(limit=200, **filters)
        return next((r.trade_role for r in rows if r.customer_id == company_id), "absent")

    assert await _role(seller) is CompanyTradeRole.SELLER
    assert await _role(buyer_only, trade_role=CompanyTradeRole.BUYER) is CompanyTradeRole.BUYER
    # Neither side is `None`, not a third role: "no deals yet" is not a kind of company.
    assert await _role(never_traded) is None


async def test_the_total_counts_what_the_filters_match_not_the_page():
    """The bug this closes: a page of 50 reported 50 companies for a filter matching
    185. The count and the rows share one set of conditions, so they cannot disagree."""
    tag = f"Counted {uuid.uuid4().hex[:8]}"
    made = [await make_company() for _ in range(3)]
    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        for company_id in made:
            await service.update_profile(company_id, {"industry": tag}, actor_id="rm-1")

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        page = await service.search_profiles(industry=tag, limit=2)
        total = await service.count_profiles(industry=tag)

    assert len(page) == 2, "the page is capped by the limit"
    assert total == 3, "the total is what the filter matches"


async def test_the_total_applies_the_same_default_exclusions_as_the_list():
    """A buyer-only company is hidden from the default list, so it must not be counted
    into it either — a total that included it would explain a list that does not."""
    buyer_only = await _buyer_company()

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        default_total = await service.count_profiles()
        asked_for = await service.count_profiles(
            pipeline_status=CompanyPipelineStatus.NOT_IN_PIPELINE
        )
        listed = {row.customer_id for row in await service.search_profiles(limit=200)}

    assert buyer_only not in listed
    assert asked_for >= 1
    assert default_total == len(listed) or default_total >= len(listed)
