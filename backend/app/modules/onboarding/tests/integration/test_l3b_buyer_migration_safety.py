"""The buyer migration's safety rules — ``remaining-work.md`` R-06 to R-11 (plan P4-6,
§17.2; decisions IQ-7, IQ-8, IQ-9).

``test_l3b_buyer_migration.py`` tests the migration §17.2 describes. This file tests
what an audit on a scratch copy of a seeded database found it doing wrong, one class
of defect per section:

* **R-06** — identifier-less buyers sharing a name were merged into one company (400
  of them, once). A name is never an identity: each row is its own company, and the
  report lists the look-alikes as "kept separate - review".
* **R-07** — a row already linked to a company is bound to it: its deal names it, or
  its BUYER results already have it as their subject. The legacy row maps to that
  company or to nothing, so the deal and its results never end up naming different
  companies. ``--validate`` catches either if it happens anyway.
* **R-08** — a PAN carried only by GSTINs on several companies is a conflict for a
  person, never the first row Postgres returns.
* **R-09** — ``--confirm-name`` lines are checked before anything is written.
* **R-10** — contacts, the creation history row, implausible registration numbers, and
  validation query 5 counting only what a run created.
* **R-11** — the command's output survives a cp1252 console.

Like the other file, every test seeds its own buyers and narrows the report to them:
the shared test database holds legacy buyers from every other suite. Validation
queries run over the whole table, so the tests assert how a count **moves** when one
row is corrupted on purpose, not what it is.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import func, select

from app.modules.onboarding.application.company_directory import BUYER_CONTACT_ROLE
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer_company_map import (
    BuyerMatchRule,
    DealBuyerCompanyMap,
)
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.migrate_deal_buyers import (
    CREATION_EVENT,
    MIN_REGISTRATION_KEY_LENGTH,
    ConfirmationError,
    _parse_confirmations,
    apply,
    check_confirmations,
    resolve,
    validate,
)
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).resolve().parents[5]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _unique(prefix: str) -> str:
    """A name nothing else in the shared database carries."""
    return f"{prefix} {uuid.uuid4().hex[:10].upper()}"


def _registration() -> str:
    return f"REG-{uuid.uuid4().hex[:8].upper()}"


async def _company(name: str, country: str, **identifiers) -> uuid.UUID:
    company_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            company_id, source=ExporterSource.SALES, name=name, country=country, **identifiers
        )
    return company_id


async def _deal_with_legacy_buyer(
    seller: uuid.UUID | None = None, **buyer
) -> tuple[uuid.UUID, uuid.UUID]:
    """A deal whose buyer is a legacy ``deal_buyer`` row. Returns (deal, buyer row)."""
    seller = seller or await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Safety deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(view.id, actor_id="rm-1", **buyer)
    async with db_services.AsyncSessionLocal() as db:
        deal = await db.scalar(select(Deal).where(Deal.id == view.id))
        await db.refresh(deal, ["buyer"])
        return view.id, deal.buyer.id


async def _name_buyer_company(deal_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """What task 2.4's picker does on the deal page."""
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=company_id, actor_id="rm-1"
        )


async def _buyer_check(deal_buyer_id: uuid.UUID) -> None:
    from app.modules.onboarding.application.verification_service import VerificationService

    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.SANCTIONS,
            VerificationEntityType.BUYER,
            deal_buyer_id,
            provider="manual",
            payload={"status": "PASSED"},
            actor_id="compliance-1",
            evidence=VerificationEvidence(note="Screened before the migration."),
        )


async def _resolve_only(*deal_buyer_ids: uuid.UUID):
    async with db_services.AsyncSessionLocal() as db:
        report = await resolve(db)
    wanted = set(deal_buyer_ids)
    report.resolutions = [r for r in report.resolutions if r.deal_buyer_id in wanted]
    return report


async def _apply_only(report, *, confirmed=None, run_id: str | None = None):
    async with db_services.AsyncSessionLocal() as db:
        return await apply(
            db,
            report,
            run_id=run_id or f"safety-{uuid.uuid4().hex[:8]}",
            actor_id="migration-test",
            confirmed=confirmed,
        )


async def _mapping(deal_buyer_id: uuid.UUID) -> DealBuyerCompanyMap | None:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(DealBuyerCompanyMap).where(DealBuyerCompanyMap.deal_buyer_id == deal_buyer_id)
        )


async def _deal(deal_id: uuid.UUID) -> Deal:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(select(Deal).where(Deal.id == deal_id))


async def _profile(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )


