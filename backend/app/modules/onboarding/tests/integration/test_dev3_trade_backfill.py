"""The trade relationship backfill — task 3.23 (**owner: Developer 3**, plan P5-5).

The claims worth testing, as opposed to restating the SQL:

* **One relationship per pair, not per deal.** Two deals between the same two
  companies must not produce two relationships, and the report must count pairs —
  otherwise the operator reads a number that is not what will be written.
* **Idempotent.** A second run writes nothing. This is what makes a run that was
  interrupted safe to repeat, and it comes free from ``get_or_create_relationship``
  rather than from a mapping table, so it is worth proving rather than assuming.
* **A self-dealing deal is refused and reported, never skipped silently.** Those rows
  are wrong in the data and the operator has to see them; the buyer migration names
  the same ones.
* **It writes nothing but relationships** — no invoices and no history. A deal having
  had a buyer is not evidence that money moved.
* **A mostly unmigrated database says so.** Running this before the buyer migration
  (P4-6) is the one sequencing mistake available here, and the report calls it.

Every test narrows ``resolve`` to its own deals with ``only_deals``: this database is
shared and holds other suites' deals, so a report about all of them would say nothing
about the rows a test created.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.trade_history_service import (
    SOURCE_BACKFILL,
    SOURCE_DEAL_BUYER_RECORDED,
    TradeHistoryService,
)
from app.modules.onboarding.backfill_trade_relationships import (
    Pair,
    Report,
    apply,
    report_run,
    resolve,
    validate,
)
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.trade_enums import (
    TradePaymentStatus,
    TradeProofStatus,
)
from app.modules.onboarding.domain.entities.trade_invoice import TradeInvoice
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


async def _migrated_deal(seller: uuid.UUID, buyer: uuid.UUID) -> uuid.UUID:
    """A deal linked **the way the buyer migration links one**: a direct
    ``UPDATE … SET buyer_company_id``, which is what this backfill exists for.

    `set_buyer_company` would create the relationship itself (task 3.18's acceptance
    criterion — "every deal with a buyer company has a relationship", in the same
    transaction), so a deal recorded through the service needs no backfill and this
    helper would test nothing. P4-6 writes the column with SQL, so the deals it links
    arrive without a relationship. Those are the rows.
    """
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Backfill {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
        # NULL → a value, which is all set-once allows and all the migration does.
        await db.execute(
            Deal.__table__.update()
            .where(Deal.id == view.id)
            .values(buyer_company_id=buyer)
        )
        await db.commit()
    return view.id


async def _relationships(seller: uuid.UUID, buyer: uuid.UUID) -> list[TradeRelationship]:
    async with db_services.AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(TradeRelationship).where(
                    TradeRelationship.seller_company_id == seller,
                    TradeRelationship.buyer_company_id == buyer,
                )
            )
        )


async def _resolve_only(*deal_ids: uuid.UUID) -> Report:
    async with db_services.AsyncSessionLocal() as db:
        return await resolve(db, only_deals=set(deal_ids))


async def _apply_only(report: Report, *, run_id: str) -> dict[str, int]:
    async with db_services.AsyncSessionLocal() as db:
        return await apply(db, report, run_id=run_id, actor_id="backfill-operator")


# ── What a run does ───────────────────────────────────────────────────────────


async def test_a_dry_run_names_the_pairs_and_writes_nothing():
    seller = await make_prospect()
    buyer = await make_company()
    deal_id = await _migrated_deal(seller, buyer)

    report = await _resolve_only(deal_id)
    assert report.deals_with_a_buyer_company == 1
    assert [p.buyer_company_id for p in report.to_create] == [buyer]
    assert not report.already_there

    rendered = report.render()
    assert "relationships to create:    1" in rendered
    assert " → " in rendered  # the pair reads as a pair, not as two uuids

    # A dry run is a read: `resolve` wrote nothing.
    assert await _relationships(seller, buyer) == []


async def test_two_deals_between_the_same_pair_make_one_relationship():
    """The report counts **pairs**. A per-deal count would promise two relationships
    and `uq_trade_relationship_pair` would deliver one, so the operator's number has
    to be the pair count."""
    seller = await make_prospect()
    buyer = await make_company()
    first = await _migrated_deal(seller, buyer)
    second = await _migrated_deal(seller, buyer)

    report = await _resolve_only(first, second)
    assert report.deals_with_a_buyer_company == 2
    assert len(report.pairs) == 1
    assert set(report.pairs[0].deal_ids) == {first, second}
    assert "2 deals" in report.pairs[0].label()

    counts = await _apply_only(report, run_id="test-backfill-pair")
    assert counts == {"created": 1, "already_there": 0, "refused": 0}
    [relationship] = await _relationships(seller, buyer)
    assert relationship.source == SOURCE_BACKFILL
    assert relationship.source_ref == "test-backfill-pair"


async def test_a_second_run_writes_nothing():
    """What makes an interrupted run safe to repeat. There is no mapping table here —
    the pair's uniqueness is the record of what was done — so this is the only thing
    standing between the operator and a duplicate."""
    seller = await make_prospect()
    buyer = await make_company()
    deal_id = await _migrated_deal(seller, buyer)

    first = await _apply_only(await _resolve_only(deal_id), run_id="test-backfill-1")
    assert first["created"] == 1

    second_report = await _resolve_only(deal_id)
    assert second_report.to_create == []
    assert len(second_report.already_there) == 1
    second = await _apply_only(second_report, run_id="test-backfill-2")
    assert second == {"created": 0, "already_there": 1, "refused": 0}

    [relationship] = await _relationships(seller, buyer)
    # Still the first run's row: nothing was rewritten, and the second run id does
    # not appear anywhere.
    assert relationship.source_ref == "test-backfill-1"


async def test_a_relationship_the_deal_path_already_created_is_left_alone():
    """A deal recorded through the service already has its relationship, created with
    ``source='deal_buyer_recorded'`` in the same transaction. Two things are proved at
    once: that such a deal needs no backfill, and that the backfill does not restamp
    it — BQ-7's ``source`` is how anyone later tells where a row came from.
    """
    seller = await make_prospect()
    buyer = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Recorded {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
        await DealService(db).set_buyer_company(
            view.id, buyer_company_id=buyer, actor_id="rm-1"
        )
    deal_id = view.id

    report = await _resolve_only(deal_id)
    assert report.to_create == []
    counts = await _apply_only(report, run_id="test-backfill-existing")
    assert counts["created"] == 0

    [relationship] = await _relationships(seller, buyer)
    assert relationship.source == SOURCE_DEAL_BUYER_RECORDED


async def test_a_withdrawn_deal_still_gets_its_relationship():
    """P5-5's wording — every deal with a buyer company — and the right reading: a
    relationship is "these two have dealt with each other", not "these two completed a
    trade". What happened is carried by the invoices, and a withdrawn deal has none, so
    the pair shows as a relationship with nothing under it. That is true."""
    seller = await make_prospect()
    buyer = await make_company()
    deal_id = await _migrated_deal(seller, buyer)
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id,
            DealStage.WITHDRAWN,
            reason="The buyer went quiet.",
            actor_id="rm-1",
        )

    report = await _resolve_only(deal_id)
    assert len(report.to_create) == 1
    await _apply_only(report, run_id="test-backfill-withdrawn")

    [relationship] = await _relationships(seller, buyer)
    async with db_services.AsyncSessionLocal() as db:
        invoices = int(
            await db.scalar(
                select(func.count())
                .select_from(TradeInvoice)
                .where(TradeInvoice.relationship_id == relationship.id)
            )
            or 0
        )
    assert invoices == 0


async def test_a_deal_cannot_name_its_own_seller_as_its_buyer():
    """The backfill carries a "seller = buyer" refusal, and this is the test that
    found it **cannot fire**: ``ck_deal_buyer_is_not_the_seller`` refuses the row at
    the database, through the service and through raw SQL alike.

    So the refusal branch is a guard, not a path, and saying so is the point — the
    alternative is a reader assuming those rows exist somewhere. It stays because it
    costs three lines and because without it one bad row would abort a whole run with
    ``TradeRelationshipIsSelfError`` instead of being named and skipped. §17.2's
    matching validation query is structurally zero for the same reason.
    """
    seller = await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Self {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
        with pytest.raises(IntegrityError) as raised:
            await db.execute(
                Deal.__table__.update()
                .where(Deal.id == view.id)
                .values(buyer_company_id=seller)
            )
        assert "ck_deal_buyer_is_not_the_seller" in str(raised.value)
        await db.rollback()


def test_the_refusal_reads_as_a_refusal_if_it_ever_fires():
    """Since no such deal can exist, the wording is tested on a constructed pair. A
    message nobody can reach is still a message somebody will one day read."""
    company_id = uuid.uuid4()
    deal_id = uuid.uuid4()
    report = Report(
        self_dealing=[
            Pair(
                seller_company_id=company_id,
                buyer_company_id=company_id,
                deal_ids=(deal_id,),
            )
        ],
        deals_with_a_buyer_company=1,
    )
    rendered = report.render()
    assert "a company does not sell to itself" in rendered
    assert str(deal_id) in rendered  # named, so it can be found
    assert str(company_id) in rendered
    assert report.to_create == []


async def test_the_backfill_writes_no_history_rows():
    """It creates relationships and that is all. A history row per backfilled pair
    would put a few thousand entries dated the night of the migration onto timelines
    that record what people did — and no person did this."""
    seller = await make_prospect()
    buyer = await make_company()
    deal_id = await _migrated_deal(seller, buyer)

    async def trade_rows() -> int:
        async with db_services.AsyncSessionLocal() as db:
            _, total = await HistoryService(db).list_for_company(
                seller, dimension=history_dimensions.TRADE
            )
        return total

    before = await trade_rows()
    await _apply_only(await _resolve_only(deal_id), run_id="test-backfill-history")
    assert await trade_rows() == before


# ── Validation and the undo ───────────────────────────────────────────────────


async def test_the_validation_queries_run_and_report_counts():
    """Asserted to **run and return numbers** rather than to be zero: this database
    holds other suites' deals, many of them unmigrated, so "every count is 0" is a
    claim about a migrated environment and not about this one. A query that no longer
    parses is what this protects against — the alternative is finding out on the night
    of the migration."""
    async with db_services.AsyncSessionLocal() as db:
        results = await validate(db)
    assert len(results) == 6
    for label, count in results:
        assert isinstance(count, int), label
        assert count >= 0, label

    labels = [label for label, _ in results]
    assert "duplicate relationships for one ordered pair" in labels


async def test_the_pair_check_finds_a_deal_the_backfill_has_not_reached():
    """The first validation query is the one that says the backfill is finished, so it
    has to be shown failing — a check that cannot fail proves nothing."""
    seller = await make_prospect()
    buyer = await make_company()
    deal_id = await _migrated_deal(seller, buyer)

    async def unrelated_deals() -> int:
        async with db_services.AsyncSessionLocal() as db:
            return dict(await validate(db))[
                "deals with a buyer company but no relationship for the pair"
            ]

    with_the_gap = await unrelated_deals()
    assert with_the_gap >= 1

    await _apply_only(await _resolve_only(deal_id), run_id="test-backfill-validate")
    assert await unrelated_deals() == with_the_gap - 1


async def test_report_run_counts_what_a_run_created_and_notices_invoices():
    """The undo is a ``DELETE`` the operator runs, so what they need from the command
    is the count and a warning: once an invoice hangs off a backfilled relationship,
    the foreign key refuses the delete. Being told that before trying is the
    difference between a decision and a surprise."""
    seller = await make_prospect()
    buyer = await make_company()
    deal_id = await _migrated_deal(seller, buyer)
    run_id = f"test-backfill-report-{uuid.uuid4().hex[:8]}"
    await _apply_only(await _resolve_only(deal_id), run_id=run_id)

    async with db_services.AsyncSessionLocal() as db:
        counts = await report_run(db, run_id=run_id)
    assert counts == {"created": 1, "with_invoices_since": 0}

    [relationship] = await _relationships(seller, buyer)
    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        invoice = await service.record_invoice(
            relationship.id,
            invoice_number=f"INV-{uuid.uuid4().hex[:6].upper()}",
            invoice_date=date(2026, 9, 1),
            amount=Decimal("1200.50"),
            currency="USD",
            actor_id="rm-1",
        )
        await service.record_outcome(
            invoice.id,
            payment_status=TradePaymentStatus.PAID,
            amount_paid=Decimal("1200.50"),
            proof_status=TradeProofStatus.PROVEN,
            evidence_note="Bank advice seen.",
            actor_id="rm-1",
        )
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        counts = await report_run(db, run_id=run_id)
    assert counts == {"created": 1, "with_invoices_since": 1}

    # And an unknown run reports nothing rather than erroring.
    async with db_services.AsyncSessionLocal() as db:
        assert (await report_run(db, run_id=f"never-{uuid.uuid4().hex[:8]}"))["created"] == 0


# ── The sequencing mistake ────────────────────────────────────────────────────


def test_a_mostly_unmigrated_database_is_called_out():
    """Running this before the buyer migration is the one ordering mistake available
    (``developer-allocation.md`` §6, step 3). It is not an error — the few linked deals
    would be backfilled correctly — but it wastes the run, so the report says so.

    A unit test on `Report`, because seeding thousands of unmigrated deals to prove a
    ratio would be a slow way to test arithmetic.
    """
    pair = Pair(
        seller_company_id=uuid.uuid4(),
        buyer_company_id=uuid.uuid4(),
        deal_ids=(uuid.uuid4(),),
    )
    mostly_unmigrated = Report(
        pairs=[pair], deals_with_a_buyer_company=10, deals_without_one=990
    )
    assert mostly_unmigrated.looks_unapplied
    assert "looks unapplied" in mostly_unmigrated.render()

    migrated = Report(pairs=[pair], deals_with_a_buyer_company=990, deals_without_one=10)
    assert not migrated.looks_unapplied
    assert "looks unapplied" not in migrated.render()

    # An empty database is not a warning — there is nothing to be wrong about.
    assert not Report().looks_unapplied
