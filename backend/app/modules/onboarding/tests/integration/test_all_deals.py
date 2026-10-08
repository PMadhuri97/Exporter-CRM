"""The list of every deal, across companies (`GET /onboarding/deals`).

The claims that could fail without anything on screen looking wrong:

* **The corridor is the seller's country, then the buyer's** — from the buyer
  company once the deal names one, and from the older buyer details otherwise. A
  corridor read the wrong way round, or from the wrong buyer, would still look like
  a corridor.
* **An unknown corridor is not dropped.** A deal with no buyer yet, or a party with
  no country, has no corridor; it must still be listed, and `UNKNOWN` must find it.
* **Filters combine.** Every filter narrows; none silently replaces another.
* **The corridor choices ignore the filters**, so a filter's options do not vanish as
  soon as one is applied.

Other tests' deals share this database, so each test narrows by a tag of its own
(`q`) or a company of its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.deal_views import UNKNOWN_CORRIDOR, DealFilters
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.qualification_enums import QualificationOutcomeValue
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import ensure_relationship_manager
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _tag() -> str:
    return f"t{uuid.uuid4().hex[:10]}"


async def _seller(name: str, country: str | None = "IN") -> uuid.UUID:
    """A named prospect: only a prospect or customer may have a deal opened."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name=name, country=country
        )
    await ensure_relationship_manager(customer_id)
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            customer_id, QualificationOutcomeValue.QUALIFIED, actor_id="test"
        )
    return customer_id


async def _buyer_company(name: str, country: str = "NL") -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        return await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=name,
                country=country,
                registration_number=f"REG-{uuid.uuid4().hex[:10].upper()}",
            ),
            actor_id="rm-1",
        )


async def _deal(
    seller: uuid.UUID,
    reference: str,
    *,
    buyer_company: uuid.UUID | None = None,
    legacy_buyer: tuple[str, str] | None = None,
) -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(seller, reference=reference, actor_id="rm-1")
    if buyer_company is not None:
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).set_buyer_company(
                view.id, buyer_company_id=buyer_company, actor_id="rm-1"
            )
    if legacy_buyer is not None:
        name, country = legacy_buyer
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).set_buyer(view.id, name=name, country=country, actor_id="rm-1")
    return view.id


async def _list(**filters) -> tuple[list, int]:
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).list_all(DealFilters(**filters))


# ── Both parties, and the corridor between them ──────────────────────────────


async def test_a_row_names_both_parties_and_the_corridor_from_the_buyer_company():
    tag = _tag()
    seller = await _seller(f"Acme Exports {tag}")
    buyer = await _buyer_company(f"Rotterdam Trading {tag}", country="NL")
    deal_id = await _deal(seller, f"Rotterdam {tag}", buyer_company=buyer)

    rows, total = await _list(search=tag)

    assert total == 1
    [row] = rows
    assert row.id == deal_id
    assert row.seller_company_id == seller
    assert row.seller_name == f"Acme Exports {tag}"
    assert row.buyer_company_id == buyer
    assert row.buyer_name == f"Rotterdam Trading {tag}"
    # Seller first: IN-NL, never NL-IN.
    assert (row.seller_country, row.buyer_country, row.corridor) == ("IN", "NL", "IN-NL")


async def test_an_older_buyer_record_still_gives_the_corridor():
    """A deal whose buyer is still the older set of details is not a company, but it
    has a country, so its corridor is known."""
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    await _deal(seller, f"Dubai {tag}", legacy_buyer=(f"Gulf Foods {tag}", "AE"))

    [row], _total = await _list(search=tag)

    assert row.buyer_company_id is None
    assert row.buyer_name == f"Gulf Foods {tag}"
    assert row.corridor == "IN-AE"


async def test_the_buyer_company_wins_over_older_buyer_details():
    """The company is the authority once the deal names one, as on the deal page."""
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    buyer = await _buyer_company(f"Hamburg Imports {tag}", country="DE")
    deal_id = await _deal(seller, f"Both {tag}", legacy_buyer=(f"Old Name {tag}", "FR"))
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(deal_id, buyer_company_id=buyer, actor_id="rm-1")

    [row], _total = await _list(search=f"Both {tag}")

    assert row.buyer_name == f"Hamburg Imports {tag}"
    assert row.corridor == "IN-DE"


async def test_a_deal_with_no_buyer_has_no_corridor_and_is_still_listed():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    deal_id = await _deal(seller, f"Fresh {tag}")

    [row], _total = await _list(search=tag)

    assert row.id == deal_id
    assert row.buyer_name is None
    assert row.corridor is None


async def test_a_seller_with_no_country_has_no_corridor():
    tag = _tag()
    seller = await _seller(f"Countryless {tag}", country=None)
    buyer = await _buyer_company(f"Buyer {tag}", country="US")
    await _deal(seller, f"Ref {tag}", buyer_company=buyer)

    [row], _total = await _list(search=tag)

    assert row.buyer_country == "US"
    assert row.corridor is None