async def _buyer_results(deal_buyer_id: uuid.UUID) -> list[VerificationResult]:
    async with db_services.AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(VerificationResult).where(
                    VerificationResult.entity_reference == deal_buyer_id
                )
            )
        )


async def _validation() -> dict[str, int]:
    async with db_services.AsyncSessionLocal() as db:
        return dict(await validate(db))


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


# ── R-06: a name is never an identity ─────────────────────────────────────────


async def test_identifier_less_buyers_sharing_a_name_become_separate_companies():
    """IQ-8 ("keep name-only matches separate"). On a scratch copy the old rule turned
    400 buyers called "Rotterdam Trading BV" into one company. The two names below
    differ only in case, punctuation and legal form, so they normalise to one key."""
    stem = _unique("Lookalike Trading")
    _d1, first = await _deal_with_legacy_buyer(name=f"{stem} BV", country="NL")
    _d2, second = await _deal_with_legacy_buyer(name=f"{stem.lower()} b.v.", country="NL")

    report = await _resolve_only(first, second)
    assert [r.rule for r in report.ready] == [BuyerMatchRule.NEW, BuyerMatchRule.NEW]
    assert all(r.group_key is None for r in report.ready)
    assert report.groups == {}
    [(country, _key)] = report.look_alikes
    assert country == "NL"
    assert "kept separate - review" in report.render()

    counts = await _apply_only(report)
    assert counts["companies_created"] == 2
    one, two = await _mapping(first), await _mapping(second)
    assert one.company_id != two.company_id
    assert one.match_rule is two.match_rule is BuyerMatchRule.NEW


async def test_a_later_row_with_that_name_needs_a_person_once_the_first_exists():
    """Kept separate does not mean forgotten: once one look-alike is a company, the
    next buyer of that name has a candidate, and a person decides."""
    name = _unique("Second Wave Imports")
    _d1, first = await _deal_with_legacy_buyer(name=name, country="DE")
    await _apply_only(await _resolve_only(first))
    company_id = (await _mapping(first)).company_id

    _d2, later = await _deal_with_legacy_buyer(name=name, country="DE")
    [blocked] = (await _resolve_only(later)).needs_a_person
    assert "confirm or reject by hand" in blocked.problems[0]
    assert blocked.candidates == [company_id]


# ── R-07: the deal's own buyer company is authoritative ───────────────────────


async def test_a_name_only_legacy_buyer_maps_to_the_company_its_deal_already_names():
    named = await _company(
        _unique("Picked On The Deal Page"), "NL", registration_number=_registration()
    )
    deal_id, buyer_id = await _deal_with_legacy_buyer(name=_unique("Old Buyer Name"), country="NL")
    await _buyer_check(buyer_id)
    await _name_buyer_company(deal_id, named)

    report = await _resolve_only(buyer_id)
    [resolution] = report.ready
    assert resolution.rule is BuyerMatchRule.ALREADY_LINKED
    assert resolution.target == named

    counts = await _apply_only(report)
    assert counts["companies_created"] == 0
    mapping = await _mapping(buyer_id)
    assert (mapping.company_id, mapping.match_rule) == (named, BuyerMatchRule.ALREADY_LINKED)
    assert (await _deal(deal_id)).buyer_company_id == named
    # The deal's BUYER result belongs to the company the deal names — and to no other.
    [result] = await _buyer_results(buyer_id)
    assert result.subject_company_id == named


async def test_an_agreeing_identifier_maps_by_that_identifier():
    pan = _pan()
    named = await _company(_unique("Agreeing Holder"), "IN", pan=pan)
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Agreeing Holder"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_id, named)

    [resolution] = (await _resolve_only(buyer_id)).ready
    assert (resolution.rule, resolution.target) == (BuyerMatchRule.PAN, named)


async def test_a_conflicting_identifier_needs_a_person_and_nothing_is_written():
    """The legacy row's PAN belongs to another company. Mapping it there would point
    the map — and the deal's BUYER results — at a company the deal does not name."""
    pan = _pan()
    holder = await _company(_unique("Real PAN Holder"), "IN", pan=pan)
    named = await _company(_unique("Picked Company"), "IN", pan=_pan())
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Conflicting Buyer"), country="IN", tax_id=pan
    )
    await _buyer_check(buyer_id)
    await _name_buyer_company(deal_id, named)

    report = await _resolve_only(buyer_id)
    [blocked] = report.needs_a_person
    assert blocked.problems[0].startswith("CONFLICT: the deal already names its buyer company")
    assert str(holder) in blocked.problems[0]
    # The deal's company is set once, so it is the only thing a person may confirm.
    assert blocked.candidates == [named]

    counts = await _apply_only(report)
    assert counts["mapped"] == 0
    assert await _mapping(buyer_id) is None
    [result] = await _buyer_results(buyer_id)
    assert result.subject_company_id is None

    # Confirming the PAN holder is refused; confirming the deal's company is accepted.
    async with db_services.AsyncSessionLocal() as db:
        errors = await check_confirmations(db, report, {buyer_id: holder})
    assert "already linked to" in errors[0]
    await _apply_only(report, confirmed={buyer_id: named})
    mapping = await _mapping(buyer_id)
    assert (mapping.company_id, mapping.match_rule) == (named, BuyerMatchRule.NAME_CONFIRMED)


