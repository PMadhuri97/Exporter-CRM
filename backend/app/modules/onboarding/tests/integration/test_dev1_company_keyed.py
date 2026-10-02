"""Company-keyed checks and buyer-only companies — Developer 1, plans P4-5 and P4-11
(decision D; allocation tasks 1.18, 1.19).

* **P4-5.** Every new company-subject result names its company
  (``subject_company_id``); the seam, the facts, the company's verification list and
  a decision's evidence read by that, with legacy rows (``subject_company_id IS
  NULL``) still found by ``entity_reference``. A legacy ``deal_buyer`` result names no
  company until the deal-buyer migration (P4-6, Developer 2) maps it — simulated
  here by the one write the database allows (``NULL`` → a company, then frozen) —
  after which it is an input of the buyer **company** in every read, while
  ``buyer_checks`` / ``for_legacy_buyer`` keep reading it for old deals. No existing
  row is rewritten by this code.
* **P4-11.** A company outside the pipeline (buyer-only) runs the same check — cycles,
  screening, evidence, rule B, maker-checker, expiry — with no special-casing, and is
  never promoted: promotion needs a ``PROSPECT``, and such a company is a ``LEAD`` by
  Developer 3's rule (P4-1). When Developer 3's ``pipeline_status`` column exists,
  ``_buyer_only_company`` sets it, so these tests run on the real thing with no edit.
* **``is_clear_current``** for every state: no Clear, awaiting approval, rejected,
  current, expired, superseded by a new cycle, required checks incomplete.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import psycopg2
import psycopg2.extras
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.decision_evidence import DecisionEvidenceReader
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.events import publisher as publisher_module
from app.modules.onboarding.exceptions import BackgroundCheckPrerequisitesUnmetError
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import record_required_checks
from app.modules.onboarding.tests.integration._dev1_support import (
    CHECKER,
    MAKER,
    answer_screening,
    clear,
    flag,
    gauge,
    inputs,
    propose,
    ready_to_clear,
    start_cycle,
    start_review,
)
from app.modules.onboarding.tests.integration._l4b_support import BASE, deal_buyer, pg
from app.platform.authentication.models import UserRole
from app.platform.configuration import config
from app.platform.database import services as db_services
from app.platform.messaging.ports import InMemoryEventBus
from app.platform.messaging.schemas import EventType
from app.shared import clock

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState
BUYER_TAX_ID = "ABCDE1234F"


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> InMemoryEventBus:
    injected = InMemoryEventBus()
    monkeypatch.setattr(publisher_module, "get_event_bus", lambda: injected)
    return injected


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _buyer_only_company() -> uuid.UUID:
    """A company outside the sales pipeline. Developer 3's P4-1 makes such a company a
    ``LEAD`` that has never been qualified or contacted (a database check); until that
    column lands this is exactly that state, and once it does it is set as well."""
    company_id = await make_company()
    with pg() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'onboarding' "
            "AND table_name = 'exporter_profile' AND column_name = 'pipeline_status'"
        )
        if cursor.fetchone():  # pragma: no cover — switches on with F3
            cursor.execute(
                "UPDATE onboarding.exporter_profile SET pipeline_status = 'NOT_IN_PIPELINE' "
                "WHERE customer_id = %s",
                (str(company_id),),
            )
    return company_id


async def _buyer_result(buyer_id, verification_type=VerificationType.SANCTIONS, status="PASSED"):
    """A legacy deal-buyer check, recorded the way the deal page records one today."""
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).trigger_verification(
            verification_type,
            VerificationEntityType.BUYER,
            buyer_id,
            provider="manual",
            payload={"status": status},
            actor_id="buyer-checker",
            evidence=VerificationEvidence(note="Buyer screened."),
        )


def _map_to_company(result_id, company_id) -> None:
    """What the deal-buyer migration (P4-6) does: the one write the database allows on
    a recorded result's subject — ``NULL`` to a company, once."""
    with pg() as cursor:
        cursor.execute(
            "UPDATE onboarding.verification_result SET subject_company_id = %s WHERE id = %s",
            (str(company_id), str(result_id)),
        )


async def _facts(company_id, now=None):
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceFactsService(db).for_company(company_id, now or clock.now())


async def _legacy_facts(deal_buyer_id):
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceFactsService(db).for_legacy_buyer(deal_buyer_id, clock.now())


async def _buyer_checks(deal_buyer_id):
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceInputsService(db).buyer_checks(deal_buyer_id)


