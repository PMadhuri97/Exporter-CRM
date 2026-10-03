"""A company's deals on the buyer side — task 2.7 (**owner: Developer 2**, plan P4-8).

Three claims, each of which could fail silently:

* **The two sides are separate lists.** The easy bug is a buyer-side request that
  quietly returns the seller's deals: the right heading over the wrong rows, which
  nothing on screen would contradict.
* **A row names the other party.** On the buyer side ``buyer_name`` carries the
  *seller's* name. Repeating the company whose page it is would be useless, and
  showing the buyer's own name there would look correct while being meaningless.
* **A buyer company's timeline includes its deals.** History rows are keyed to the
  selling company, so without widening the query a buyer-only company's timeline is
  empty but for the row saying it was created — and decision D8's exclusions must
  still apply to the rows that arrive this way.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


async def _named_seller(name: str) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name=name, country="IN"
        )
    # Only a PROSPECT may have a deal opened on it.
    from app.modules.onboarding.application.qualification_service import QualificationService
    from app.modules.onboarding.domain.entities.qualification_enums import (
        QualificationOutcomeValue,
    )

    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            customer_id, QualificationOutcomeValue.QUALIFIED, actor_id="test"
        )
    return customer_id


async def _deal_with_buyer_company(
    *, seller: uuid.UUID, buyer: uuid.UUID
) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            view.id, buyer_company_id=buyer, actor_id="rm-1"
        )
    return view.id


async def _buyer_only_company(name: str) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        return await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=name,
                country="NL",
                registration_number=f"REG-{uuid.uuid4().hex[:10].upper()}",
            ),
            actor_id="rm-1",
        )


# ── Two sides, two lists ──────────────────────────────────────────────────────


async def test_the_buyer_side_lists_the_deals_this_company_buys_on():
    seller = await _named_seller(f"Acme Exports {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"Rotterdam Trading {uuid.uuid4().hex[:8]}")
    deal_id = await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        bought, total = await DealService(db).list_for_company(buyer, as_buyer=True)
    assert [view.id for view in bought] == [deal_id]
    assert total == 1


async def test_the_buyer_side_is_not_the_seller_side():
    """The bug this guards against: the buyer request returning the seller's deals.
    A company that sells on one deal and buys on another must see one of each."""
    company = await _named_seller(f"Both Sides {uuid.uuid4().hex[:8]}")
    other = await _named_seller(f"Counterparty {uuid.uuid4().hex[:8]}")

    # It sells on this one.
    async with db_services.AsyncSessionLocal() as db:
        sells_on = await DealService(db).open_deal(
            company, reference=f"Sells {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    # And buys on this one.
    buys_on = await _deal_with_buyer_company(seller=other, buyer=company)

    async with db_services.AsyncSessionLocal() as db:
        as_seller, _t = await DealService(db).list_for_company(company)
        as_buyer, _t = await DealService(db).list_for_company(company, as_buyer=True)

    assert [v.id for v in as_seller] == [sells_on.id]
    assert [v.id for v in as_buyer] == [buys_on]


async def test_a_legacy_deal_buyer_never_appears_on_the_buyer_side():
    """A `deal_buyer` row is a set of details, not a company, so there is nothing to
    match it to a company by. Such a deal appears here only once the buyer migration
    has linked it — which is correct, not a gap: until then nothing in the database
    says that buyer *is* this company."""
    seller = await make_prospect()
    buyer_company = await _buyer_only_company(f"Legacy Buyer {uuid.uuid4().hex[:8]}")

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Legacy {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id, name="Legacy Buyer", country="NL", actor_id="rm-1"
        )

    async with db_services.AsyncSessionLocal() as db:
        bought, total = await DealService(db).list_for_company(
            buyer_company, as_buyer=True
        )
    assert list(bought) == []
    assert total == 0


async def test_the_buyer_side_names_the_seller_not_the_company_itself():
    seller_name = f"Acme Exports {uuid.uuid4().hex[:8]}"
    seller = await _named_seller(seller_name)
    buyer_name = f"Rotterdam Trading {uuid.uuid4().hex[:8]}"
    buyer = await _buyer_only_company(buyer_name)
    await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        [row], _total = await DealService(db).list_for_company(buyer, as_buyer=True)
    # "The other party on this deal", which on this side is the seller.
    assert row.buyer_name == seller_name
    assert row.buyer_name != buyer_name


async def test_stage_filters_still_apply_on_the_buyer_side():
    seller = await _named_seller(f"Staged Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"Staged Buyer {uuid.uuid4().hex[:8]}")
    deal_id = await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        open_deals, _t = await DealService(db).list_for_company(
            buyer, as_buyer=True, stages=(DealStage.OPEN,)
        )
        gathering, _t = await DealService(db).list_for_company(
            buyer, as_buyer=True, stages=(DealStage.GATHERING_PAPERWORK,)
        )
    assert [v.id for v in open_deals] == [deal_id]
    assert list(gathering) == []


# ── Through the route ─────────────────────────────────────────────────────────


async def test_the_route_takes_as_buyer(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    seller = await _named_seller(f"Route Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"Route Buyer {uuid.uuid4().hex[:8]}")
    deal_id = await _deal_with_buyer_company(seller=seller, buyer=buyer)

    bought = await client.get(
        f"{BASE}/exporters/{buyer}/deals", params={"as": "buyer"}, headers=auth_header(token)
    )
    assert bought.status_code == 200, bought.text
    assert [d["id"] for d in bought.json()["deals"]] == [str(deal_id)]

    # The same company, as a seller: it sells on nothing.
    sold = await client.get(f"{BASE}/exporters/{buyer}/deals", headers=auth_header(token))
    assert sold.status_code == 200, sold.text
    assert sold.json()["deals"] == []


async def test_the_default_side_is_the_seller(client: AsyncClient):
    """Omitting `as` must behave exactly as before this task: every existing caller
    depends on it."""
    token = await token_with_role(client, UserRole.OPERATIONS)
    seller = await _named_seller(f"Default Seller {uuid.uuid4().hex[:8]}")
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Default {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )

    resp = await client.get(f"{BASE}/exporters/{seller}/deals", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    assert [d["id"] for d in resp.json()["deals"]] == [str(view.id)]


async def test_an_unknown_side_is_refused(client: AsyncClient):
    token = await token_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(
        f"{BASE}/exporters/{uuid.uuid4()}/deals",
        params={"as": "guarantor"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


# ── The buyer company's timeline ──────────────────────────────────────────────


async def test_a_buyer_companys_history_includes_the_deals_it_buys_on():
    """Deal history rows are keyed to the selling company, so without widening the
    query this company's timeline would show nothing of a deal it is a party to."""
    seller = await _named_seller(f"History Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"History Buyer {uuid.uuid4().hex[:8]}")
    deal_id = await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        rows, total = await HistoryService(db).list_for_company(buyer, limit=50)
    deal_rows = [row for row in rows if row.deal_id == deal_id]
    assert deal_rows, "the buyer's timeline must carry its deal's rows"
    assert total == len(rows)

    # Its own creation row is still there: the widening adds, never replaces.
    assert any(
        row.dimension == history_dimensions.PIPELINE and row.deal_id is None for row in rows
    )


async def test_the_total_matches_the_page_on_a_widened_timeline():
    """The count and the page use one predicate. If they disagreed, the screen would
    offer a next page that does not exist — or hide rows it just counted."""
    seller = await _named_seller(f"Total Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"Total Buyer {uuid.uuid4().hex[:8]}")
    await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        rows, total = await HistoryService(db).list_for_company(buyer, limit=200)
    assert total == len(rows)


async def test_a_sellers_timeline_is_unchanged_by_the_widening():
    """The seller already saw its deal's rows through `customer_id`; the widening
    must not duplicate them."""
    seller = await _named_seller(f"Unchanged Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"Unchanged Buyer {uuid.uuid4().hex[:8]}")
    deal_id = await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(seller, limit=200)
    ids = [row.id for row in rows if row.deal_id == deal_id]
    assert len(ids) == len(set(ids)), "a row must not appear twice"


async def test_d8_exclusions_still_apply_to_rows_reached_through_a_deal():
    """A dimension DEVELOPER may not see on its own company must not become readable
    by arriving through a deal. `exclude_dimensions` is applied to both halves of the
    predicate, and this is the test that says so."""
    seller = await _named_seller(f"D8 Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"D8 Buyer {uuid.uuid4().hex[:8]}")
    await _deal_with_buyer_company(seller=seller, buyer=buyer)

    async with db_services.AsyncSessionLocal() as db:
        with_deals, _t = await HistoryService(db).list_for_company(buyer, limit=200)
        without_deals, _t = await HistoryService(db).list_for_company(
            buyer, exclude_dimensions=[history_dimensions.DEAL], limit=200
        )
    assert any(row.dimension == history_dimensions.DEAL for row in with_deals)
    assert all(row.dimension != history_dimensions.DEAL for row in without_deals)


async def test_an_ordinary_company_with_no_purchases_sees_only_its_own_history():
    company = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(company, limit=50)
    assert all(row.customer_id == company for row in rows)


async def test_the_sellers_own_gauge_rows_do_not_leak_onto_the_buyers_timeline():
    """The subtlety in the widening, pinned down.

    A ``conversation`` row carries a ``deal_id`` when seam S1 moves a seller to
    ``READY_NOW`` on opening a deal — and a ``verification`` row carries one for a
    check run in a deal's context. Both are about the **seller's** own state and
    merely mention the deal. An earlier version of this widening admitted every row
    carrying the id, which put the seller's conversation gauge on the buyer's
    timeline, where it reads as the buyer's own conversation.

    So the buyer side admits the ``deal`` dimension and nothing else; the buyer's own
    rows, its own checks included, arrive through ``customer_id`` as they always did.
    """
    seller = await _named_seller(f"Leak Seller {uuid.uuid4().hex[:8]}")
    buyer = await _buyer_only_company(f"Leak Buyer {uuid.uuid4().hex[:8]}")
    deal_id = await _deal_with_buyer_company(seller=seller, buyer=buyer)

    # Opening the deal moved the seller's conversation to READY_NOW (seam S1), and
    # that row carries this deal's id.
    async with db_services.AsyncSessionLocal() as db:
        seller_conversation, _t = await HistoryService(db).list_for_company(
            seller, dimension=history_dimensions.CONVERSATION, limit=50
        )
    assert any(row.deal_id == deal_id for row in seller_conversation), (
        "this test needs a conversation row carrying the deal id to be meaningful"
    )

    async with db_services.AsyncSessionLocal() as db:
        buyer_conversation, total = await HistoryService(db).list_for_company(
            buyer, dimension=history_dimensions.CONVERSATION, limit=50
        )
    # The buyer has no conversation of its own — it is not in the pipeline — and the
    # seller's must not appear here.
    assert list(buyer_conversation) == []
    assert total == 0

    # The deal itself still does appear, which is the point of the widening.
    async with db_services.AsyncSessionLocal() as db:
        buyer_deals, _t = await HistoryService(db).list_for_company(
            buyer, dimension=history_dimensions.DEAL, limit=50
        )
    assert any(row.deal_id == deal_id for row in buyer_deals)
