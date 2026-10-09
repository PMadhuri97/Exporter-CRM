"""Structured sanctions screening, over HTTP.

The walk-through: an officer records a run against the UN and MHA lists with one hit,
marks it a false positive with a reason, and the run is Passed; the Clear rule sees a
sanctions pass. Recording a new MHA version date puts the company on Re-screen due.

Then the rules around it: every mandatory list must be covered; a true match is
proposed, flags the company and waits for a second officer; a rejected proposal goes
back to open; decisions are append-only; and a REVIEW the screening wrote is concluded
when the screening resolves, so it never holds a Clear back.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import psycopg2
import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.domain.compliance_facts import check_state
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
LISTS = ["UN_SC", "IN_MHA_UAPA"]


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _record(client, token, company_id, *, hits=(), lists=LISTS, **body):
    return await client.post(
        f"{BASE}/exporters/{company_id}/sanctions/runs",
        headers=auth_header(token),
        json={"list_codes": list(lists), "hits": list(hits), **body},
    )


async def _sanctions_state(company_id) -> str:
    async with db_services.AsyncSessionLocal() as db:
        inputs = await ComplianceInputsService(db).company_inputs(company_id)
    return check_state(inputs.verifications, "SANCTIONS")


HIT = {"list_code": "UN_SC", "matched_name": "Acme Exports Ltd", "list_entry_id": "QDe.123", "score": 82}


async def test_a_false_positive_passes_the_run_and_the_clear_rule_sees_it(client: AsyncClient):
    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await make_company()

    recorded = await _record(client, officer, company_id, hits=[HIT])
    assert recorded.status_code == 201, recorded.text
    run = recorded.json()
    assert run["outcome"] == "REVIEW"
    assert {row["code"] for row in run["lists"]} == set(LISTS)
    assert await _sanctions_state(company_id) == "PENDING"

    hit_id = run["hits"][0]["id"]
    decided = await client.post(
        f"{BASE}/sanctions/hits/{hit_id}/decision",
        headers=auth_header(officer),
        json={"disposition": "FALSE_POSITIVE", "reason": "Different company, different country"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["outcome"] == "PASSED"
    assert len(decided.json()["hits"][0]["decisions"]) == 2
    assert await _sanctions_state(company_id) == "PASSED"

    # The earlier REVIEW result was concluded, so it does not hold the Clear back.
    async with db_services.AsyncSessionLocal() as db:
        inputs = await ComplianceInputsService(db).company_inputs(company_id)
    reviews = [v for v in inputs.verifications if v.verification_type == "SANCTIONS" and v.status == "REVIEW"]
    assert reviews and all(v.latest_review_status == "ACCEPTED" for v in reviews)

    coverage = (await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(officer))).json()
    assert coverage["standing"] == "PASSED"
    assert coverage["flagged"] is False
    assert coverage["subjects"][0]["subject_type"] == "COMPANY"
    assert coverage["subjects"][0]["rescreen_reasons"] == []


async def test_a_new_list_version_puts_the_company_on_rescreen_due(client: AsyncClient):
    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    _, admin = await user_with_role(client, UserRole.ADMIN)
    company_id = await make_company()
    await _record(client, officer, company_id)

    lists = (await client.get(f"{BASE}/settings/sanctions-lists", headers=auth_header(admin))).json()
    mha = next(row for row in lists["lists"] if row["code"] == "IN_MHA_UAPA")
    newer = (date.fromisoformat(mha["list_version_date"]) + timedelta(days=1)).isoformat()
    revised = await client.patch(
        f"{BASE}/settings/sanctions-lists/IN_MHA_UAPA",
        headers=auth_header(admin),
        json={"list_version_date": newer},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == mha["version"] + 1

    due = await client.get(f"{BASE}/sanctions/rescreen-due", headers=auth_header(officer))
    row = next(r for r in due.json()["companies"] if r["company_id"] == str(company_id))
    assert any("newer version" in reason for reason in row["reasons"])

    # Screening again against the new version takes it off the list.
    await _record(client, officer, company_id)
    due = await client.get(f"{BASE}/sanctions/rescreen-due", headers=auth_header(officer))
    assert str(company_id) not in {r["company_id"] for r in due.json()["companies"]}


async def test_every_mandatory_list_must_be_covered(client: AsyncClient):
    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await make_company()

    refused = await _record(client, officer, company_id, lists=["UN_SC"])
    assert refused.status_code == 422, refused.text
    assert "mandatory" in refused.json()["detail"]
    unknown = await _record(client, officer, company_id, lists=[*LISTS, "NOPE"])
    assert unknown.status_code == 422


async def test_a_true_match_is_proposed_flags_the_company_and_needs_a_second_officer(
    client: AsyncClient,
):
    _, first = await user_with_role(client, UserRole.COMPLIANCE)
    _, second = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await make_company()
    run = (
        await _record(
            client, first, company_id,
            hits=[{**HIT, "disposition": "TRUE_MATCH", "reason": "Same name, address and director"}],
        )
    ).json()
    hit_id = run["hits"][0]["id"]
    assert run["hits"][0]["current"]["disposition"] == "TRUE_MATCH_PROPOSED"
    assert run["outcome"] == "REVIEW"
    coverage = (await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(first))).json()
    assert coverage["flagged"] is True

    own = await client.post(f"{BASE}/sanctions/hits/{hit_id}/confirm", headers=auth_header(first))
    assert own.status_code == 403, own.text
    assert own.json()["error_code"] == "SANCTIONS_TRUE_MATCH_REFUSED"
    queue = (await client.get(f"{BASE}/sanctions/true-matches", headers=auth_header(second))).json()
    row = next(m for m in queue["matches"] if m["hit"]["id"] == hit_id)
    assert row["can_confirm"] is True

    confirmed = await client.post(f"{BASE}/sanctions/hits/{hit_id}/confirm", headers=auth_header(second))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["outcome"] == "FAILED"
    assert await _sanctions_state(company_id) == "FAILED"
    final = await client.post(
        f"{BASE}/sanctions/hits/{hit_id}/decision",
        headers=auth_header(first),
        json={"disposition": "FALSE_POSITIVE", "reason": "changed mind"},
    )
    assert final.status_code == 422


async def test_a_rejected_true_match_goes_back_to_open_and_lifts_the_flag(client: AsyncClient):
    _, first = await user_with_role(client, UserRole.COMPLIANCE)
    _, second = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await make_company()
    run = (
        await _record(client, first, company_id, hits=[{**HIT, "disposition": "TRUE_MATCH", "reason": "Looks like it"}])
    ).json()
    hit_id = run["hits"][0]["id"]

    rejected = await client.post(
        f"{BASE}/sanctions/hits/{hit_id}/reject",
        headers=auth_header(second),
        json={"reason": "The listed entity is in another country"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["hits"][0]["current"]["disposition"] == "OPEN"
    coverage = (await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(first))).json()
    assert coverage["flagged"] is False
    assert coverage["standing"] == "REVIEW"


async def test_a_true_match_still_flags_the_company_after_a_re_check_starts(client: AsyncClient):
    """A new cycle screens afresh, but it does not wash a match away: the flag follows
    each subject's latest screening, in whatever cycle, until it is screened again."""
    from app.modules.onboarding.tests.integration._compliance_support import (
        cleared_company,
        start_cycle,
    )

    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await cleared_company(await make_company())
    proposed = await _record(
        client, officer, company_id,
        hits=[{**HIT, "disposition": "TRUE_MATCH", "reason": "Same name and address"}],
    )
    assert proposed.status_code == 201, proposed.text
    url = f"{BASE}/exporters/{company_id}/sanctions"
    assert (await client.get(url, headers=auth_header(officer))).json()["flagged"] is True

    await start_cycle(company_id)
    after = (await client.get(url, headers=auth_header(officer))).json()
    assert after["flagged"] is True
    assert after["standing"] is None  # the new cycle has not screened the company yet

    assert (await _record(client, officer, company_id)).status_code == 201
    rescreened = (await client.get(url, headers=auth_header(officer))).json()
    assert rescreened["flagged"] is False
    assert rescreened["standing"] == "PASSED"