async def _subject_results(deal_buyer_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """Give the row's BUYER results a subject before the migration runs (NULL -> a
    value, which their freeze allows once) — the state 45 rows on the scratch copy were
    found in."""
    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE onboarding.verification_result SET subject_company_id = %s "
                "WHERE entity_reference = %s",
                (str(company_id), str(deal_buyer_id)),
            )
    finally:
        connection.close()


async def test_a_buyer_result_that_already_names_a_company_links_the_row_to_it():
    """Found by the scratch run: 45 BUYER results already had a subject while their
    deals named no buyer company. Mapping those rows to a new company would have left
    each deal naming one company and its result another, for good — both are frozen."""
    subject = await _company(_unique("Already Subject"), "NL", registration_number=_registration())
    deal_id, buyer_id = await _deal_with_legacy_buyer(name=_unique("Old Name"), country="NL")
    await _buyer_check(buyer_id)
    await _subject_results(buyer_id, subject)

    report = await _resolve_only(buyer_id)
    [resolution] = report.ready
    assert (resolution.rule, resolution.target) == (BuyerMatchRule.ALREADY_LINKED, subject)
    assert "existing subject" in resolution.notes[0]

    counts = await _apply_only(report)
    assert counts["companies_created"] == 0
    assert (await _mapping(buyer_id)).company_id == subject
    assert (await _deal(deal_id)).buyer_company_id == subject


async def test_a_deal_and_its_results_naming_different_companies_need_correcting_by_hand():
    named = await _company(_unique("Deal Names"), "NL", registration_number=_registration())
    subject = await _company(_unique("Result Names"), "NL", registration_number=_registration())
    deal_id, buyer_id = await _deal_with_legacy_buyer(name=_unique("Split"), country="NL")
    await _buyer_check(buyer_id)
    await _subject_results(buyer_id, subject)
    await _name_buyer_company(deal_id, named)

    report = await _resolve_only(buyer_id)
    [blocked] = report.needs_a_person
    assert "already linked to different companies" in blocked.problems[0]
    # Both links are frozen, so no confirmation can make them agree.
    assert blocked.candidates == []
    assert (await _apply_only(report))["mapped"] == 0


async def test_the_deals_company_holding_a_different_pan_is_a_conflict():
    named = await _company(_unique("Different PAN"), "IN", pan=_pan())
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Different PAN"), country="IN", tax_id=_pan()
    )
    await _name_buyer_company(deal_id, named)

    [blocked] = (await _resolve_only(buyer_id)).needs_a_person
    assert "holds a different PAN" in blocked.problems[0]


