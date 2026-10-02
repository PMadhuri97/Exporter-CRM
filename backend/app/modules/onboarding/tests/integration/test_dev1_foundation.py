"""F1 — the compliance foundation (allocation §3, plan P0-2, P0-5, IQ-18) — Developer 1.

* ``verification_result.subject_company_id``: a nullable company FK, **set once then
  frozen** by ``trg_verification_result_input_immutability`` — tried in raw SQL;
* ``exporter_profile.background_check_expires_at`` exists with its index;
* ``ComplianceFactsReader`` answers for real companies and legacy buyers;
* promotion to ``CUSTOMER`` requires a **current** Clear (IQ-18), driven by the
  injectable clock rather than by waiting a year;
* ``approve_as`` and the second-compliance-user fixture (P0-5);
* DEVELOPER is not served the background check's new history dimensions (D8).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.domain.compliance_facts import LEGACY_CLEAR_VALIDITY
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationType
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationOutcomeValue,
)
from app.modules.onboarding.domain.history_dimensions import (
    ALL_DIMENSIONS,
    HIDDEN_FROM_DEVELOPER,
)
from app.modules.onboarding.exceptions import (
    ComplianceInputsBuyerNotFoundError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.tests.fixtures import compliance as compliance_fixtures
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import (
    insert_company,
    make_company,
    make_prospect,
)
from app.modules.onboarding.tests.fixtures.compliance import ComplianceUser, approve_as
from app.modules.onboarding.tests.integration._dev1_support import (
    CHECKER,
    MAKER,
    cleared_company,
    gauge,
    ready_to_clear,
    start_cycle,
)
from app.modules.onboarding.tests.integration._l4b_support import (
    BASE,
    deal_buyer,
    exporter_result,
    insert_result,
    pg,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared import clock
from app.shared.clock import FixedClock, use_clock

pytestmark = pytest.mark.asyncio

# The P0-5 fixtures, made available to this module by name.
compliance_maker = compliance_fixtures.compliance_maker
compliance_checker = compliance_fixtures.compliance_checker
second_compliance_user = compliance_fixtures.second_compliance_user


# ── Schema: subject_company_id, set once then frozen ─────────────────────────


async def test_subject_company_id_can_be_set_once_and_never_changed():
    with pg() as cursor:
        company = insert_company(cursor)
        other = insert_company(cursor)
        result_id = insert_result(cursor, entity_type="BUYER")

        # NULL → value is allowed: what the buyer migration (P4-6) needs.
        cursor.execute(
            "UPDATE onboarding.verification_result SET subject_company_id = %s WHERE id = %s",
            (str(company), str(result_id)),
        )
        # value → another value is refused …
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable once set"):
            cursor.execute(
                "UPDATE onboarding.verification_result SET subject_company_id = %s WHERE id = %s",
                (str(other), str(result_id)),
            )
        # … and so is value → NULL.
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable once set"):
            cursor.execute(
                "UPDATE onboarding.verification_result SET subject_company_id = NULL WHERE id = %s",
                (str(result_id),),
            )
        cursor.execute(
            "SELECT subject_company_id FROM onboarding.verification_result WHERE id = %s",
            (str(result_id),),
        )
        assert cursor.fetchone()[0] == str(company)


async def test_subject_company_id_must_name_a_company():
    with pg() as cursor:
        result_id = insert_result(cursor, entity_type="BUYER")
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                "UPDATE onboarding.verification_result SET subject_company_id = %s WHERE id = %s",
                (str(uuid.uuid4()), str(result_id)),
            )


async def test_the_evidence_and_snapshot_stay_frozen_after_the_trigger_was_recreated():
    """0023 re-created the trigger; the columns 0021 froze are still in it."""
    with pg() as cursor:
        result_id = insert_result(cursor, entity_type="BUYER")
        cursor.execute(
            "UPDATE onboarding.verification_result SET evidence_note = 'first' WHERE id = %s",
            (str(result_id),),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable once set"):
            cursor.execute(
                "UPDATE onboarding.verification_result SET evidence_note = 'second' WHERE id = %s",
                (str(result_id),),
            )


async def test_background_check_expires_at_exists_nullable_and_indexed():
    with pg() as cursor:
        cursor.execute(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_schema = 'onboarding' AND table_name = 'exporter_profile' "
            "AND column_name = 'background_check_expires_at'"
        )
        assert cursor.fetchone() == ("YES", "timestamp with time zone")
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'onboarding' "
            "AND indexname = 'ix_exporter_profile_background_check_expires_at'"
        )
        assert "background_check_expires_at IS NOT NULL" in cursor.fetchone()[0]


# ── ComplianceFactsReader on real data ───────────────────────────────────────


async def _facts(company_id: uuid.UUID, now=None):
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceFactsService(db).for_company(company_id, now or clock.now())


async def test_a_new_company_has_no_check_and_no_sanctions_or_aml():
    facts = await _facts(await make_company())
    assert facts.background_check == "NOT_STARTED"
    assert not facts.is_clear and not facts.is_clear_current
    assert facts.clear_expires_at is None
    assert (facts.sanctions, facts.aml) == ("MISSING", "MISSING")


async def test_sanctions_and_aml_follow_the_latest_real_result():
    company_id = await make_company()
    await exporter_result(company_id, verification_type=VerificationType.SANCTIONS)
    await exporter_result(company_id, verification_type=VerificationType.AML, status="FAILED")
    facts = await _facts(company_id)
    assert (facts.sanctions, facts.aml) == ("PASSED", "FAILED")

    # A later PASSED AML result is the latest real one, so it wins.
    await exporter_result(company_id, verification_type=VerificationType.AML)
    assert (await _facts(company_id)).aml == "PASSED"


async def test_a_clear_is_current_for_a_year_from_its_clearing_decision():
    company_id = await cleared_company(await make_company())
    facts = await _facts(company_id)
    assert facts.background_check == "CLEAR"
    assert facts.is_clear and facts.is_clear_current

    # The expiry is the clearing decision's time + one year (BQ-5).
    async with db_services.AsyncSessionLocal() as db:
        decided_at = (await BackgroundCheckReader(db).standing(company_id)).decided_at
    assert facts.clear_expires_at == decided_at + LEGACY_CLEAR_VALIDITY

    later = await _facts(company_id, facts.clear_expires_at + timedelta(seconds=1))
    assert later.is_clear and not later.is_clear_current


async def test_an_unknown_company_or_buyer_is_refused():
    with pytest.raises(ExporterProfileNotFoundError):
        await _facts(uuid.uuid4())
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ComplianceInputsBuyerNotFoundError):
            await ComplianceFactsService(db).for_legacy_buyer(uuid.uuid4(), clock.now())


async def test_a_naive_now_is_refused():
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValueError):
            await ComplianceFactsService(db).for_company(company_id, clock.now().replace(tzinfo=None))


async def test_a_legacy_buyer_is_never_clear_and_reads_its_own_checks():
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
    )
    from app.modules.onboarding.tests.integration._l4b_support import NOTE

    _company_id, _deal_id, buyer_id = await deal_buyer()
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).trigger_verification(
            VerificationType.SANCTIONS,
            VerificationEntityType.BUYER,
            buyer_id,
            payload={"status": "PASSED"},
            actor_id="tester",
            evidence=NOTE,
        )
    async with db_services.AsyncSessionLocal() as db:
        facts = await ComplianceFactsService(db).for_legacy_buyer(buyer_id, clock.now())
    assert facts.background_check == "NOT_STARTED"
    assert not facts.is_clear and not facts.is_clear_current and facts.clear_expires_at is None
    assert (facts.sanctions, facts.aml) == ("PASSED", "MISSING")


# ── Promotion requires a current Clear (IQ-18) ───────────────────────────────


async def _qualify(company_id: uuid.UUID) -> None:
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            company_id, QualificationOutcomeValue.QUALIFIED, actor_id="sales"
        )


async def _journey(company_id: uuid.UUID) -> ExporterJourney:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.journey).where(ExporterProfile.customer_id == company_id)
        )


async def test_qualifying_a_company_with_a_current_clear_promotes_it():
    company_id = await cleared_company(await make_company())
    await _qualify(company_id)
    assert await _journey(company_id) is ExporterJourney.CUSTOMER


async def test_qualifying_a_company_whose_clear_has_expired_does_not_promote_it():
    company_id = await cleared_company(await make_company())
    with use_clock(FixedClock(clock.now() + LEGACY_CLEAR_VALIDITY + timedelta(days=1))):
        await _qualify(company_id)
    assert await _journey(company_id) is ExporterJourney.PROSPECT
    assert await gauge(company_id) is BackgroundCheckState.CLEAR


async def test_clearing_a_prospect_still_promotes_it_in_the_same_move():
    company_id = await ready_to_clear(await make_prospect())
    await approve_as(CHECKER, company_id, maker=MAKER)
    assert await _journey(company_id) is ExporterJourney.CUSTOMER


# ── approve_as and the second compliance user (P0-5) ─────────────────────────


async def test_approve_as_clears_with_two_different_compliance_users(
    compliance_maker: ComplianceUser, compliance_checker: ComplianceUser
):
    assert compliance_maker.user_id != compliance_checker.user_id
    assert compliance_maker.role is compliance_checker.role is UserRole.COMPLIANCE
    company_id = await ready_to_clear(await make_company())
    view = await approve_as(compliance_checker, company_id, maker=compliance_maker)
    assert view.to_value is BackgroundCheckState.CLEAR
    # P3-1b: the maker decided, the checker approved — two people on one decision.
    assert view.decided_by == compliance_maker.user_id
    assert view.approved_by == compliance_checker.user_id


async def test_approve_as_refuses_one_user_as_maker_and_checker(
    compliance_maker: ComplianceUser, second_compliance_user: ComplianceUser
):
    assert second_compliance_user.user_id != compliance_maker.user_id
    with pytest.raises(AssertionError, match="two different users"):
        await approve_as(compliance_maker, await make_company(), maker=compliance_maker)


# ── History dimensions (F1) and D8 ───────────────────────────────────────────


async def test_the_five_f1_dimensions_are_listed_and_the_compliance_ones_hidden():
    for dimension in ("check_cycle", "background_check_approval", "gst_registration", "trade", "pipeline"):
        assert dimension in ALL_DIMENSIONS
    assert {"check_cycle", "background_check_approval"} <= HIDDEN_FROM_DEVELOPER
    assert not {"gst_registration", "trade", "pipeline"} & HIDDEN_FROM_DEVELOPER
    assert all(len(dimension) <= 32 for dimension in ALL_DIMENSIONS)  # varchar(32)


async def test_developer_is_not_served_check_cycle_rows(client: AsyncClient):
    company_id = await cleared_company(await make_company())
    await start_cycle(company_id)
    url = f"{BASE}/exporters/{company_id}/history"

    staff = await client.get(url, headers=auth_header(await token_with_role(client, UserRole.COMPLIANCE)))
    assert staff.status_code == 200
    assert "check_cycle" in {entry["dimension"] for entry in staff.json()["entries"]}

    developer = await client.get(url, headers=auth_header(await token_with_role(client, UserRole.DEVELOPER)))
    assert developer.status_code == 200
    dimensions = {entry["dimension"] for entry in developer.json()["entries"]}
    assert not dimensions & HIDDEN_FROM_DEVELOPER
    filtered = await client.get(
        url, params={"dimension": "check_cycle"},
        headers=auth_header(await token_with_role(client, UserRole.DEVELOPER)),
    )
    assert filtered.json()["entries"] == [] and filtered.json()["total"] == 0


async def test_the_facts_are_right_for_the_sample_companies():
    """F1's "done when": the reader answers for the seeded §3.9 companies — A a lead with
    no check, B cleared (and current), C flagged."""
    from app.modules.onboarding.sample_data import COMPANIES, load_sample_data

    await load_sample_data()
    by_slug = {company.slug: company.customer_id for company in COMPANIES}
    a, b, c = [await _facts(by_slug[slug]) for slug in ("company-a", "company-b", "company-c")]
    assert (a.background_check, a.is_clear) == ("NOT_STARTED", False)
    assert b.background_check == "CLEAR" and b.is_clear and b.is_clear_current
    assert b.clear_expires_at is not None
    assert (c.background_check, c.is_clear, c.is_clear_current) == ("FLAGGED", False, False)
