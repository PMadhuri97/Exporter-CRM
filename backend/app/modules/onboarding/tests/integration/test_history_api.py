"""The history read routes.

`GET /onboarding/exporters/{customer_id}/history` and
`GET /onboarding/deals/{deal_id}/history`.

Role refusals are generated for both routes by the platform-wide table in
`tests/contract/test_route_authorization_coverage.py`, so they are not repeated
here. What this file covers is what that table cannot: that every role which
*may* read actually gets the data, and that the response, the ordering, the
paging and the dimension filter behave.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
READERS = [UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER]


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


async def _seed(company_id: uuid.UUID, deal_id: uuid.UUID) -> None:
    """Four rows across three dimensions, written oldest first.

    Each in its own transaction so `created_at` — which is transaction time —
    genuinely differs between them; rows written in one transaction share a
    timestamp and would only exercise the `id` tie-break.
    """
    rows = [
        {"dimension": "journey", "to_value": "LEAD", "actor_id": "rm-1", "source": "seed"},
        {
            "dimension": "qualification",
            "from_value": "NOT_YET_REVIEWED",
            "to_value": "QUALIFIED",
            "actor_id": "rm-1",
            "reason": "revenue above threshold",
            "source": "seed",
            "details": {"criteria_version": 3},
        },
        {
            "dimension": "journey",
            "from_value": "LEAD",
            "to_value": "PROSPECT",
            "actor_id": "rm-2",
            "source": "seed",
        },
        {
            "dimension": "deal",
            "to_value": "OPEN",
            "actor_id": "ops-1",
            "source": "seed",
            "deal_id": deal_id,
        },
    ]
    for row in rows:
        async with db_services.AsyncSessionLocal() as db:
            await HistoryService(db).record(company_id, **row)
            await db.commit()


@pytest.fixture(scope="module")
async def seeded() -> tuple[uuid.UUID, uuid.UUID]:
    company_id, deal_id = uuid.uuid4(), uuid.uuid4()
    await _seed(company_id, deal_id)
    return company_id, deal_id


# ── Company history ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", READERS)
async def test_every_reader_role_can_read_a_company_timeline(
    client: AsyncClient, tokens: dict[UserRole, str], seeded, role: UserRole
):
    """The positive half of the role matrix.

    A refusal-only suite passes just as well against a route that refuses
    everyone, and DEVELOPER in particular is read-only *and* permitted here —
    "see companies, contacts, deals, history" is a yes for it.
    """
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history", headers=auth_header(tokens[role])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 4


async def test_the_response_carries_every_contracted_field(
    client: AsyncClient, tokens: dict[UserRole, str], seeded
):
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        params={"dimension": "qualification"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 200, resp.text
    (entry,) = resp.json()["entries"]

    assert entry["company_id"] == str(company_id)
    assert entry["dimension"] == "qualification"
    assert entry["from_value"] == "NOT_YET_REVIEWED"
    assert entry["to_value"] == "QUALIFIED"
    assert entry["actor_id"] == "rm-1"
    assert entry["reason"] == "revenue above threshold"
    # `source` is lifted out of the metadata blob; the rest stays in `details`,
    # so a caller need not know one of its keys is special.
    assert entry["source"] == "seed"
    assert entry["details"] == {"criteria_version": 3}
    assert entry["deal_id"] is None
    assert entry["occurred_at"] is not None
    assert entry["id"]


async def test_the_timeline_is_newest_first(
    client: AsyncClient, tokens: dict[UserRole, str], seeded
):
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        headers=auth_header(tokens[UserRole.ADMIN]),
    )
    stamps = [e["occurred_at"] for e in resp.json()["entries"]]
    assert stamps == sorted(stamps, reverse=True)
    assert resp.json()["entries"][0]["to_value"] == "OPEN"


async def test_an_unfiltered_read_interleaves_every_dimension(
    client: AsyncClient, tokens: dict[UserRole, str], seeded
):
    """The company timeline the architecture describes as "the full story of a
    company" — not one gauge at a time."""
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert {e["dimension"] for e in resp.json()["entries"]} == {
        "journey",
        "qualification",
        "deal",
    }


@pytest.mark.parametrize(
    ("dimension", "expected"), [("journey", 2), ("qualification", 1), ("deal", 1)]
)
async def test_the_dimension_filter_narrows_entries_and_total(
    client: AsyncClient, tokens: dict[UserRole, str], seeded, dimension: str, expected: int
):
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        params={"dimension": dimension},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    body = resp.json()
    assert body["total"] == expected
    assert len(body["entries"]) == expected
    assert {e["dimension"] for e in body["entries"]} == {dimension}