async def test_another_deals_buyer_with_the_same_pan_joins_the_named_company():
    """The deal page's choice is an identity: a second legacy buyer carrying the same
    PAN, on a deal that names nobody, is the same company."""
    pan = _pan()
    named = await _company(_unique("Named Once"), "IN")
    deal_a, buyer_a = await _deal_with_legacy_buyer(
        name=_unique("Named Once"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_a, named)
    deal_b, buyer_b = await _deal_with_legacy_buyer(
        name=_unique("Named Once"), country="IN", tax_id=pan
    )

    report = await _resolve_only(buyer_a, buyer_b)
    assert {r.target for r in report.ready} == {named}
    counts = await _apply_only(report)
    assert counts["companies_created"] == 0
    assert (await _deal(deal_b)).buyer_company_id == named


async def test_deals_naming_different_companies_for_one_identity_need_a_person():
    """Found on the scratch copy: five deals had each named a *different* buyer company
    for legacy buyers sharing one registration number, and 325 other buyers carried it
    too. Letting the first deal decide would have mapped all 325 to that one company.
    A contested identity maps nobody by rule; each deal's own row can only ever be
    confirmed to the company its deal names."""
    pan = _pan()
    first_pick = await _company(_unique("First Pick"), "IN")
    second_pick = await _company(_unique("Second Pick"), "IN")
    deal_1, buyer_1 = await _deal_with_legacy_buyer(
        name=_unique("Contested"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_1, first_pick)
    deal_2, buyer_2 = await _deal_with_legacy_buyer(
        name=_unique("Contested"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_2, second_pick)
    _deal_3, buyer_3 = await _deal_with_legacy_buyer(
        name=_unique("Contested"), country="IN", tax_id=pan
    )

    report = await _resolve_only(buyer_1, buyer_2, buyer_3)
    assert report.ready == []
    rows = {r.deal_buyer_id: r for r in report.needs_a_person}
    assert all(r.problems[0].startswith("CONFLICT") for r in rows.values())
    assert rows[buyer_1].candidates == [first_pick]
    assert rows[buyer_2].candidates == [second_pick]
    assert sorted(rows[buyer_3].candidates, key=str) == sorted([first_pick, second_pick], key=str)
    assert (await _apply_only(report))["mapped"] == 0


async def test_a_contest_survives_its_rows_being_confirmed_in_an_earlier_run():
    """Found by the scratch run: once a person confirmed the linked rows, they were no
    longer resolved, the contest vanished with them, and the rows left over would have
    been mapped by rule. Earlier runs' decisions still count."""
    pan = _pan()
    first_pick = await _company(_unique("Earlier Pick"), "IN")
    second_pick = await _company(_unique("Other Pick"), "IN")
    deal_1, buyer_1 = await _deal_with_legacy_buyer(
        name=_unique("Survives"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_1, first_pick)
    deal_2, buyer_2 = await _deal_with_legacy_buyer(
        name=_unique("Survives"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_2, second_pick)
    _deal_3, left_over = await _deal_with_legacy_buyer(
        name=_unique("Survives"), country="IN", tax_id=pan
    )

    report = await _resolve_only(buyer_1, buyer_2, left_over)
    await _apply_only(report, confirmed={buyer_1: first_pick, buyer_2: second_pick})
    assert (await _mapping(buyer_1)).company_id == first_pick

    [still_blocked] = (await _resolve_only(left_over)).needs_a_person
    assert still_blocked.problems[0].startswith("CONFLICT: buyers already linked")
    assert sorted(still_blocked.candidates, key=str) == sorted([first_pick, second_pick], key=str)


async def test_a_later_row_joins_what_an_earlier_run_decided():
    """The same rule from the other side: a buyer arriving after a run, carrying an
    identity that run mapped, joins that company rather than creating another."""
    pan = _pan()
    named = await _company(_unique("Decided Before"), "IN")
    deal_1, buyer_1 = await _deal_with_legacy_buyer(
        name=_unique("Decided"), country="IN", tax_id=pan
    )
    await _name_buyer_company(deal_1, named)
    await _apply_only(await _resolve_only(buyer_1))

    _deal_2, later = await _deal_with_legacy_buyer(
        name=_unique("Decided"), country="IN", tax_id=pan
    )
    [resolution] = (await _resolve_only(later)).ready
    assert (resolution.rule, resolution.target) == (BuyerMatchRule.PAN, named)


async def test_a_deal_that_names_a_company_after_the_report_is_skipped():
    """The report is built, then somebody picks the buyer company on the deal page
    before ``--apply`` writes. The row is skipped, not mapped against it."""
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Raced Buyer"), country="NL", registration_number=_registration()
    )
    report = await _resolve_only(buyer_id)
    await _name_buyer_company(
        deal_id,
        await _company(_unique("Picked Meanwhile"), "NL", registration_number=_registration()),
    )

    counts = await _apply_only(report)
    assert counts["skipped_deal_changed"] == 1
    assert counts["companies_created"] == counts["mapped"] == 0
    assert await _mapping(buyer_id) is None


async def test_validation_fails_when_the_map_disagrees_with_the_deal():
    """Deliberately corrupted: a mapping row (the table is append-only, but inserting
    is allowed) naming a company the deal does not."""
    label = "mapped deal buyers whose company is not the deal's buyer company"
    before = (await _validation())[label]

    deal_id, buyer_id = await _deal_with_legacy_buyer(name=_unique("Corrupt Map"), country="NL")
    await _name_buyer_company(
        deal_id, await _company(_unique("Deal Says"), "NL", registration_number=_registration())
    )
    wrong = await _company(_unique("Map Says"), "NL", registration_number=_registration())
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            DealBuyerCompanyMap(
                deal_buyer_id=buyer_id,
                company_id=wrong,
                match_rule=BuyerMatchRule.NEW,
                matched_by="corruption-test",
                run_id=f"corrupt-{uuid.uuid4().hex[:8]}",
            )
        )
        await db.commit()

    assert (await _validation())[label] == before + 1


async def test_validation_fails_when_a_buyer_result_names_another_company():
    """Deliberately corrupted: the result's subject set (NULL -> a value, which its
    freeze allows once) to a company other than the one the deal names."""
    label = "BUYER results whose subject is not the deal's buyer company"
    before = (await _validation())[label]

    deal_id, buyer_id = await _deal_with_legacy_buyer(name=_unique("Corrupt Result"), country="NL")
    await _buyer_check(buyer_id)
    await _name_buyer_company(
        deal_id, await _company(_unique("Deal Names"), "NL", registration_number=_registration())
    )
    wrong = await _company(_unique("Result Says"), "NL", registration_number=_registration())
    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE onboarding.verification_result SET subject_company_id = %s "
                "WHERE entity_reference = %s",
                (str(wrong), str(buyer_id)),
            )
    finally:
        connection.close()

    assert (await _validation())[label] == before + 1


# ── R-08: one PAN, several GST holders ────────────────────────────────────────


async def test_a_pan_carried_by_several_companies_gstins_is_a_conflict():
    """IQ-9 makes this legal: GSTINs are warn-only. No company holds the PAN itself,
    so the GSTIN path is the only one — and it names two companies."""
    pan = _pan()
    first = await _company(_unique("GST Holder One"), "IN", gstins=[f"27{pan}1Z5"])
    second = await _company(_unique("GST Holder Two"), "IN", gstins=[f"29{pan}1Z5"])
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Shared PAN Buyer"), country="IN", tax_id=pan
    )

    report = await _resolve_only(buyer_id)
    [blocked] = report.needs_a_person
    assert blocked.problems[0].startswith("CONFLICT: the PAN is held by several companies")
    assert sorted(blocked.candidates, key=str) == sorted([first, second], key=str)
    assert (await _apply_only(report))["mapped"] == 0

    # A person chooses one of the two.
    await _apply_only(report, confirmed={buyer_id: second})
    mapping = await _mapping(buyer_id)
    assert (mapping.company_id, mapping.match_rule) == (second, BuyerMatchRule.NAME_CONFIRMED)


async def test_a_pan_carried_by_one_companys_gstin_still_matches():
    pan = _pan()
    holder = await _company(_unique("Single GST Holder"), "IN", gstins=[f"27{pan}1Z5"])
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Single GST Buyer"), country="IN", tax_id=pan
    )
    [resolution] = (await _resolve_only(buyer_id)).ready
    assert (resolution.rule, resolution.target) == (BuyerMatchRule.PAN, holder)


