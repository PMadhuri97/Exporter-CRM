"""The buyer migration — task 2.6 (**owner: Developer 2**, plan P4-6 and §17.2).

§17.2 asks for "migration tests on a fixture DB seeded with the edge cases", and
names them: duplicates, Indian buyers with a PAN or GSTIN in ``tax_id``, a buyer
matching an existing *seller*, a buyer matching its own deal's seller (refused),
terminal deals, BUYER results with snapshots, and an idempotent re-run. Each has a
test here.

**Nothing in this file runs against real data**, and neither does the command: it is
driven here over rows these tests create. Sizing a real run needs Developer 3's 3.2
reports and the name-only duplicates need Compliance's review, so the command exists,
is tested, and waits.

Every test seeds its own buyers and resolves **only those**, by passing their ids —
the shared database already holds a thousand legacy buyers from other suites, and a
test that asserted over the whole table would be asserting about other people's
fixtures.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer_company_map import (
    BuyerMatchRule,
    DealBuyerCompanyMap,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.migrate_deal_buyers import apply, resolve, rollback, validate
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _unique(prefix: str) -> str:
    """A name nothing else in this shared database shares, so a name-only match is
    about this test's rows and not about a thousand other fixtures'."""
    return f"{prefix} {uuid.uuid4().hex[:10].upper()}"


async def _seller() -> uuid.UUID:
    return await make_prospect()


async def _deal_with_legacy_buyer(seller: uuid.UUID, **buyer) -> tuple[uuid.UUID, uuid.UUID]:
    """A deal whose buyer is a legacy ``deal_buyer`` row. Returns (deal, buyer row)."""
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Migration deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    deal_id = view.id
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer(deal_id, actor_id="rm-1", **buyer)
    async with db_services.AsyncSessionLocal() as db:
        deal = await db.scalar(select(Deal).where(Deal.id == deal_id))
        await db.refresh(deal, ["buyer"])
        return deal_id, deal.buyer.id


async def _resolve_only(*deal_buyer_ids: uuid.UUID):
    """The report, narrowed to the rows a test seeded."""
    async with db_services.AsyncSessionLocal() as db:
        report = await resolve(db)
    wanted = set(deal_buyer_ids)
    report.resolutions = [r for r in report.resolutions if r.deal_buyer_id in wanted]
    return report


async def _apply_only(report, *, run_id: str, confirmed=None) -> dict[str, int]:
    async with db_services.AsyncSessionLocal() as db:
        return await apply(
            db, report, run_id=run_id, actor_id="migration-test", confirmed=confirmed
        )


async def _mapping(deal_buyer_id: uuid.UUID) -> DealBuyerCompanyMap | None:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(DealBuyerCompanyMap).where(
                DealBuyerCompanyMap.deal_buyer_id == deal_buyer_id
            )
        )


async def _deal(deal_id: uuid.UUID) -> Deal:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(select(Deal).where(Deal.id == deal_id))


# ── A new company, and what it looks like (§17.2 "Creation") ──────────────────


async def test_a_buyer_with_no_match_becomes_a_not_in_pipeline_company():
    seller = await _seller()
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller,
        name=_unique("Brand New Buyer"),
        country="NL",
        registration_number=f"KVK-{uuid.uuid4().hex[:8].upper()}",
    )

    report = await _resolve_only(buyer_id)
    [resolution] = report.ready
    assert resolution.rule is BuyerMatchRule.REGISTRATION_NUMBER

    counts = await _apply_only(report, run_id="test-new")
    assert counts["companies_created"] == 1
    assert counts["deals_linked"] == 1

    mapping = await _mapping(buyer_id)
    assert mapping is not None
    async with db_services.AsyncSessionLocal() as db:
        company = await db.scalar(
            select(ExporterProfile).where(
                ExporterProfile.customer_id == mapping.company_id
            )
        )
    # §17.2's creation rules, every one of them.
    assert company.pipeline_status is CompanyPipelineStatus.NOT_IN_PIPELINE
    assert company.source is ExporterSource.DEAL_BUYER
    assert company.created_via == "DEAL_BUYER"
    assert company.created_via_deal_id == deal_id
    assert (await _deal(deal_id)).buyer_company_id == mapping.company_id


async def test_an_indian_buyer_joins_the_company_holding_its_pan():
    """§17.2 step 2, and R1's case: the company it joins may be an existing **seller**,
    which is the whole point of unifying buyers and sellers into one record."""
    pan = _pan()
    existing = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            existing,
            source=ExporterSource.SALES,
            name=_unique("Mumbai Textiles"),
            country="IN",
            pan=pan,
        )
    seller = await _seller()
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller, name=_unique("Mumbai Textiles"), country="IN", tax_id=pan
    )

    report = await _resolve_only(buyer_id)
    [resolution] = report.ready
    assert resolution.rule is BuyerMatchRule.PAN
    assert resolution.company_id == existing

    counts = await _apply_only(report, run_id="test-pan")
    # Joined, not created: one set of checks per company (P4-5's criterion).
    assert counts["companies_created"] == 0
    assert (await _mapping(buyer_id)).company_id == existing


async def test_a_gstin_in_tax_id_resolves_through_its_embedded_pan():
    """A legacy ``tax_id`` is free text, so it may hold a GSTIN. Characters 3–12 are
    the PAN, which is the same rule the CRM already matches companies by."""
    pan = _pan()
    existing = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            existing,
            source=ExporterSource.SALES,
            name=_unique("Chennai Spices"),
            country="IN",
            pan=pan,
        )
    seller = await _seller()
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller, name=_unique("Chennai Spices"), country="IN", tax_id=f"27{pan}1Z5"
    )

    report = await _resolve_only(buyer_id)
    [resolution] = report.ready
    assert resolution.rule is BuyerMatchRule.PAN
    assert resolution.company_id == existing


async def test_several_deal_buyers_with_one_registration_number_become_one_company():
    """§17.2's "logical merge": the rows stay, and the map records that they were the
    same company all along. No company-to-company merge is performed."""
    seller = await _seller()
    registration = f"KVK-{uuid.uuid4().hex[:8].upper()}"
    buyers = []
    for _ in range(3):
        _deal_id, buyer_id = await _deal_with_legacy_buyer(
            seller,
            name=_unique("Rotterdam Trading"),
            country="NL",
            registration_number=registration,
        )
        buyers.append(buyer_id)

    report = await _resolve_only(*buyers)
    assert len(report.ready) == 3
    counts = await _apply_only(report, run_id="test-merge")
    assert counts["companies_created"] == 1
    assert counts["mapped"] == 3

    companies = {(await _mapping(b)).company_id for b in buyers}
    assert len(companies) == 1


# ── The two refusals (§17.2 steps 4 and 5) ────────────────────────────────────


async def test_a_name_only_match_is_reported_and_never_merged_automatically():
    """Decision IQ-8. The whole reason this is a command with a dry run rather than
    an Alembic revision."""
    shared_name = _unique("Antwerp Shipping")
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(),
            source=ExporterSource.SALES,
            name=shared_name,
            country="BE",
            registration_number=f"BE-{uuid.uuid4().hex[:8].upper()}",
        )
    seller = await _seller()
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller, name=shared_name, country="BE"
    )

    report = await _resolve_only(buyer_id)
    assert report.ready == []
    [blocked] = report.needs_a_person
    assert blocked.name_candidates
    assert "confirm or reject by hand" in blocked.problems[0]

    # --apply skips it rather than guessing.
    counts = await _apply_only(report, run_id="test-name-skip")
    assert counts["mapped"] == 0
    assert await _mapping(buyer_id) is None


async def test_a_confirmed_name_match_is_mapped_and_marked_as_a_persons_decision():
    """"The machine matched these" and "a person agreed to merge these" are different
    claims about the same data, so the rule records which."""
    shared_name = _unique("Hamburg Imports")
    existing = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            existing,
            source=ExporterSource.SALES,
            name=shared_name,
            country="DE",
            registration_number=f"DE-{uuid.uuid4().hex[:8].upper()}",
        )
    seller = await _seller()
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller, name=shared_name, country="DE"
    )

    report = await _resolve_only(buyer_id)
    counts = await _apply_only(
        report, run_id="test-name-confirmed", confirmed={buyer_id: existing}
    )
    assert counts["mapped"] == 1
    assert counts["companies_created"] == 0
    mapping = await _mapping(buyer_id)
    assert mapping.company_id == existing
    assert mapping.match_rule is BuyerMatchRule.NAME_CONFIRMED
    assert (await _deal(deal_id)).buyer_company_id == existing


async def test_a_buyer_resolving_to_its_own_deals_seller_is_refused():
    """§17.2 step 5. ``ck_deal_buyer_is_not_the_seller`` would refuse the write; this
    catches it in the report, where a person can correct the row."""
    pan = _pan()
    seller = await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            seller,
            {"name": _unique("Self Dealing"), "country": "IN", "pan": pan},
            actor_id="test",
        )
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller, name=_unique("Self Dealing"), country="IN", tax_id=pan
    )

    report = await _resolve_only(buyer_id)
    assert report.ready == []
    [blocked] = report.needs_a_person
    assert "its own seller" in blocked.problems[0] or "own seller" in blocked.problems[0]

    counts = await _apply_only(report, run_id="test-self")
    assert counts["mapped"] == 0


# ── Buyer checks and terminal deals (§17.2) ───────────────────────────────────


async def test_a_buyers_checks_become_the_companys_without_touching_the_row():
    """§17.2's "Buyer checks": set ``subject_company_id``, leave ``entity_type``,
    ``entity_reference`` and ``subject_snapshot`` exactly as they are. Every read
    already prefers ``subject_company_id`` when it is set."""
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.verification_result import (
        VerificationResult,
    )

    seller = await _seller()
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller,
        name=_unique("Checked Buyer"),
        country="NL",
        registration_number=f"KVK-{uuid.uuid4().hex[:8].upper()}",
    )
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.SANCTIONS,
            VerificationEntityType.BUYER,
            buyer_id,
            provider="manual",
            payload={"status": "PASSED"},
            actor_id="compliance-1",
            evidence=VerificationEvidence(note="Screened before the migration."),
        )

    report = await _resolve_only(buyer_id)
    counts = await _apply_only(report, run_id="test-checks")
    assert counts["results_linked"] == 1

    company_id = (await _mapping(buyer_id)).company_id
    async with db_services.AsyncSessionLocal() as db:
        [result] = list(
            await db.scalars(
                select(VerificationResult).where(
                    VerificationResult.entity_reference == buyer_id
                )
            )
        )
    assert result.subject_company_id == company_id
    # Untouched, exactly as §17.2 requires.
    assert result.entity_type is VerificationEntityType.BUYER
    assert result.entity_reference == buyer_id


async def test_a_terminal_deal_is_linked_without_its_snapshot_changing():
    """A handed-over deal's buyer company is filled in — ``buyer_company_id`` goes
    from ``NULL`` to a value once, which the set-once trigger allows — and its
    ``handover_snapshot`` is untouched, because that is what the lending team was
    given (P2-7)."""
    seller = await _seller()
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller,
        name=_unique("Withdrawn Buyer"),
        country="NL",
        registration_number=f"KVK-{uuid.uuid4().hex[:8].upper()}",
    )
    from app.modules.onboarding.domain.entities.deal_enums import DealStage

    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.WITHDRAWN, reason="not proceeding", actor_id="rm-1"
        )
    before = await _deal(deal_id)
    assert before.buyer_company_id is None

    report = await _resolve_only(buyer_id)
    counts = await _apply_only(report, run_id="test-terminal")
    assert counts["mapped"] == 1

    after = await _deal(deal_id)
    # Migration 0039: the terminal freeze refuses a *change* to this column but allows
    # NULL -> a value once, the same rule 0029 gave `handover_snapshot`. Without it the
    # migration could not link a closed deal at all, and §17.2's first validation query
    # could never reach 0 — which is how this was found.
    assert after.buyer_company_id is not None
    assert after.handover_snapshot == before.handover_snapshot

    # And it is still frozen against a *change*. Through raw SQL, because the service
    # refuses a terminal deal for its stage first — an earlier and different objection
    # — so the service path cannot show that the trigger is doing its job.
    import psycopg2
    import psycopg2.errors

    from app.platform.configuration.config import get_settings

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    connection = psycopg2.connect(url)
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException) as caught:
                cursor.execute(
                    "UPDATE onboarding.deal SET buyer_company_id = %s WHERE id = %s",
                    (str(uuid.uuid4()), str(deal_id)),
                )
            assert "does not change" in str(caught.value) or "immutable" in str(caught.value)
    finally:
        connection.close()


# ── Idempotency and rollback (§17.2) ──────────────────────────────────────────


async def test_re_running_creates_nothing():
    """§17.2's own acceptance criterion, and the reason ``deal_buyer_id`` is the
    mapping table's primary key rather than a plain column."""
    seller = await _seller()
    _deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller,
        name=_unique("Idempotent Buyer"),
        country="NL",
        registration_number=f"KVK-{uuid.uuid4().hex[:8].upper()}",
    )
    first = await _apply_only(await _resolve_only(buyer_id), run_id="test-again-1")
    assert first["companies_created"] == 1

    # The second run does not even see the row: `resolve` skips what is mapped.
    second_report = await _resolve_only(buyer_id)
    assert second_report.resolutions == []
    second = await _apply_only(second_report, run_id="test-again-2")
    assert second == {
        "companies_created": 0,
        "contacts_created": 0,
        "mapped": 0,
        "deals_linked": 0,
        "results_linked": 0,
        "skipped_deal_changed": 0,
    }