async def test_a_dimension_nobody_writes_yet_returns_an_empty_page(
    client: AsyncClient, tokens: dict[UserRole, str], seeded
):
    """Not a 422: the dimension list lives in a contract, not an enum, so the
    API cannot tell "not built yet" from "spelled wrong" and must not pretend
    it can."""
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        params={"dimension": "background_check"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 200
    assert resp.json() == {"entries": [], "total": 0, "limit": 50, "offset": 0}


async def test_paging_does_not_repeat_or_drop_a_row(
    client: AsyncClient, tokens: dict[UserRole, str], seeded
):
    company_id, _ = seeded
    token = auth_header(tokens[UserRole.ADMIN])

    seen: list[str] = []
    for offset in (0, 2):
        resp = await client.get(
            f"{BASE}/exporters/{company_id}/history",
            params={"limit": 2, "offset": offset},
            headers=token,
        )
        body = resp.json()
        assert body["total"] == 4 and body["limit"] == 2 and body["offset"] == offset
        seen.extend(e["id"] for e in body["entries"])

    assert len(seen) == 4
    assert len(set(seen)) == 4


async def test_an_unknown_company_returns_an_empty_page_not_a_404(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """A company with no history and a company id that was never real are the
    same answer from this table. Distinguishing them would mean this route
    checking the company record — which would also make it a way to probe
    which company ids exist.
    """
    resp = await client.get(
        f"{BASE}/exporters/{uuid.uuid4()}/history",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.parametrize(("params", "reason"), [
    ({"limit": 0}, "below the minimum"),
    ({"limit": 201}, "above the maximum"),
    ({"offset": -1}, "negative"),
])
async def test_paging_bounds_are_enforced(
    client: AsyncClient, tokens: dict[UserRole, str], seeded, params: dict, reason: str
):
    company_id, _ = seeded
    resp = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        params=params,
        headers=auth_header(tokens[UserRole.ADMIN]),
    )
    assert resp.status_code == 422, reason


# ── Deal history ─────────────────────────────────────────────────────────────


async def test_a_deal_read_returns_only_that_deals_rows(
    client: AsyncClient, tokens: dict[UserRole, str], seeded
):
    company_id, deal_id = seeded
    resp = await client.get(
        f"{BASE}/deals/{deal_id}/history", headers=auth_header(tokens[UserRole.OPERATIONS])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["entries"][0]["deal_id"] == str(deal_id)
    assert body["entries"][0]["company_id"] == str(company_id)


async def test_an_unknown_deal_returns_an_empty_page(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """The correct answer today, when no deal table exists (migration 0018
    is Developer 3's), and the correct answer afterwards for an id that was
    never real."""
    resp = await client.get(
        f"{BASE}/deals/{uuid.uuid4()}/history",
        headers=auth_header(tokens[UserRole.ADMIN]),
    )
    assert resp.status_code == 200
    assert resp.json() == {"entries": [], "total": 0, "limit": 50, "offset": 0}


# ── Read-only ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_history_cannot_be_written_through_the_api(
    client: AsyncClient, tokens: dict[UserRole, str], seeded, method: str
):
    """There is no write surface, and there should never be one.

    History is written by the service that made the change, inside that
    change's transaction, and the table refuses UPDATE and DELETE at the
    database. A route that could post a history row would be a way to record
    something that never happened.

    404 rather than the 405 a bare Starlette router would give: the gateway's
    root fallback (`/{version}/{rest:path}`, registered last in `main.py`)
    matches the unrouted request first and answers 404. Either status proves
    the same thing — nothing handles a write here — so the assertion accepts
    both rather than pinning an accident of router ordering.
    """
    company_id, _ = seeded
    resp = await client.request(
        method,
        f"{BASE}/exporters/{company_id}/history",
        json={"dimension": "journey", "to_value": "CUSTOMER"},
        headers={**auth_header(tokens[UserRole.ADMIN]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code in (404, 405), resp.text

    # And nothing was written by the attempt.
    check = await client.get(
        f"{BASE}/exporters/{company_id}/history",
        headers=auth_header(tokens[UserRole.ADMIN]),
    )
    assert check.json()["total"] == 4
