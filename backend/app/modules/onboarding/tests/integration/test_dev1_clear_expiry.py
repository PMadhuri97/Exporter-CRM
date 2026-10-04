"""Clear expiry and Re-KYC due — Developer 1, plans P3-3a, P3-3b, P3-3c (decision E,
BQ-5, IQ-18).

* **P3-3a.** Every new CLEAR stores ``expires_at`` = ``decided_at`` + the validity
  setting (default 365 days), exactly, and the company's current
  ``background_check_expires_at``; any move away clears the current value; the database
  refuses an expiry on another move or before the decision; migration 0027's backfill
  dates a legacy Clear one year on and is idempotent.
* **P3-3b.** The facts and the standing read the stored expiry (the legacy rule for an
  older Clear); an expired Clear stays ``CLEAR`` — nothing moves the gauge — but is not
  current, and promotion is refused on it.
* **P3-3c.** ``GET /background-check/due`` lists expired and soon-expiring Clears,
  company by company, and the standing serves ``rekyc_due``.

Companies cleared here with a short validity are reopened at the end of each test, so
the shared database's due list does not fill up with them.
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
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
)
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationOutcomeValue
from app.modules.onboarding.migrations import onboarding_0027_dev1_expiry as migration
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._dev1_support import (
    cleared_company,
    gauge,
    move,
    start_cycle,
)
from app.modules.onboarding.tests.integration._l4b_support import BASE, pg
from app.platform.authentication.models import UserRole
from app.platform.configuration import config
from app.platform.database import services as db_services
from app.shared import clock
from app.shared.clock import FixedClock, use_clock

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState
YEAR = timedelta(days=365)


async def _clearing_decision(company_id) -> BackgroundCheckDecision:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(BackgroundCheckDecision)
            .where(
                BackgroundCheckDecision.company_id == company_id,
                BackgroundCheckDecision.to_value == State.CLEAR,
            )
            .order_by(BackgroundCheckDecision.decided_at.desc())
            .limit(1)
        )


async def _current_expiry(company_id):
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.background_check_expires_at).where(
                ExporterProfile.customer_id == company_id
            )
        )


async def _facts(company_id, now=None):
    async with db_services.AsyncSessionLocal() as db:
        return await ComplianceFactsService(db).for_company(company_id, now or clock.now())


async def _cleared_with_validity(monkeypatch, days: int) -> uuid.UUID:
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", days)
    company_id = await cleared_company(await make_company())
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 365)
    return company_id


async def _reopen(company_id) -> None:
    await move(company_id, State.IN_REVIEW, reason="test clean-up")


def _legacy_clear(cursor, company_id, decided_at: str) -> uuid.UUID:
    """A CLEAR recorded the way it was before 0027: no ``expires_at``, and the company's
    current value not yet backfilled."""
    start, cleared = uuid.uuid4(), uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
        " to_value, decided_by, decided_by_kind, source, decided_at) "
        "VALUES (%s, %s, 'NOT_STARTED', 'IN_REVIEW', 'legacy', 'MANUAL', 'MANUAL', %s)",
        (str(start), str(company_id), decided_at),
    )
    cursor.execute(
        "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
        " to_value, decided_by, decided_by_kind, source, reason, risk_rating, "
        " supersedes_decision_id, decided_at) "
        "VALUES (%s, %s, 'IN_REVIEW', 'CLEAR', 'legacy', 'MANUAL', 'MANUAL', 'old', 'LOW', %s, "
        " %s::timestamptz + interval '1 minute')",
        (str(cleared), str(company_id), str(start), decided_at),
    )
    cursor.execute(
        "UPDATE onboarding.exporter_profile SET background_check = 'CLEAR', "
        " background_check_expires_at = NULL WHERE customer_id = %s",
        (str(company_id),),
    )
    return cleared


# ── P3-3a: stored on every new CLEAR ─────────────────────────────────────────


async def test_a_new_clear_stores_its_expiry_and_the_companys_current_value():
    company_id = await cleared_company(await make_company())
    decision = await _clearing_decision(company_id)
    assert decision.expires_at - decision.decided_at == YEAR  # exactly, one timestamp
    assert await _current_expiry(company_id) == decision.expires_at
    await _reopen(company_id)


async def test_the_validity_setting_is_honoured(monkeypatch):
    company_id = await _cleared_with_validity(monkeypatch, 30)
    decision = await _clearing_decision(company_id)
    assert decision.expires_at - decision.decided_at == timedelta(days=30)
    await _reopen(company_id)


async def test_any_move_away_clears_the_current_value_and_never_the_decision():
    company_id = await cleared_company(await make_company())
    decision = await _clearing_decision(company_id)
    await _reopen(company_id)
    assert await _current_expiry(company_id) is None
    assert (await _clearing_decision(company_id)).expires_at == decision.expires_at

    # A Re-KYC on a CLEAR company reopens it too.
    other = await cleared_company(await make_company())
    await start_cycle(other)
    assert await gauge(other) is State.IN_REVIEW
    assert await _current_expiry(other) is None


async def test_the_database_refuses_an_expiry_on_another_move_or_before_the_decision():
    company_id = await make_company()
    with pg() as cursor:
        start = uuid.uuid4()
        cursor.execute(
            "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
            " to_value, decided_by, decided_by_kind, source) "
            "VALUES (%s, %s, 'NOT_STARTED', 'IN_REVIEW', 'x', 'MANUAL', 'MANUAL')",
            (str(start), str(company_id)),
        )
        with pytest.raises(psycopg2.errors.CheckViolation, match="decision_expiry"):
            cursor.execute(
                "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
                " to_value, decided_by, decided_by_kind, source, reason, "
                " supersedes_decision_id, expires_at) "
                "VALUES (%s, %s, 'IN_REVIEW', 'MORE_INFO', 'x', 'MANUAL', 'MANUAL', 'r', %s, "
                " now() + interval '1 day')",
                (str(uuid.uuid4()), str(company_id), str(start)),
            )
        with pytest.raises(psycopg2.errors.CheckViolation, match="decision_expiry"):
            cursor.execute(
                "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
                " to_value, decided_by, decided_by_kind, source, reason, risk_rating, "
                " supersedes_decision_id, decided_at, expires_at) "
                "VALUES (%s, %s, 'IN_REVIEW', 'CLEAR', 'x', 'MANUAL', 'MANUAL', 'r', 'LOW', %s, "
                " now(), now() - interval '1 day')",
                (str(uuid.uuid4()), str(company_id), str(start)),
            )


async def test_the_backfill_dates_a_legacy_clear_one_year_on_and_is_idempotent():
    """BQ-5: a company already cleared expires one year from its last Clear."""
    company_id = await make_company()
    with pg() as cursor:
        cleared = _legacy_clear(cursor, company_id, "2025-03-01T10:00:00+00:00")
        cursor.execute(migration.preview_sql(), ())
        [row] = [r for r in cursor.fetchall() if str(r[0]) == str(company_id)]
        assert str(row[1]) == str(cleared) and row[4] is True  # by the legacy rule
        cursor.execute(migration.BACKFILL_SQL)
        cursor.execute(
            "SELECT background_check_expires_at - (SELECT decided_at FROM "
            " onboarding.background_check_decision WHERE id = %s) "
            "FROM onboarding.exporter_profile WHERE customer_id = %s",
            (str(cleared), str(company_id)),
        )
        assert cursor.fetchone()[0] == YEAR
        # Idempotent: a second run touches this company no more.
        cursor.execute(migration.preview_sql(), ())
        assert str(company_id) not in {str(r[0]) for r in cursor.fetchall()}
        cursor.execute(migration.BACKFILL_SQL)
        cursor.execute(
            "SELECT background_check_expires_at FROM onboarding.exporter_profile "
            "WHERE customer_id = %s",
            (str(company_id),),
        )
        assert cursor.fetchone()[0] is not None  # unchanged by the second run
    assert (await _facts(company_id)).clear_expires_at is not None
    with pg() as cursor:  # leave it out of the due list
        cursor.execute(
            "UPDATE onboarding.exporter_profile SET background_check = 'IN_REVIEW', "
            " background_check_expires_at = NULL WHERE customer_id = %s",
            (str(company_id),),
        )


# ── P3-3b: read, never moved ─────────────────────────────────────────────────


async def test_an_expired_clear_stays_clear_but_is_not_current():
    company_id = await cleared_company(await make_company())
    facts = await _facts(company_id)
    assert facts.is_clear_current
    later = await _facts(company_id, facts.clear_expires_at + timedelta(seconds=1))
    assert later.background_check == "CLEAR" and later.is_clear and not later.is_clear_current
    async with db_services.AsyncSessionLocal() as db:
        standing = await BackgroundCheckReader(db).standing(company_id)
    assert standing.expires_at == facts.clear_expires_at
    assert standing.is_clear_and_current(clock.now())
    assert not standing.is_clear_and_current(facts.clear_expires_at)
    assert await gauge(company_id) is State.CLEAR  # nothing moved it
    await _reopen(company_id)


async def test_the_facts_read_the_stored_expiry(monkeypatch):
    company_id = await _cleared_with_validity(monkeypatch, 10)
    decision = await _clearing_decision(company_id)
    facts = await _facts(company_id)
    assert facts.clear_expires_at == decision.expires_at == decision.decided_at + timedelta(days=10)
    assert not (await _facts(company_id, decision.decided_at + timedelta(days=11))).is_clear_current
    await _reopen(company_id)


async def test_a_legacy_clear_reads_one_year_from_its_decision():
    company_id = await make_company()
    with pg() as cursor:
        cleared = _legacy_clear(cursor, company_id, "2025-06-01T10:00:00+00:00")
    async with db_services.AsyncSessionLocal() as db:
        decided_at = await db.scalar(
            select(BackgroundCheckDecision.decided_at).where(BackgroundCheckDecision.id == cleared)
        )
    facts = await _facts(company_id)
    assert facts.clear_expires_at == decided_at + YEAR
    assert facts.is_clear and not facts.is_clear_current  # expired on 1 June 2026
    with pg() as cursor:
        cursor.execute(
            "UPDATE onboarding.exporter_profile SET background_check = 'IN_REVIEW' "
            "WHERE customer_id = %s",
            (str(company_id),),
        )


async def test_promotion_is_refused_while_the_clear_is_expired(monkeypatch):
    """IQ-18: a cleared LEAD qualified after its Clear expired stays a PROSPECT."""
    company_id = await _cleared_with_validity(monkeypatch, 1)
    with use_clock(FixedClock(clock.now() + timedelta(days=2))):
        async with db_services.AsyncSessionLocal() as db:
            await QualificationService(db).record_outcome(
                company_id, QualificationOutcomeValue.QUALIFIED, actor_id="sales"
            )
    async with db_services.AsyncSessionLocal() as db:
        journey = await db.scalar(
            select(ExporterProfile.journey).where(ExporterProfile.customer_id == company_id)
        )
    assert journey is ExporterJourney.PROSPECT
    assert await gauge(company_id) is State.CLEAR
    await _reopen(company_id)


# ── P3-3c: Re-KYC due ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


async def test_the_due_list_has_the_expired_and_the_soon_expiring_and_not_the_rest(
    client: AsyncClient, tokens, monkeypatch
):
    soon = await _cleared_with_validity(monkeypatch, 1)
    later = await _cleared_with_validity(monkeypatch, 20)
    far = await _cleared_with_validity(monkeypatch, 400)
    reopened = await _cleared_with_validity(monkeypatch, 1)
    await start_cycle(reopened)  # Re-KYC started: no longer due
    try:
        now = clock.now() + timedelta(days=2)
        with use_clock(FixedClock(now)):
            response = await client.get(
                f"{BASE}/background-check/due",
                params={"before": (now + timedelta(days=25)).isoformat(), "limit": 100},
                headers=auth_header(tokens[UserRole.COMPLIANCE]),
            )
        assert response.status_code == 200, response.text
        body = response.json()
        rows = {row["company_id"]: row for row in body["companies"]}
        assert rows[str(soon)]["is_expired"] is True
        assert rows[str(later)]["is_expired"] is False
        assert str(far) not in rows and str(reopened) not in rows
        assert rows[str(soon)]["current_cycle_number"] == 1
        assert rows[str(soon)]["background_check"] == "CLEAR"
        order = [row["company_id"] for row in body["companies"]]
        assert order.index(str(soon)) < order.index(str(later))  # soonest first
        expiries = [row["expires_at"] for row in body["companies"]]
        assert expiries == sorted(expiries)
    finally:
        for company_id in (soon, later, far):
            await _reopen(company_id)


async def test_the_due_list_says_which_renewals_are_for_a_buyer_only_company(
    client: AsyncClient, tokens, monkeypatch
):
    """R-29: a company that exists only as a buyer is screened and renewed like any
    other, and the list says it is not in the pipeline rather than reading as a lead."""
    from app.modules.onboarding.application.company_directory import CompanyDirectoryService
    from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
    from app.modules.onboarding.tests.fixtures.deals import make_deal

    lead = await _cleared_with_validity(monkeypatch, 1)
    async with db_services.AsyncSessionLocal() as db:
        buyer_only = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name=f"Renewing Buyer {uuid.uuid4().hex[:6]}",
                country="NL",
                registration_number=f"KVK-{uuid.uuid4().hex[:8].upper()}",
                created_via_deal_id=await make_deal(),
            ),
            actor_id="rm-1",
        )
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 1)
    await cleared_company(buyer_only)
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 365)
    try:
        now = clock.now() + timedelta(days=2)
        with use_clock(FixedClock(now)):
            response = await client.get(
                f"{BASE}/background-check/due",
                params={"before": (now + timedelta(days=5)).isoformat(), "limit": 100},
                headers=auth_header(tokens[UserRole.OPERATIONS]),
            )
        assert response.status_code == 200, response.text
        rows = {row["company_id"]: row for row in response.json()["companies"]}
        assert rows[str(buyer_only)]["pipeline_status"] == "NOT_IN_PIPELINE"
        assert rows[str(lead)]["pipeline_status"] == "IN_PIPELINE"
    finally:
        for company_id in (lead, buyer_only):
            await _reopen(company_id)


async def test_the_standing_serves_re_kyc_due(client: AsyncClient, tokens, monkeypatch):
    due = await _cleared_with_validity(monkeypatch, 5)
    fresh = await cleared_company(await make_company())
    try:
        for company_id, expected in ((due, True), (fresh, False)):
            body = (
                await client.get(
                    f"{BASE}/exporters/{company_id}/background-check",
                    headers=auth_header(tokens[UserRole.OPERATIONS]),
                )
            ).json()
            assert body["rekyc_due"] is expected
            assert body["value"] == "CLEAR"
    finally:
        await _reopen(due)
        await _reopen(fresh)


async def test_the_due_list_is_staff_only_and_needs_a_time_zone(client: AsyncClient, tokens):
    developer = await client.get(
        f"{BASE}/background-check/due", headers=auth_header(tokens[UserRole.DEVELOPER])
    )
    assert developer.status_code == 403
    rm = await client.get(
        f"{BASE}/background-check/due", headers=auth_header(tokens[UserRole.OPERATIONS])
    )
    assert rm.status_code == 200
    naive = await client.get(
        f"{BASE}/background-check/due",
        params={"before": "2026-11-01T00:00:00"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert naive.status_code == 422


async def test_the_due_list_carries_no_identifier(client: AsyncClient, tokens, monkeypatch):
    import random
    import string

    pan = "".join(random.choice(string.ascii_uppercase) for _ in range(5)) + "1234Z"
    created = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": f"Due Co {uuid.uuid4().hex[:6]}", "country": "IN",
              "pan": pan, "gstins": [f"27{pan}1Z5"]},
        headers={**auth_header(tokens[UserRole.COMPLIANCE]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    company_id = uuid.UUID(created.json()["customer_id"])
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 3)
    await cleared_company(company_id)
    monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 365)
    try:
        response = await client.get(
            f"{BASE}/background-check/due",
            params={"limit": 100},
            headers=auth_header(tokens[UserRole.OPERATIONS]),
        )
        assert response.status_code == 200
        assert str(company_id) in response.text
        for forbidden in (pan, f"27{pan}1Z5", '"pan"', '"gstin', '"iec"', '"cin"'):
            assert forbidden not in response.text
    finally:
        await _reopen(company_id)
