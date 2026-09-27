"""Sample data for deals, buyers and documents — **owner: Developer 3B**
(L3-05 … L3-10).

Called from ``sample_data.py``'s hook, after every sample company exists: a deal
hangs off a company, so this can never run first.

Architecture §3.9 gives company B two deals, one handed over, and company C one
open deal that cannot be handed over because its background check is flagged —
each sample company's target is recorded on ``SampleCompany.target``.

**Two of those three states cannot be reached yet, and this does not fake them.**

* *Handed over* needs assumption A5's guard: the company a ``CUSTOMER`` with a
  ``CLEAR`` background check. ``exporter_profile.background_check`` is Developer
  4's column in migration 0015, which has not landed, so no deal can legitimately
  reach ``HANDED_OVER``. Writing the stage directly would put a row in the
  database that the service would never have produced, with no history row behind
  it — sample data that lies about what the system can do.
* *Cannot be handed over because the check is flagged* is the same column. What
  company C gets instead is a deal that cannot be handed over for the reason that
  is true today: no background check exists.

So this seeder brings each company's deals to the closest **honest** state, and
``docs/dev3b-progress.md`` records the gap. Phase 4 finishes it when 0015 lands.

Converges like every other seeder: it looks at what is there, adds only what is
missing, and reports zero on a repeat run.
"""

from __future__ import annotations

import uuid

import structlog

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)


class _SampleDeal:
    """One deal to bring into being, with its buyer and the stage to leave it at."""

    def __init__(
        self,
        *,
        reference: str,
        buyer_name: str,
        buyer_country: str,
        stage: DealStage = DealStage.OPEN,
        buyer_registration_number: str | None = None,
    ) -> None:
        self.reference = reference
        self.buyer_name = buyer_name
        self.buyer_country = buyer_country
        self.stage = stage
        self.buyer_registration_number = buyer_registration_number


#: Keyed by the sample company's slug, from ``sample_data.COMPANIES``.
SAMPLE_DEALS: dict[str, tuple[_SampleDeal, ...]] = {
    # §3.9 company B: two deals. The second is the one §3.9 calls "handed over";
    # it stops at GATHERING_PAPERWORK with its buyer recorded, which is as far as
    # the guard allows today — see the module docstring.
    "company-b": (
        _SampleDeal(
            reference="Rotterdam shipment, March",
            buyer_name="Rotterdam Trading BV",
            buyer_country="NL",
            buyer_registration_number="NL-8899-221",
            stage=DealStage.GATHERING_PAPERWORK,
        ),
        _SampleDeal(
            reference="Hamburg order, April",
            buyer_name="Hanseatic Industrie GmbH",
            buyer_country="DE",
            buyer_registration_number="HRB-77321",
            stage=DealStage.GATHERING_PAPERWORK,
        ),
    ),
    # §3.9 company C: one open deal that cannot be handed over.
    "company-c": (
        _SampleDeal(
            reference="Dubai seafood order",
            buyer_name="Gulf Fresh Foods LLC",
            buyer_country="AE",
            stage=DealStage.OPEN,
        ),
    ),
}


async def load_deal_sample_data() -> int:
    """Bring each sample company's deals to their §3.9 state.

    Returns the number of deals this run created — ``0`` on a repeat run.
    """
    # Imported here rather than at module scope: `sample_data` imports this
    # module, so a module-scope import back into it would be a cycle.
    from app.modules.onboarding.sample_data import COMPANIES

    slugs = {company.slug: company.customer_id for company in COMPANIES}
    created = 0

    for slug, deals in SAMPLE_DEALS.items():
        company_id = slugs.get(slug)
        if company_id is None:  # pragma: no cover - a renamed sample company
            logger.warning("sample_deals.company_missing", slug=slug)
            continue
        for deal in deals:
            if await _ensure_deal(company_id, deal):
                created += 1

    return created


async def _ensure_deal(company_id: uuid.UUID, sample: _SampleDeal) -> bool:
    """Create one deal, its buyer and its stage, unless a deal with that
    reference is already there."""
    async with db_services.AsyncSessionLocal() as db:
        existing, _ = await DealService(db).list_for_company(company_id, limit=200)
    if any(view.reference == sample.reference for view in existing):
        return False

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            company_id, reference=sample.reference, actor_id=None
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(
            view.id,
            name=sample.buyer_name,
            country=sample.buyer_country,
            registration_number=sample.buyer_registration_number,
            actor_id=None,
        )
    if sample.stage is not DealStage.OPEN:
        async with db_services.AsyncSessionLocal() as db:
            await DealService(db).transition_stage(
                view.id, sample.stage, actor_id=None
            )

    logger.info(
        "sample_deals.created",
        company_id=str(company_id),
        deal_id=str(view.id),
        reference=sample.reference,
        stage=sample.stage.value,
    )
    return True


__all__ = ["load_deal_sample_data"]