# ── R-09: confirmations are checked before anything is written ────────────────


async def _blocked_row():
    """A deal buyer that needs a person (a name-only match), its candidate, and its
    deal's seller."""
    name = _unique("Needs A Person")
    candidate = await _company(name, "BE", registration_number=_registration())
    seller = await make_prospect()
    _deal_id, buyer_id = await _deal_with_legacy_buyer(seller, name=name, country="BE")
    return buyer_id, candidate, seller


async def test_each_kind_of_bad_confirmation_is_refused():
    buyer_id, candidate, seller = await _blocked_row()
    _d, ready_id = await _deal_with_legacy_buyer(
        name=_unique("Ready Row"), country="NL", registration_number=_registration()
    )
    elsewhere = await _company(_unique("Not Offered"), "BE", registration_number=_registration())
    report = await _resolve_only(buyer_id, ready_id)

    cases = {
        "no deal buyer has that id": {uuid.uuid4(): candidate},
        "no company has that id": {buyer_id: uuid.uuid4()},
        "not one the report offered": {buyer_id: elsewhere},
        "own seller": {buyer_id: seller},
        "does not need a person": {ready_id: candidate},
    }
    async with db_services.AsyncSessionLocal() as db:
        for expected, confirmed in cases.items():
            [error] = await check_confirmations(db, report, confirmed)
            assert expected in error, (expected, error)
        assert await check_confirmations(db, report, {buyer_id: candidate}) == []


async def test_an_already_mapped_buyer_cannot_be_confirmed_again():
    buyer_id, candidate, _seller = await _blocked_row()
    report = await _resolve_only(buyer_id)
    await _apply_only(report, confirmed={buyer_id: candidate})

    later = await _resolve_only(buyer_id)
    async with db_services.AsyncSessionLocal() as db:
        [error] = await check_confirmations(db, later, {buyer_id: candidate})
    assert "already mapped" in error


