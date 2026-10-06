"""Who acted, by name, on the CRM's list responses.

History rows, background-check decisions, activities and follow-ups store the person
who acted as a user id. The screens used to print that id ("By cc56991e-…"): the user
list is gated to user management, so no staff screen could turn it into a name. Each
response now carries the name as well (`actor_name`, `decided_by_name`), resolved when
it is read (`api/actor_names.py`):

- OPERATIONS, COMPLIANCE and ADMIN get the account's full name, or its email when it
  has none;
- DEVELOPER gets the full name only;
- the platform (no actor), and an id that is not an account's, get `null`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import PASSWORD, create_user_direct
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


async def _login(client: AsyncClient, email: str) -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, str]:
    """A named OPERATIONS user and an unnamed COMPLIANCE user, logged in."""
    suffix = uuid.uuid4().hex[:8]
    named_email = f"priya-{suffix}@aner-test.com"
    unnamed_email = f"unnamed-{suffix}@aner-test.com"
    named_id = create_user_direct(named_email, UserRole.OPERATIONS, full_name="Priya Ops")
    unnamed_id = create_user_direct(unnamed_email, UserRole.COMPLIANCE)
    return {
        "named_id": named_id,
        "named_token": await _login(client, named_email),
        "unnamed_id": unnamed_id,
        "unnamed_email": unnamed_email,
        "unnamed_token": await _login(client, unnamed_email),
        "developer_token": await token_with_role(client, UserRole.DEVELOPER),
    }


async def _history_rows(company_id: uuid.UUID, people: dict[str, str]) -> None:
    rows = [
        {"to_value": "A", "actor_id": people["named_id"]},
        {"to_value": "B", "actor_id": people["unnamed_id"]},
        {"to_value": "C", "actor_id": None},
        {"to_value": "D", "actor_id": "rm-1"},  # not an account's id
    ]
    async with db_services.AsyncSessionLocal() as db:
        for row in rows:
            await HistoryService(db).record(
                company_id, dimension="marker", source="test", **row
            )
        await db.commit()


def _names_by_value(entries: list[dict]) -> dict[str, str | None]:
    return {entry["to_value"]: entry["actor_name"] for entry in entries}


async def test_history_names_each_actor_for_staff(client: AsyncClient, people):
    company_id = await make_company()
    await _history_rows(company_id, people)

    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        headers=auth_header(people["unnamed_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert _names_by_value(resp.json()["entries"]) == {
        "A": "Priya Ops",
        "B": people["unnamed_email"],  # no full name: the email stands in for staff
        "C": None,  # the platform
        "D": None,  # not an account; the id is still served in `actor_id`
    }


async def test_history_gives_developer_names_but_never_emails(client: AsyncClient, people):
    company_id = await make_company()
    await _history_rows(company_id, people)

    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        headers=auth_header(people["developer_token"]),
    )
    assert resp.status_code == 200, resp.text
    names = _names_by_value(resp.json()["entries"])
    assert names["A"] == "Priya Ops"
    assert names["B"] is None


async def test_activities_and_follow_ups_name_who_logged_them(client: AsyncClient, people):
    company_id = await make_company()
    due = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    logged = await client.post(
        f"{BASE}/exporters/{company_id}/activities",
        json={"activity_type": "CALL", "subject": "Intro call", "due_at": due},
        headers=auth_header(people["named_token"]),
    )
    assert logged.status_code == 201, logged.text
    assert logged.json()["actor_name"] == "Priya Ops"

    listed = await client.get(
        f"{BASE}/exporters/{company_id}/activities",
        headers=auth_header(people["unnamed_token"]),
    )
    assert listed.status_code == 200, listed.text
    assert [a["actor_name"] for a in listed.json()["activities"]] == ["Priya Ops"]

    follow_ups = await client.get(
        f"{BASE}/follow-ups",
        params={"customer_id": str(company_id), "state": "OUTSTANDING"},
        headers=auth_header(people["unnamed_token"]),
    )
    assert follow_ups.status_code == 200, follow_ups.text
    assert [f["actor_name"] for f in follow_ups.json()["follow_ups"]] == ["Priya Ops"]


async def test_a_completed_follow_up_names_who_completed_it(client: AsyncClient, people):
    """R-59. The Agenda's Done tab printed "Done by 853ef096-…": the completion was
    served with `completed_by` only. It now carries `completed_by_name`, resolved
    as every other actor is — the email standing in for an unnamed account for
    staff, and never for DEVELOPER."""
    company_id = await make_company()
    due = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    completers = {"named": people["named_token"], "unnamed": people["unnamed_token"]}
    activity_ids: dict[str, str] = {}
    for who, token in completers.items():
        logged = await client.post(
            f"{BASE}/exporters/{company_id}/activities",
            json={"activity_type": "FOLLOW_UP", "subject": f"Chase {who}", "due_at": due},
            headers=auth_header(people["named_token"]),
        )
        assert logged.status_code == 201, logged.text
        activity_ids[who] = logged.json()["id"]
        done = await client.post(
            f"{BASE}/follow-ups/{activity_ids[who]}/completion",
            json={"outcome": "DONE"},
            headers=auth_header(token),
        )
        assert done.status_code == 201, done.text
        assert done.json()["completed_by_name"] == (
            "Priya Ops" if who == "named" else people["unnamed_email"]
        )

    async def done_rows(token: str) -> list[dict]:
        resp = await client.get(
            f"{BASE}/follow-ups",
            params={"customer_id": str(company_id), "state": "DONE"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["follow_ups"]

    staff_rows = await done_rows(people["unnamed_token"])
    developer_rows = await done_rows(people["developer_token"])

    def by_activity(rows: list[dict], key: str) -> dict[str, str | None]:
        return {row["activity_id"]: row["completion"][key] for row in rows}

    assert by_activity(staff_rows, "completed_by_name") == {
        activity_ids["named"]: "Priya Ops",
        activity_ids["unnamed"]: people["unnamed_email"],
    }
    # DEVELOPER: the full name, never the email (architecture §8).
    assert by_activity(developer_rows, "completed_by_name") == {
        activity_ids["named"]: "Priya Ops",
        activity_ids["unnamed"]: None,
    }
    # The id is still served beside the name.
    assert by_activity(staff_rows, "completed_by") == {
        activity_ids["named"]: people["named_id"],
        activity_ids["unnamed"]: people["unnamed_id"],
    }


async def test_background_check_decisions_name_who_decided(client: AsyncClient, people):
    company_id = await make_company()
    started = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "IN_REVIEW"},
        headers=auth_header(people["named_token"]),
    )
    assert started.status_code == 201, started.text
    assert started.json()["decided_by_name"] == "Priya Ops"

    listed = await client.get(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        headers=auth_header(people["unnamed_token"]),
    )
    assert listed.status_code == 200, listed.text
    (decision,) = listed.json()["decisions"]
    assert decision["decided_by"] == people["named_id"]
    assert decision["decided_by_name"] == "Priya Ops"


async def test_screening_decisions_and_verification_reviews_name_the_reviewer(
    client: AsyncClient, people
):
    company_id = await make_company()
    compliance = auth_header(people["unnamed_token"])

    decided = await client.put(
        f"{BASE}/exporters/{company_id}/screening-review/exception-approval",
        json={"status": "PASSED", "comment": "approved"},
        headers=compliance,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["reviewed_by_name"] == people["unnamed_email"]
    item_history = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review/exception-approval/history",
        headers=compliance,
    )
    assert [i["reviewed_by_name"] for i in item_history.json()["items"]] == [
        people["unnamed_email"]
    ]

    recorded = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "SANCTIONS",
            "entity_type": "EXPORTER",
            "entity_reference": str(company_id),
            "payload": {"status": "REVIEW"},
            "evidence_note": "list hit to look at",
        },
        headers=compliance,
    )
    assert recorded.status_code == 201, recorded.text
    reviewed = await client.post(
        f"{BASE}/verifications/{recorded.json()['id']}/review",
        json={"review_status": "ACCEPTED", "note": "false positive"},
        headers=compliance,
    )
    assert reviewed.status_code in (200, 201), reviewed.text
    body = reviewed.json()
    assert body["reviewed_by_name"] == people["unnamed_email"]
    assert [r["reviewed_by_name"] for r in body["reviews"]] == [people["unnamed_email"]]