async def _journey(company_id) -> ExporterJourney:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.journey).where(ExporterProfile.customer_id == company_id)
        )


def _journey_rows(company_id) -> int:
    with pg() as cursor:
        cursor.execute(
            "SELECT count(*) FROM onboarding.exporter_lifecycle_history "
            "WHERE customer_id = %s AND dimension = 'journey'",
            (str(company_id),),
        )
        return cursor.fetchone()[0]


# ── P4-5: every new company-subject result names its company ────────────────


async def test_a_new_company_result_names_its_company_seller_or_buyer_only():
    seller = await make_company()
    buyer_only = await _buyer_only_company()
    for company_id in (seller, buyer_only):
        [result] = await record_required_checks(company_id, types=("KYB",))
        assert result.subject_company_id == company_id
        assert result.subject_company == company_id
        assert result.cycle_id is not None  # stamped in that company's cycle


async def test_a_legacy_buyer_result_names_no_company_and_stays_a_legacy_read():
    seller, _deal, buyer_id = await deal_buyer(tax_id=BUYER_TAX_ID)
    result = await _buyer_result(buyer_id)
    assert result.subject_company_id is None and result.cycle_id is None
    # Not an input of the seller's check (background-check.md §12.1 invariant 3) …
    assert result.id not in {v.verification_result_id for v in (await inputs(seller)).verifications}
    # … and still the legacy buyer's, through both legacy reads.
    assert result.id in {v.verification_result_id for v in await _buyer_checks(buyer_id)}
    assert (await _legacy_facts(buyer_id)).sanctions == "PASSED"


async def test_a_mapped_buyer_result_is_its_companys_input_everywhere():
    """The deal-buyer migration maps a legacy buyer to a company: from then on that
    result is one of the company's checks — in its inputs, its facts and its list —
    while old deals keep reading it as their buyer's."""
    seller, _deal, buyer_id = await deal_buyer(tax_id=BUYER_TAX_ID)
    buyer_company = await _buyer_only_company()
    result = await _buyer_result(buyer_id)
    _map_to_company(result.id, buyer_company)

    company_inputs = await inputs(buyer_company)
    [as_input] = [v for v in company_inputs.verifications if v.verification_result_id == result.id]
    assert as_input.entity_type == "BUYER"
    assert as_input.cycle_id == company_inputs.current_cycle_id  # cycle 1 by the read rule
    assert (await _facts(buyer_company)).sanctions == "PASSED"
    assert result.id not in {v.verification_result_id for v in (await inputs(seller)).verifications}
    # Legacy reads are untouched.
    assert result.id in {v.verification_result_id for v in await _buyer_checks(buyer_id)}
    assert (await _legacy_facts(buyer_id)).sanctions == "PASSED"
    async with db_services.AsyncSessionLocal() as db:
        listed = await VerificationService(db).list_verification_results(
            VerificationEntityType.EXPORTER, buyer_company
        )
    assert result.id in {row.id for row in listed}

    # Set once, then frozen: it cannot be re-pointed or unset.
    other = await make_company()
    for value in (str(other), None):
        with pg() as cursor, pytest.raises(psycopg2.Error):
            cursor.execute(
                "UPDATE onboarding.verification_result SET subject_company_id = %s WHERE id = %s",
                (value, str(result.id)),
            )


async def test_old_and_new_records_together_and_across_cycles():
    """A company with a legacy row (no subject company, no cycle), a mapped buyer row
    and a new company-keyed row: all three are cycle 1's; a Re-KYC starts cycle 2 with
    none of them."""
    _seller, _deal, buyer_id = await deal_buyer()
    company_id = await make_company()
    legacy_id = uuid.uuid4()
    with pg() as cursor:
        cursor.execute(
            "INSERT INTO onboarding.verification_result (id, verification_type, entity_type, "
            " entity_reference, provider, status, performed_at, raw_result, normalized_result) "
            "VALUES (%s, 'KYB', 'EXPORTER', %s, 'manual', 'PASSED', now() - interval '1 day', "
            " '{}'::jsonb, '{}'::jsonb)",
            (str(legacy_id), str(company_id)),
        )
    mapped = await _buyer_result(buyer_id, VerificationType.AML)
    _map_to_company(mapped.id, company_id)
    [new] = await record_required_checks(company_id, types=("SANCTIONS",))
    assert new.subject_company_id == company_id

    before = await inputs(company_id)
    ids = {v.verification_result_id for v in before.verifications}
    assert {legacy_id, mapped.id, new.id} <= ids
    assert {v.cycle_id for v in before.verifications} == {before.current_cycle_id}
    facts = await _facts(company_id)
    assert (facts.sanctions, facts.aml) == ("PASSED", "PASSED")

    started = await start_cycle(company_id)
    after = await inputs(company_id)
    assert after.current_cycle_id == started.cycle.id and after.verifications == ()
    facts = await _facts(company_id)
    assert (facts.sanctions, facts.aml) == ("MISSING", "MISSING")