async def test_a_bad_confirmation_stops_the_run_before_any_row_is_written():
    """The failure mode the old code had: companies for earlier rows committed one by
    one, then a later confirmation failed. Now nothing is written at all."""
    buyer_id, _candidate, seller = await _blocked_row()
    deal_id, ready_id = await _deal_with_legacy_buyer(
        name=_unique("Would Be Created"), country="NL", registration_number=_registration()
    )
    report = await _resolve_only(ready_id, buyer_id)
    async with db_services.AsyncSessionLocal() as db:
        companies_before = await db.scalar(select(func.count()).select_from(ExporterProfile))

    with pytest.raises(ConfirmationError) as caught:
        await _apply_only(report, confirmed={buyer_id: seller})
    assert "own seller" in caught.value.errors[0]

    assert await _mapping(ready_id) is None
    assert (await _deal(deal_id)).buyer_company_id is None
    async with db_services.AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(func.count()).select_from(ExporterProfile)) == companies_before
        )


async def test_confirmation_lines_must_name_one_company_per_buyer():
    buyer, company = uuid.uuid4(), uuid.uuid4()
    assert _parse_confirmations([f"{buyer}={company}", f"{buyer}={company}"]) == {buyer: company}
    with pytest.raises(SystemExit, match="twice"):
        _parse_confirmations([f"{buyer}={company}", f"{buyer}={uuid.uuid4()}"])
    with pytest.raises(SystemExit, match="two UUIDs"):
        _parse_confirmations([f"{buyer}=not-a-uuid"])
    with pytest.raises(SystemExit, match="one company id"):
        _parse_confirmations([f"{buyer}={company},{uuid.uuid4()}"])


# ── R-10: contacts, the creation row, registration numbers, query 5 ───────────


async def test_a_created_company_gets_one_creation_row_saying_where_it_came_from():
    """§17.2: one history row on the new company, ``company_created_from_deal_buyer``,
    with ``{run_id, deal_buyer_ids, deal_ids, match_rule}``, on the earliest deal."""
    registration = _registration()
    first_deal, first = await _deal_with_legacy_buyer(
        name=_unique("Grouped Buyer"), country="NL", registration_number=registration
    )
    second_deal, second = await _deal_with_legacy_buyer(
        name=_unique("Grouped Buyer"), country="NL", registration_number=registration
    )
    run_id = f"creation-{uuid.uuid4().hex[:8]}"
    await _apply_only(await _resolve_only(first, second), run_id=run_id)

    company_id = (await _mapping(first)).company_id
    assert (await _mapping(second)).company_id == company_id
    assert (await _profile(company_id)).created_via_deal_id == first_deal
    async with db_services.AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(ExporterLifecycleHistory).where(
                    ExporterLifecycleHistory.customer_id == company_id
                )
            )
        )
    [row] = rows
    assert (row.dimension, row.event_type) == ("pipeline", CREATION_EVENT)
    details = row.event_metadata
    assert details["run_id"] == run_id
    assert sorted(details["deal_buyer_ids"]) == sorted([str(first), str(second)])
    assert sorted(details["deal_ids"]) == sorted([str(first_deal), str(second_deal)])
    assert details["match_rule"] == BuyerMatchRule.REGISTRATION_NUMBER.value


async def test_the_buyers_email_and_phone_become_contact_records():
    """§17.2: "contacts from buyer email/phone (as a contact record)". One per distinct
    pair across the rows that became the company; never the primary contact."""
    registration = _registration()
    _d1, first = await _deal_with_legacy_buyer(
        name=_unique("Contact Buyer"),
        country="NL",
        registration_number=registration,
        contact_email="buying@contact.example",
        contact_phone="+31 20 555 0101",
    )
    _d2, second = await _deal_with_legacy_buyer(
        name=_unique("Contact Buyer"),
        country="NL",
        registration_number=registration,
        contact_email="BUYING@contact.example",
        contact_phone="+31205550101",
    )
    _d3, third = await _deal_with_legacy_buyer(
        name=_unique("Contact Buyer"),
        country="NL",
        registration_number=registration,
        contact_email="finance@contact.example",
    )
    counts = await _apply_only(await _resolve_only(first, second, third))
    assert counts["contacts_created"] == 2

    company_id = (await _mapping(first)).company_id
    async with db_services.AsyncSessionLocal() as db:
        contacts = list(
            await db.scalars(
                select(ExporterContact).where(ExporterContact.customer_id == company_id)
            )
        )
    assert sorted(c.email for c in contacts) == [
        "buying@contact.example",
        "finance@contact.example",
    ]
    assert {c.role for c in contacts} == {BUYER_CONTACT_ROLE}
    assert not any(c.is_primary_contact for c in contacts)