# ── Filters ──────────────────────────────────────────────────────────────────


async def test_the_corridor_filter_keeps_only_that_corridor():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    to_nl = await _deal(
        seller, f"A {tag}", buyer_company=await _buyer_company(f"NL {tag}", country="NL")
    )
    await _deal(seller, f"B {tag}", buyer_company=await _buyer_company(f"US {tag}", country="US"))
    no_buyer = await _deal(seller, f"C {tag}")

    rows, total = await _list(search=tag, corridors=("IN-NL",))
    assert [row.id for row in rows] == [to_nl] and total == 1

    rows, _total = await _list(search=tag, corridors=(UNKNOWN_CORRIDOR,))
    assert [row.id for row in rows] == [no_buyer]

    rows, _total = await _list(search=tag, corridors=("IN-NL", UNKNOWN_CORRIDOR))
    assert {row.id for row in rows} == {to_nl, no_buyer}


async def test_the_stage_filter():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    kept = await _deal(seller, f"Kept {tag}")
    withdrawn = await _deal(seller, f"Gone {tag}")
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            withdrawn, DealStage.WITHDRAWN, reason="Buyer walked away", actor_id="rm-1"
        )

    rows, _total = await _list(search=tag, stages=(DealStage.WITHDRAWN,))
    assert [row.id for row in rows] == [withdrawn]

    rows, _total = await _list(search=tag, stages=(DealStage.OPEN,))
    assert [row.id for row in rows] == [kept]


async def test_search_matches_reference_seller_and_buyer_in_any_case():
    tag = _tag()
    by_seller = await _deal(await _seller(f"Zephyr {tag} Exports"), "Plain reference")
    by_buyer = await _deal(
        await _seller("Someone"),
        "Another plain one",
        buyer_company=await _buyer_company(f"Quokka {tag} Imports"),
    )
    by_reference = await _deal(await _seller("Someone else"), f"Order {tag.upper()}")

    rows, _total = await _list(search=tag)

    assert {row.id for row in rows} == {by_seller, by_buyer, by_reference}


async def test_search_treats_wildcards_literally():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    await _deal(seller, f"{tag} 100% advance")
    await _deal(seller, f"{tag} 100 advance")

    rows, _total = await _list(search=f"{tag} 100%")

    assert [row.reference for row in rows] == [f"{tag} 100% advance"]


async def test_the_company_filter_matches_either_side():
    tag = _tag()
    company = await _seller(f"Both Sides {tag}")
    sells = await _deal(company, f"Sells {tag}")
    buys = await _deal(await _seller(f"Other {tag}"), f"Buys {tag}", buyer_company=company)
    await _deal(await _seller(f"Unrelated {tag}"), f"Unrelated {tag}")

    rows, total = await _list(company_id=company)

    assert {row.id for row in rows} == {sells, buys}
    assert total == 2


async def test_the_opened_range_is_from_inclusive_to_exclusive():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    deal_id = await _deal(seller, f"Ref {tag}")
    [row], _total = await _list(search=tag)
    opened = row.created_at

    rows, _total = await _list(search=tag, opened_from=opened)
    assert [row.id for row in rows] == [deal_id]
    rows, _total = await _list(search=tag, opened_before=opened)
    assert rows == []
    rows, _total = await _list(
        search=tag, opened_from=opened - timedelta(days=1), opened_before=opened + timedelta(days=1)
    )
    assert [row.id for row in rows] == [deal_id]


async def test_filters_combine_rather_than_replace_each_other():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    nl = await _buyer_company(f"NL {tag}", country="NL")
    match = await _deal(seller, f"Match {tag}", buyer_company=nl)
    wrong_stage = await _deal(seller, f"Stage {tag}", buyer_company=nl)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            wrong_stage, DealStage.WITHDRAWN, reason="No longer needed", actor_id="rm-1"
        )
    await _deal(seller, f"Corridor {tag}", buyer_company=await _buyer_company("US", country="US"))

    rows, _total = await _list(search=tag, corridors=("IN-NL",), stages=(DealStage.OPEN,))

    assert [row.id for row in rows] == [match]


async def test_newest_first_with_a_total_behind_the_page():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    ids = [await _deal(seller, f"{n} {tag}") for n in range(3)]

    async with db_services.AsyncSessionLocal() as db:
        first, total = await DealService(db).list_all(DealFilters(search=tag), limit=2)
        second, _total = await DealService(db).list_all(
            DealFilters(search=tag), limit=2, offset=2
        )

    assert total == 3
    assert [row.id for row in first + second] == list(reversed(ids))


# ── The corridor choices ─────────────────────────────────────────────────────


async def test_the_corridor_choices_count_every_deal_and_put_unknown_last():
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    await _deal(seller, f"A {tag}", buyer_company=await _buyer_company(f"B {tag}", country="JP"))
    await _deal(seller, f"C {tag}")

    async with db_services.AsyncSessionLocal() as db:
        corridors = await DealService(db).corridors()

    values = [c.corridor for c in corridors]
    assert "IN-JP" in values
    assert values[-1] is None
    known = [value for value in values if value is not None]
    assert known == sorted(known)
    assert all(c.deals >= 1 for c in corridors)