async def test_rule_b_counts_a_mapped_buyer_check_and_the_evidence_names_its_recorder():
    """One set of checks per company: a buyer company's Clear can rest on the sanctions
    check recorded on a deal before it was a company; the decision's evidence resolves
    it and says who recorded it (on the seller's timeline, with the deal)."""
    _seller, _deal, buyer_id = await deal_buyer()
    buyer_company = await _buyer_only_company()
    mapped = await _buyer_result(buyer_id, VerificationType.SANCTIONS)
    _map_to_company(mapped.id, buyer_company)
    await answer_screening(buyer_company)
    await record_required_checks(buyer_company, types=("KYB", "AML"))
    await start_review(buyer_company)
    decision = await clear(buyer_company)

    async with db_services.AsyncSessionLocal() as db:
        evidence = await DecisionEvidenceReader(db).for_decision(buyer_company, decision.id)
    [pinned] = [
        item.verification for item in evidence.items
        if item.verification is not None
        and item.verification.verification_result_id == mapped.id
    ]
    assert pinned.recorded_by == "buyer-checker"


async def test_a_review_of_a_mapped_buyer_result_goes_on_the_buyer_companys_timeline():
    seller, deal_id, buyer_id = await deal_buyer()
    buyer_company = await make_company()
    result = await _buyer_result(buyer_id)
    _map_to_company(result.id, buyer_company)
    async with db_services.AsyncSessionLocal() as db:
        await VerificationService(db).record_review(
            result.id, reviewed_by=CHECKER.user_id, review_status=VerificationReviewStatus.ACCEPTED
        )
    with pg() as cursor:
        cursor.execute(
            "SELECT customer_id, deal_id FROM onboarding.exporter_lifecycle_history "
            "WHERE dimension = 'verification' "
            "AND event_metadata->>'verification_result_id' = %s ORDER BY created_at",
            (str(result.id),),
        )
        rows = cursor.fetchall()
    # Recorded on the seller's timeline (as a legacy buyer check), reviewed on the buyer
    # company's — each with the deal as context.
    assert [(str(c), str(d)) for c, d in rows] == [
        (str(seller), str(deal_id)),
        (str(buyer_company), str(deal_id)),
    ]


async def test_the_company_list_serves_a_mapped_buyer_result_masked_per_role(
    client: AsyncClient, tokens
):
    _seller, _deal, buyer_id = await deal_buyer(tax_id=BUYER_TAX_ID)
    buyer_company = await make_company()
    result = await _buyer_result(buyer_id)
    _map_to_company(result.id, buyer_company)
    url = f"{BASE}/verifications"
    params = {"entity_type": "EXPORTER", "entity_reference": str(buyer_company)}

    compliance = await client.get(url, params=params, headers=auth_header(tokens[UserRole.COMPLIANCE]))
    assert compliance.status_code == 200, compliance.text
    [row] = [r for r in compliance.json()["results"] if r["id"] == str(result.id)]
    assert row["subject_company_id"] == str(buyer_company)
    assert row["entity_type"] == "BUYER"
    assert row["subject_snapshot"]["tax_id"] == BUYER_TAX_ID

    rm = await client.get(url, params=params, headers=auth_header(tokens[UserRole.OPERATIONS]))
    assert rm.status_code == 200
    [masked] = [r for r in rm.json()["results"] if r["id"] == str(result.id)]
    assert masked["subject_snapshot"]["tax_id"] != BUYER_TAX_ID
    assert BUYER_TAX_ID not in rm.text

    developer = await client.get(url, params=params, headers=auth_header(tokens[UserRole.DEVELOPER]))
    assert developer.status_code == 403


# ── P4-11: a buyer-only company, the full check, never promoted ──────────────