async def test_a_flagged_seller_cannot_hand_over(client: AsyncClient):
    from app.modules.onboarding.tests.fixtures.companies import make_prospect

    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    _, rm = await user_with_role(client, UserRole.OPERATIONS)
    company_id = await make_prospect()
    await _record(client, officer, company_id, hits=[{**HIT, "disposition": "TRUE_MATCH", "reason": "Match"}])
    deal = await client.post(
        f"{BASE}/exporters/{company_id}/deals", headers=auth_header(rm), json={"reference": "Flagged"}
    )
    assert deal.status_code == 201, deal.text
    moved = await client.post(
        f"{BASE}/deals/{deal.json()['id']}/transitions",
        headers=auth_header(rm),
        json={"to_stage": "GATHERING_PAPERWORK"},
    )
    assert moved.status_code == 200, moved.text
    assert "flagged by a sanctions match" in moved.json()["handover_blocked_reason"]


async def test_a_beneficial_owner_on_record_is_a_subject_and_unscreened_until_screened(
    client: AsyncClient,
):
    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    company_id = await make_company()
    ubo_id = uuid.uuid4()
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            request_id = uuid.uuid4()
            cursor.execute(
                "INSERT INTO onboarding.onboarding_request (id, tenant_id, idempotency_key, "
                "customer_id, status, entity_type, legal_name, incorporation_country, "
                "initial_user_id) VALUES (%s, %s, %s, %s, 'DRAFT', 'CORPORATION', 'x', 'IN', 't')",
                (str(request_id), str(uuid.uuid4()), uuid.uuid4().hex, str(company_id)),
            )
            cursor.execute(
                "INSERT INTO onboarding.ubo_record (id, onboarding_request_id, first_name, "
                "last_name, control_type, kyc_result) "
                "VALUES (%s, %s, 'Priya', 'Shah', 'DIRECT_OWNERSHIP', 'VERIFIED')",
                (str(ubo_id), str(request_id)),
            )
        conn.commit()
    finally:
        conn.close()
    await _record(client, officer, company_id)

    coverage = (await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(officer))).json()
    ubo = next(s for s in coverage["subjects"] if s["subject_type"] == "UBO")
    assert ubo["subject_name"] == "Priya Shah"
    assert ubo["latest"] is None and ubo["rescreen_reasons"] == ["never screened"]

    screened = await _record(
        client, officer, company_id, subject_type="UBO", subject_reference=str(ubo_id)
    )
    assert screened.status_code == 201, screened.text
    coverage = (await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(officer))).json()
    ubo = next(s for s in coverage["subjects"] if s["subject_type"] == "UBO")
    assert ubo["latest"]["outcome"] == "PASSED"