async def test_rollback_reports_what_a_run_did_and_writes_nothing():
    """§17.2's logical rollback is **not available**, and this is the test that found it.

    The plan allowed for it — "needs the freeze trigger to allow NULL→value only, so
    do the rollback before enabling it, or restore" — and in the shipped schema both
    triggers are on: `trg_deal_buyer_company_set_once` and
    `trg_verification_result_input_immutability`. So neither column can be set back to
    NULL.

    An earlier version of this command attempted both updates. It would have failed
    partway through, after clearing some results, leaving the operator unsure which
    half had happened. Reporting the truth is strictly better than a rollback that
    half-works.
    """
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.verification_result import (
        VerificationResult,
    )

    seller = await _seller()
    deal_id, buyer_id = await _deal_with_legacy_buyer(
        seller,
        name=_unique("Rollback Buyer"),
        country="NL",
        registration_number=f"KVK-{uuid.uuid4().hex[:8].upper()}",
    )
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.AML,
            VerificationEntityType.BUYER,
            buyer_id,
            provider="manual",
            payload={"status": "PASSED"},
            actor_id="compliance-1",
            evidence=VerificationEvidence(note="Screened before the migration."),
        )
    # A fresh run id each time: the mapping table is append-only, so a literal one
    # would still carry this test's rows from every previous run of the suite and the
    # counts would climb by one each time.
    run_id = f"test-rollback-{uuid.uuid4().hex[:8]}"
    await _apply_only(await _resolve_only(buyer_id), run_id=run_id)
    assert (await _deal(deal_id)).buyer_company_id is not None

    async with db_services.AsyncSessionLocal() as db:
        counts = await rollback(db, run_id=run_id)
    assert counts["mapped"] == 1
    assert counts["deals_linked"] == 1
    assert counts["results_linked"] == 1
    assert counts["companies_created"] == 1

    # Nothing was undone, which is the point: every link the run made is still there.
    company_id = (await _mapping(buyer_id)).company_id
    assert (await _deal(deal_id)).buyer_company_id == company_id
    async with db_services.AsyncSessionLocal() as db:
        [result] = list(
            await db.scalars(
                select(VerificationResult).where(
                    VerificationResult.entity_reference == buyer_id
                )
            )
        )
    assert result.subject_company_id == company_id

    # And an unknown run reports nothing rather than erroring.
    async with db_services.AsyncSessionLocal() as db:
        empty = await rollback(db, run_id=f"never-ran-{uuid.uuid4().hex[:8]}")
    assert empty["mapped"] == 0


async def test_the_validation_queries_run_and_report_counts():
    """§17.2's checks. They are asserted to **run and return numbers** rather than to
    be zero: this shared database holds a thousand unmigrated legacy buyers from other
    suites, so "every count is 0" is a claim about a migrated environment, not about
    this one. Running them is what this test protects — a query that no longer parses
    would otherwise be discovered on the night of the migration."""
    async with db_services.AsyncSessionLocal() as db:
        results = await validate(db)
    # Seven from §17.2, and two from R-07: the map and the BUYER results agree with
    # the deal's own buyer company.
    assert len(results) == 9
    for label, count in results:
        assert isinstance(count, int), label
        assert count >= 0, label