async def test_a_buyer_only_company_is_cleared_with_approval_and_never_promoted(
    bus: InMemoryEventBus,
):
    company_id = await _buyer_only_company()
    assert await _journey(company_id) is ExporterJourney.LEAD

    await ready_to_clear(company_id)  # screening, rule B's checks, the start
    proposal = await propose(company_id)
    assert (await _facts(company_id)).is_clear is False  # awaiting approval
    decision = await clear_approved(company_id, proposal.id)
    assert (decision.decided_by, decision.approved_by) == (MAKER.user_id, CHECKER.user_id)
    assert decision.expires_at is not None

    facts = await _facts(company_id)
    assert facts.is_clear_current and facts.clear_expires_at == decision.expires_at
    assert await _journey(company_id) is ExporterJourney.LEAD
    assert _journey_rows(company_id) == 0
    assert [e for e in bus.published if e.event_type is EventType.COMPANY_BECAME_CUSTOMER] == []

    # A Re-KYC reopens it; cleared again in cycle 2 — still out of the journey.
    started = await start_cycle(company_id)
    assert await gauge(company_id) is State.IN_REVIEW
    await answer_screening(company_id)
    await record_required_checks(company_id)
    second = await clear(company_id)
    assert second.cycle_id == started.cycle.id
    assert await _journey(company_id) is ExporterJourney.LEAD and _journey_rows(company_id) == 0


async def clear_approved(company_id, proposal_id):
    async with db_services.AsyncSessionLocal() as db:
        approved = await BackgroundCheckService(db).approve(
            company_id, proposal_id, actor_id=CHECKER.user_id, actor_role=CHECKER.role
        )
    return approved.decision


async def test_a_buyer_only_company_is_flagged_and_held_with_approval():
    company_id = await ready_to_clear(await _buyer_only_company())
    await flag(company_id)
    await flag(company_id, State.ON_HOLD, reason="regulator")
    assert await gauge(company_id) is State.ON_HOLD
    assert await _journey(company_id) is ExporterJourney.LEAD


async def test_a_buyer_only_company_needs_rule_b_like_any_other():
    company_id = await _buyer_only_company()
    await answer_screening(company_id)
    await start_review(company_id)
    with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as caught:
        await propose(company_id)
    assert caught.value.extensions["unmet"] == ["kyb_passed", "aml_passed", "sanctions_passed"]


async def test_a_buyer_only_company_is_on_the_re_kyc_list(client: AsyncClient, tokens, monkeypatch):
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 3)
    company_id = await ready_to_clear(await _buyer_only_company())
    await clear(company_id)
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 365)
    try:
        response = await client.get(
            f"{BASE}/background-check/due",
            params={"limit": 100},
            headers=auth_header(tokens[UserRole.COMPLIANCE]),
        )
        assert response.status_code == 200
        [row] = [r for r in response.json()["companies"] if r["company_id"] == str(company_id)]
        assert row["journey"] == "LEAD" and row["is_expired"] is False
    finally:
        async with db_services.AsyncSessionLocal() as db:
            await BackgroundCheckService(db).reopen(
                company_id, reason="test clean-up", actor_id=MAKER.user_id,
                actor_role=UserRole.COMPLIANCE,
            )


# ── is_clear_current for every state ─────────────────────────────────────────


async def test_is_clear_current_through_every_state():
    company_id = await make_company()
    facts = await _facts(company_id)
    assert (facts.background_check, facts.is_clear_current) == ("NOT_STARTED", False)

    # Required checks incomplete: no Clear can even be proposed.
    await answer_screening(company_id)
    await start_review(company_id)
    with pytest.raises(BackgroundCheckPrerequisitesUnmetError):
        await propose(company_id)
    assert not (await _facts(company_id)).is_clear_current

    # Awaiting approval: not Clear. Rejected: still not.
    await record_required_checks(company_id)
    proposal = await propose(company_id)
    assert not (await _facts(company_id)).is_clear_current
    async with db_services.AsyncSessionLocal() as db:
        await BackgroundCheckService(db).reject(
            company_id, proposal.id, reason="not yet", actor_id=CHECKER.user_id,
            actor_role=CHECKER.role,
        )
    assert not (await _facts(company_id)).is_clear_current

    # Approved: current — until it expires.
    await clear(company_id)
    facts = await _facts(company_id)
    assert facts.is_clear and facts.is_clear_current
    expired = await _facts(company_id, facts.clear_expires_at + timedelta(seconds=1))
    assert expired.is_clear and not expired.is_clear_current

    # Superseded by a new cycle: reopened, not current.
    await start_cycle(company_id)
    facts = await _facts(company_id)
    assert facts.background_check == "IN_REVIEW" and not facts.is_clear_current
    assert facts.clear_expires_at is None