async def test_a_one_character_registration_number_is_not_an_identity():
    """``REG:BE:X`` grouped eleven rows on a scratch copy. Now ``X`` matches nothing,
    groups nothing, is not stored on a company (whose unique index it would claim) and
    is listed for review."""
    assert MIN_REGISTRATION_KEY_LENGTH == 2
    _d1, first = await _deal_with_legacy_buyer(
        name=_unique("Placeholder One"), country="BE", registration_number="X"
    )
    _d2, second = await _deal_with_legacy_buyer(
        name=_unique("Placeholder Two"), country="BE", registration_number="-x-"
    )

    report = await _resolve_only(first, second)
    assert [r.rule for r in report.ready] == [BuyerMatchRule.NEW, BuyerMatchRule.NEW]
    assert all(r.group_key is None and r.registration_number is None for r in report.ready)
    rendered = report.render()
    assert "fewer than 2 letters or digits" in rendered and "Migrates, but review" in rendered

    assert (await _apply_only(report))["companies_created"] == 2
    for buyer in (first, second):
        assert (await _profile((await _mapping(buyer)).company_id)).registration_number is None


async def test_rows_sharing_either_identifier_are_one_company():
    """A buyer with a PAN and a registration number, and another with only that
    registration number, are one company (§17.2 steps 2-3). Treated as two, the second
    company would be refused by the ``(country, registration number)`` unique index
    halfway through ``--apply``."""
    pan, registration = _pan(), _registration()
    _d1, both = await _deal_with_legacy_buyer(
        name=_unique("Two Keys"), country="IN", tax_id=pan, registration_number=registration
    )
    _d2, reg_only = await _deal_with_legacy_buyer(
        name=_unique("Two Keys"), country="IN", registration_number=registration
    )
    report = await _resolve_only(both, reg_only)
    assert len(report.ready) == 2
    assert (await _apply_only(report))["companies_created"] == 1
    assert (await _mapping(both)).company_id == (await _mapping(reg_only)).company_id


async def test_query_5_counts_only_companies_a_run_created():
    label = "companies a run created without exactly one creation history row"
    before = (await _validation())[label]

    # A DEAL_BUYER company no run created: not the migration's to account for.
    from app.modules.onboarding.application.company_directory import CompanyDirectoryService
    from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft

    async with db_services.AsyncSessionLocal() as db:
        await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(name=_unique("Not From A Run"), country="NL"), actor_id="test"
        )
    # A run's company later brought into the pipeline: a second pipeline row, still one
    # creation row.
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Brought In Later"), country="NL", registration_number=_registration()
    )
    await _apply_only(await _resolve_only(buyer_id))
    company_id = (await _mapping(buyer_id)).company_id
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).bring_into_pipeline(company_id, actor_id="rm-1")
    assert (await _validation())[label] == before

    # Deliberately corrupted: a second creation row on that company.
    async with db_services.AsyncSessionLocal() as db:
        await HistoryService(db).record(
            company_id,
            dimension=history_dimensions.PIPELINE,
            to_value="NOT_IN_PIPELINE",
            actor_id="corruption-test",
            source="test",
            event_type=CREATION_EVENT,
        )
        await db.commit()
    assert (await _validation())[label] == before + 1


async def test_validation_has_every_check_and_a_rerun_creates_nothing():
    registration = _registration()
    _d, buyer_id = await _deal_with_legacy_buyer(
        name=_unique("Run Twice"),
        country="NL",
        registration_number=registration,
        contact_email="twice@run.example",
    )
    first = await _apply_only(await _resolve_only(buyer_id))
    assert (first["companies_created"], first["contacts_created"], first["mapped"]) == (1, 1, 1)

    second = await _apply_only(await _resolve_only(buyer_id))
    assert set(second.values()) == {0}
    assert len(await _validation()) == 9


# ── R-11: Windows consoles ────────────────────────────────────────────────────