# ── Over HTTP ────────────────────────────────────────────────────────────────


async def test_the_route_filters_and_reports_who_may_open_deals(client: AsyncClient):
    tag = _tag()
    seller = await _seller(f"Seller {tag}")
    deal_id = await _deal(
        seller, f"Ref {tag}", buyer_company=await _buyer_company(f"B {tag}", country="SG")
    )
    await _deal(seller, f"Other {tag}")

    token = await token_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(
        f"{BASE}/deals",
        params={"q": tag, "corridor": "IN-SG", "stage": "OPEN"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [row["id"] for row in body["deals"]] == [str(deal_id)]
    assert body["deals"][0]["corridor"] == "IN-SG"
    assert body["deals"][0]["seller_name"] == f"Seller {tag}"
    assert body["total"] == 1
    assert body["can_open_deal"] is True
    # Other tests' deals may be on IN-SG too; the choice is there either way.
    assert any(c["corridor"] == "IN-SG" for c in body["corridors"])

    developer = await token_with_role(client, UserRole.DEVELOPER)
    resp = await client.get(f"{BASE}/deals", params={"q": tag}, headers=auth_header(developer))
    assert resp.status_code == 200
    assert resp.json()["can_open_deal"] is False
    assert resp.json()["total"] == 2


async def test_the_route_reads_a_zoneless_timestamp_as_utc(client: AsyncClient):
    tag = _tag()
    await _deal(await _seller(f"Seller {tag}"), f"Ref {tag}")
    token = await token_with_role(client, UserRole.OPERATIONS)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()

    resp = await client.get(
        f"{BASE}/deals", params={"q": tag, "opened_before": tomorrow}, headers=auth_header(token)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


@pytest.mark.parametrize("corridor", ["in-nl", "IND-NL", "IN_NL", "unknown", ""])
async def test_a_malformed_corridor_is_refused(client: AsyncClient, corridor: str):
    token = await token_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(
        f"{BASE}/deals", params={"corridor": corridor}, headers=auth_header(token)
    )
    assert resp.status_code == 422


# ── The deals between two companies ──────────────────────────────────────────


async def test_the_pair_filter_lists_only_the_deals_between_those_two():
    """The point of the pair: naming both sides answers "what have these two done
    together", which neither side alone and neither `company_id` can ask."""
    acme, globex = await _seller(f"Acme {_tag()}"), await _seller(f"Globex {_tag()}")
    north, south = await _buyer_company(f"North {_tag()}"), await _buyer_company(f"South {_tag()}")

    between = await _deal(acme, f"acme-north {_tag()}", buyer_company=north)
    await _deal(acme, f"acme-south {_tag()}", buyer_company=south)
    await _deal(globex, f"globex-north {_tag()}", buyer_company=north)

    rows, total = await _list(seller_company_id=acme, buyer_company_id=north)
    assert [row.id for row in rows] == [between]
    assert total == 1


async def test_each_side_of_the_pair_also_filters_on_its_own():
    acme = await _seller(f"Acme {_tag()}")
    north, south = await _buyer_company(f"North {_tag()}"), await _buyer_company(f"South {_tag()}")
    sold_to_north = await _deal(acme, f"north {_tag()}", buyer_company=north)
    sold_to_south = await _deal(acme, f"south {_tag()}", buyer_company=south)

    as_seller, _ = await _list(seller_company_id=acme)
    assert {row.id for row in as_seller} == {sold_to_north, sold_to_south}

    as_buyer, _ = await _list(buyer_company_id=north)
    assert sold_to_north in {row.id for row in as_buyer}
    assert sold_to_south not in {row.id for row in as_buyer}


async def test_the_pair_is_directional():
    """Seller and buyer are not interchangeable. Swapping them asks a different
    question, and for one-way trade the answer is nothing."""
    acme = await _seller(f"Acme {_tag()}")
    north = await _buyer_company(f"North {_tag()}")
    await _deal(acme, f"acme-north {_tag()}", buyer_company=north)

    _rows, total = await _list(seller_company_id=north, buyer_company_id=acme)
    assert total == 0


async def test_a_buyer_that_is_not_yet_a_company_cannot_be_half_of_a_pair():
    """A `deal_buyer` row is a name on a deal, not a company. It is still listed and
    still findable by search — it simply has no id to pair with."""
    acme = await _seller(f"Acme {_tag()}")
    reference = f"legacy {_tag()}"
    await _deal(acme, reference, legacy_buyer=("Unmatched Buyer", "NL"))

    by_seller, _ = await _list(seller_company_id=acme)
    assert [row.reference for row in by_seller] == [reference]

    # Nothing is lost: the deal is still reachable by name.
    found, _ = await _list(search="Unmatched Buyer")
    assert reference in {row.reference for row in found}
