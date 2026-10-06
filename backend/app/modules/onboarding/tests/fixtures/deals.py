"""A real deal for a test to point at.

Since migration 0042, ``exporter_profile.created_via_deal_id`` and
``trade_invoice.deal_id`` are foreign keys to ``deal.id``. A test that used to invent
``uuid.uuid4()`` as "the deal this buyer came from" now opens one with this, the way
``companies.py`` replaced invented company ids after 0014.

Opened through ``DealService`` on a qualified seller, because ``open_deal`` refuses a
``LEAD`` — so the deal is one the service could really have produced.
"""

from __future__ import annotations

import uuid

from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.database import services as db_services


async def make_deal(seller: uuid.UUID | None = None) -> uuid.UUID:
    """Open a deal on ``seller`` (a new prospect if none) and return its id."""
    # Imported here, as in `make_prospect`: most tests never need the application layer.
    from app.modules.onboarding.application.deal_service import DealService

    seller = seller or await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Fixture deal {uuid.uuid4().hex[:8]}", actor_id="fixture"
        )
    return view.id


async def make_deal_with_buyer_company(
    seller: uuid.UUID | None = None, buyer_company: uuid.UUID | None = None
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A deal whose buyer is a company — which also gives the pair its trade
    relationship, as naming the buyer company does. Returns
    ``(deal, seller, buyer_company)``."""
    from app.modules.onboarding.application.deal_service import DealService

    seller = seller or await make_prospect()
    buyer_company = buyer_company or await make_company()
    deal_id = await make_deal(seller)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer_company, actor_id="fixture"
        )
    return deal_id, seller, buyer_company


__all__ = ["make_deal", "make_deal_with_buyer_company"]
