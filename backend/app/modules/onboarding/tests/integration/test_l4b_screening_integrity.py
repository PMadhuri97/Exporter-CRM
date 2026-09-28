"""Screening integrity — **owner: Developer 4B** (4B-1; ``docs/dev4/4b-task.md`` §5.5,
§5.6).

* the one catalogue is served by the backend, in order, with labels and sections;
* capabilities are served, so the UI keeps no role list;
* unknown key / unknown status → 422, unknown company → 404 (not a database error);
* each item's history is readable, newest first, paged, from the append-only table;
* the latest-row rule is unchanged;
* every decision also writes a ``screening`` row to the company history (D9).

The status CHECK itself is proved with direct SQL in ``test_l4b_verification_schema.py``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE_ITEMS,
    ScreeningReviewService,
)
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._l4b_support import BASE, history_rows, pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


async def _decide(company_id: uuid.UUID, item_key: str, status: str, actor: str = "c"):
    async with db_services.AsyncSessionLocal() as db:
        return await ScreeningReviewService(db).upsert_review_item(
            company_id, item_key=item_key, status=status, comment=f"{status} by {actor}",
            actor_id=actor,
        )


# ── Served catalogue and capabilities ────────────────────────────────────────


async def test_the_list_serves_the_catalogue_in_order(client, tokens):
    company_id = await make_company()
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["catalogue"] == [
        {"key": item.key, "label": item.label, "section": item.section}
        for item in SCREENING_CATALOGUE_ITEMS
    ]
    assert resp.json()["items"] == []


@pytest.mark.parametrize(
    ("role", "may_decide"),
    [(UserRole.OPERATIONS, False), (UserRole.COMPLIANCE, True), (UserRole.ADMIN, True)],
)
async def test_capabilities_say_whether_the_caller_may_record_a_decision(
    client, tokens, role, may_decide
):
    company_id = await make_company()
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review", headers=auth_header(tokens[role])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["capabilities"] == {"can_record_decision": may_decide}


# ── Validation: key, status, company ─────────────────────────────────────────


async def test_an_unknown_item_key_is_422_over_the_api(client, tokens):
    company_id = await make_company()
    resp = await client.put(
        f"{BASE}/exporters/{company_id}/screening-review/not-a-real-item",
        json={"status": "PASSED"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 422, resp.text


async def test_an_unknown_status_is_422_over_the_api(client, tokens):
    company_id = await make_company()
    resp = await client.put(
        f"{BASE}/exporters/{company_id}/screening-review/website-reviewed",
        json={"status": "MAYBE"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 422, resp.text


async def test_an_unknown_status_is_refused_by_the_service_too():
    company_id = await make_company()
    with pytest.raises(ValidationError, match="status"):
        await _decide(company_id, "website-reviewed", "MAYBE")


async def test_recording_on_an_unknown_company_is_404_not_a_database_error(client, tokens):
    resp = await client.put(
        f"{BASE}/exporters/{uuid.uuid4()}/screening-review/website-reviewed",
        json={"status": "PASSED"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "EXPORTER_PROFILE_NOT_FOUND"


@pytest.mark.parametrize("suffix", ["", "/website-reviewed/history"])
async def test_reading_an_unknown_company_is_404(client, tokens, suffix):
    resp = await client.get(
        f"{BASE}/exporters/{uuid.uuid4()}/screening-review{suffix}",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 404, resp.text


async def test_the_service_refuses_an_unknown_company_before_writing():
    with pytest.raises(ExporterProfileNotFoundError):
        await _decide(uuid.uuid4(), "website-reviewed", "PASSED")


# ── History ──────────────────────────────────────────────────────────────────


async def test_history_is_every_decision_newest_first_and_paged(client, tokens):
    company_id = await make_company()
    first = await _decide(company_id, "payment-purpose", "FAILED", "a")
    second = await _decide(company_id, "payment-purpose", "NEEDS_REVIEW", "b")
    third = await _decide(company_id, "payment-purpose", "PASSED", "c")
    await _decide(company_id, "website-reviewed", "PASSED", "d")  # another item

    url = f"{BASE}/exporters/{company_id}/screening-review/payment-purpose/history"
    headers = auth_header(tokens[UserRole.OPERATIONS])

    page = await client.get(url, headers=headers)
    assert page.status_code == 200, page.text
    body = page.json()
    assert [row["id"] for row in body["items"]] == [str(third.id), str(second.id), str(first.id)]
    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (50, 0)
    assert [row["reviewed_by"] for row in body["items"]] == ["c", "b", "a"]

    second_page = await client.get(url, params={"limit": 2, "offset": 2}, headers=headers)
    assert [row["id"] for row in second_page.json()["items"]] == [str(first.id)]
    assert second_page.json()["total"] == 3


async def test_history_of_an_unknown_item_is_422(client, tokens):
    company_id = await make_company()
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review/not-a-real-item/history",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 422, resp.text


async def test_the_first_history_row_is_the_current_state():
    """History and the latest-row rule use one order, so they can never disagree."""
    company_id = await make_company()
    await _decide(company_id, "exception-approval", "FAILED")
    latest = await _decide(company_id, "exception-approval", "EXEMPT")

    async with db_services.AsyncSessionLocal() as db:
        service = ScreeningReviewService(db)
        current = await service.list_review_items(company_id)
        history, total = await service.list_item_history(company_id, "exception-approval")

    assert [row.id for row in current] == [latest.id]
    assert history[0].id == latest.id
    assert total == 2


async def test_every_screening_decision_writes_a_screening_history_row():
    """D9 (lead, 28 Sep 2026): decisions appear in the company timeline under the
    ``screening`` dimension, from the item's previous status to the new one."""
    company_id = await make_company()
    first = await _decide(company_id, "website-reviewed", "FAILED", "a")
    second = await _decide(company_id, "website-reviewed", "PASSED", "b")
    other = await _decide(company_id, "payment-purpose", "EXEMPT", "c")

    with pg() as cur:
        rows = history_rows(cur, company_id, dimension="screening")
        cur.execute(
            "SELECT count(*) FROM onboarding.exporter_lifecycle_history WHERE customer_id = %s",
            (str(company_id),),
        )
        assert cur.fetchone() == (3,)  # nothing written under any other dimension

    assert [r[:6] for r in rows] == [
        ("screening_initial", None, "FAILED", "a", "FAILED by a", None),
        ("screening_transition", "FAILED", "PASSED", "b", "PASSED by b", None),
        ("screening_initial", None, "EXEMPT", "c", "EXEMPT by c", None),
    ]
    assert [r[6] for r in rows] == [
        {
            "source": "screening_review_service.upsert_review_item",
            "item_key": key,
            "screening_review_item_id": str(item.id),
        }
        for key, item in (
            ("website-reviewed", first),
            ("website-reviewed", second),
            ("payment-purpose", other),
        )
    ]


async def test_a_refused_screening_decision_writes_no_history_row():
    company_id = await make_company()
    with pytest.raises(ValidationError):
        await _decide(company_id, "not-a-real-item", "PASSED")
    with pg() as cur:
        assert history_rows(cur, company_id, dimension="screening") == []


# ── ORM foreign key (no migration) ───────────────────────────────────────────


async def test_the_model_declares_the_companys_foreign_key():
    column = ScreeningReviewItem.__table__.c.customer_id
    [fk] = column.foreign_keys
    assert fk.name == "fk_screening_review_item_customer_id"
    assert fk.target_fullname == "onboarding.exporter_profile.customer_id"
    assert fk.ondelete == "RESTRICT"


async def test_the_declared_foreign_key_matches_the_database():
    with pg() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'fk_screening_review_item_customer_id'"
        )
        [(definition,)] = cur.fetchall()
    assert "REFERENCES onboarding.exporter_profile(customer_id)" in definition
    assert "ON DELETE RESTRICT" in definition