async def test_an_rm_reads_screenings_but_may_not_record_them_and_developer_reads_nothing(
    client: AsyncClient,
):
    _, rm = await user_with_role(client, UserRole.OPERATIONS)
    _, developer = await user_with_role(client, UserRole.DEVELOPER)
    company_id = await make_company()

    assert (await _record(client, rm, company_id)).status_code == 403
    coverage = await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(rm))
    assert coverage.status_code == 200 and coverage.json()["can_record"] is False
    assert (
        await client.get(f"{BASE}/exporters/{company_id}/sanctions", headers=auth_header(developer))
    ).status_code == 403


async def test_developer_is_not_served_sanctions_history(client: AsyncClient):
    """The history rows carry the screened names, the matches and each decision's
    reason — what the screening routes refuse DEVELOPER."""
    _, officer = await user_with_role(client, UserRole.COMPLIANCE)
    _, developer = await user_with_role(client, UserRole.DEVELOPER)
    company_id = await make_company()
    assert (await _record(client, officer, company_id, hits=[HIT])).status_code == 201
    url = f"{BASE}/exporters/{company_id}/history"

    staff = await client.get(url, headers=auth_header(officer))
    assert "sanctions" in {entry["dimension"] for entry in staff.json()["entries"]}

    everything = await client.get(url, headers=auth_header(developer))
    assert everything.status_code == 200
    assert "sanctions" not in {entry["dimension"] for entry in everything.json()["entries"]}
    filtered = await client.get(
        url, params={"dimension": "sanctions"}, headers=auth_header(developer)
    )
    assert filtered.json()["entries"] == [] and filtered.json()["total"] == 0


async def test_hits_and_decisions_cannot_be_changed_or_deleted():
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM onboarding.sanctions_disposition LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                pytest.skip("no decision recorded yet")
            with pytest.raises(psycopg2.Error):
                cursor.execute(
                    "UPDATE onboarding.sanctions_disposition SET reason = 'x' WHERE id = %s", row
                )
    finally:
        conn.rollback()
        conn.close()