async def test_the_report_is_ascii_even_with_conflicts_and_look_alikes():
    """The old report printed an arrow in every conflict row, which a cp1252 console
    cannot encode."""
    pan = _pan()
    await _company(_unique("Arrow One"), "IN", gstins=[f"27{pan}1Z5"])
    await _company(_unique("Arrow Two"), "IN", gstins=[f"29{pan}1Z5"])
    _d1, conflict = await _deal_with_legacy_buyer(name=_unique("Arrow"), country="IN", tax_id=pan)
    stem = _unique("Ascii Lookalike")
    _d2, a = await _deal_with_legacy_buyer(name=stem, country="FR")
    _d3, b = await _deal_with_legacy_buyer(name=stem, country="FR")

    rendered = (await _resolve_only(conflict, a, b)).render()
    assert rendered.isascii()
    rendered.encode("cp1252")


async def test_the_backfill_report_is_ascii():
    from app.modules.onboarding.backfill_trade_relationships import Pair, Report

    pair = Pair(
        seller_company_id=uuid.uuid4(),
        buyer_company_id=uuid.uuid4(),
        deal_ids=(uuid.uuid4(),),
        seller_name="Seller",
        buyer_name="Buyer",
    )
    report = Report(
        pairs=[pair], self_dealing=[pair], deals_with_a_buyer_company=1, deals_without_one=9
    )
    rendered = report.render()
    assert "->" in rendered and rendered.isascii()


async def test_a_name_the_console_cannot_encode_is_escaped_not_fatal(monkeypatch):
    """The command's own text is ASCII; a buyer's name may not be."""
    from app.modules.onboarding.command_console import prepare_console

    buffer = io.BytesIO()
    console = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    prepare_console()
    print("buyer → 中文 Trading")
    console.flush()
    assert b"\\u2192" in buffer.getvalue()


def _run_command(module: str, *args: str) -> subprocess.CompletedProcess:
    """Run a data command the way an operator would on a cp1252 console, against the
    database this test session uses."""
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "LOG_LEVEL": "WARNING",
        "DEBUG": "false",
        "DATABASE_URL": get_settings().DATABASE_URL,
        "DATABASE_SYNC_URL": get_settings().DATABASE_SYNC_URL,
    }
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        timeout=600,
    )


async def test_both_commands_run_on_a_cp1252_console_and_validation_fails_loudly():
    """End to end, in a subprocess whose stdout is cp1252. ``--validate`` exits 1 and
    says so when any count is not 0; on this shared database some always are, because
    other suites leave legacy buyers unmigrated."""
    counts = await _validation()
    done = _run_command("app.modules.onboarding.migrate_deal_buyers", "--validate")
    assert b"UnicodeEncodeError" not in done.stderr, done.stderr.decode("cp1252", "replace")
    assert done.stdout.isascii()
    if any(counts.values()):
        assert done.returncode == 1
        assert b"VALIDATION FAILED" in done.stdout
    else:
        assert done.returncode == 0

    backfill = _run_command("app.modules.onboarding.backfill_trade_relationships", "--validate")
    assert b"UnicodeEncodeError" not in backfill.stderr
    assert backfill.returncode in (0, 1)


async def test_a_dry_run_on_a_cp1252_console_writes_nothing():
    """The dry run prints conflict rows (the old arrow) and look-alikes, and writes
    nothing: the tables it would write are counted before and after."""
    pan = _pan()
    await _company(_unique("Dry One"), "IN", gstins=[f"27{pan}1Z5"])
    await _company(_unique("Dry Two"), "IN", gstins=[f"29{pan}1Z5"])
    await _deal_with_legacy_buyer(name=_unique("Dry Conflict"), country="IN", tax_id=pan)

    async def tallies() -> tuple[int, ...]:
        async with db_services.AsyncSessionLocal() as db:
            return (
                await db.scalar(select(func.count()).select_from(ExporterProfile)),
                await db.scalar(select(func.count()).select_from(DealBuyerCompanyMap)),
                await db.scalar(select(func.count()).select_from(ExporterContact)),
                await db.scalar(select(func.count()).select_from(ExporterLifecycleHistory)),
                await db.scalar(
                    select(func.count()).select_from(Deal).where(Deal.buyer_company_id.isnot(None))
                ),
                await db.scalar(
                    select(func.count())
                    .select_from(VerificationResult)
                    .where(VerificationResult.subject_company_id.isnot(None))
                ),
            )

    before = await tallies()
    done = _run_command("app.modules.onboarding.migrate_deal_buyers", "--dry-run")
    assert done.returncode == 0, done.stderr.decode("cp1252", "replace")[-2000:]
    assert b"UnicodeEncodeError" not in done.stderr
    assert b"CONFLICT: the PAN is held by several companies" in done.stdout
    assert b"Dry run: nothing was written." in done.stdout
    assert await tallies() == before
