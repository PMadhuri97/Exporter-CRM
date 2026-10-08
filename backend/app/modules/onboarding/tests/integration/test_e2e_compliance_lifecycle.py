"""The compliance lifecycle end to end, through the API (the main CRM path is
`test_crm_end_to_end.py`).

One company, real routes, real users, nothing substituted: an RM starts the check;
compliance answers the checklist and records KYB, AML and sanctions; a maker
proposes CLEAR; the RM and DEVELOPER are refused; a second officer rejects it, then
approves the next — and only then does the qualified PROSPECT become a CUSTOMER; the
Clear carries its expiry and shows on the Re-KYC list; a Re-KYC starts cycle 2 with
nothing carried over. Every compliance route also refuses a caller with no token.
"""

from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.screening_review_service import SCREENING_CATALOGUE
from app.modules.onboarding.events import publisher as publisher_module
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.messaging.ports import InMemoryEventBus

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
_ID = "00000000-0000-4000-8000-000000000000"


@pytest.fixture(autouse=True)
def _quiet_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher_module, "get_event_bus", InMemoryEventBus)


@pytest.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, tuple[str, str]]:
    """``name → (user_id, token)``."""
    return {
        "maker": await user_with_role(client, UserRole.COMPLIANCE, email_prefix="e2e-maker"),
        "checker": await user_with_role(client, UserRole.COMPLIANCE, email_prefix="e2e-checker"),
        "rm": await user_with_role(client, UserRole.OPERATIONS, email_prefix="e2e-rm"),
        "developer": await user_with_role(client, UserRole.DEVELOPER, email_prefix="e2e-dev"),
        "api_user": await user_with_role(client, UserRole.API_USER, email_prefix="e2e-api"),
    }


def _pan() -> str:
    letters = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
    return f"{letters}{random.randint(0, 9999):04d}{random.choice(string.ascii_uppercase)}"


class _Api:
    def __init__(self, client: AsyncClient, people) -> None:
        self.client, self.people = client, people

    def token(self, who: str) -> str:
        return self.people[who][1]

    async def call(self, who: str, method: str, path: str, expect: int, **kwargs) -> dict:
        response = await self.client.request(
            method, f"{BASE}{path}", headers=auth_header(self.token(who)), **kwargs
        )
        assert response.status_code == expect, f"{method} {path} as {who}: {response.text}"
        return response.json() if response.content else {}

    async def journey(self, company_id: str) -> str:
        return (await self.call("maker", "GET", f"/exporters/{company_id}", 200))["journey"]

    async def standing(self, company_id: str, who: str = "maker") -> dict:
        return await self.call(who, "GET", f"/exporters/{company_id}/background-check", 200)


async def test_the_compliance_lifecycle_with_two_officers(client: AsyncClient, people):
    api = _Api(client, people)
    pan = _pan()
    created = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": f"Lifecycle Exports {uuid.uuid4().hex[:6]}",
              "country": "IN", "pan": pan},
        headers={**auth_header(api.token("rm")), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    company = created.json()["customer_id"]
    check = f"/exporters/{company}/background-check"
    # The RM records QUALIFIED and, the company having no RM, names themselves.
    await api.call("rm", "POST", f"/exporters/{company}/qualification/outcome", 201,
                   json={"outcome": "QUALIFIED", "note": "Meets our requirements.",
                         "relationship_manager_user_id": api.people["rm"][0]})
    assert await api.journey(company) == "PROSPECT"

    # Start (the RM may), then the inputs.
    await api.call("rm", "POST", f"{check}/decisions", 201, json={"to_value": "IN_REVIEW"})
    for key in SCREENING_CATALOGUE:
        await api.call("maker", "PUT", f"/exporters/{company}/screening-review/{key}", 200,
                       json={"status": "PASSED"})
    standing = await api.standing(company)
    assert [c["state"] for c in standing["required_checks"]] == ["MISSING"] * 3
    assert {"kyb_passed", "aml_passed", "sanctions_passed"} <= set(standing["clear_blocked_reasons"])
    for kind in ("KYB", "AML", "SANCTIONS"):
        await api.call("maker", "POST", "/verifications", 201,
                       json={"verification_type": kind, "entity_type": "EXPORTER",
                             "entity_reference": company, "payload": {"status": "PASSED"},
                             "evidence_note": f"{kind} checked manually."})
    standing = await api.standing(company)
    assert standing["clear_blocked_reasons"] == []
    assert [c["state"] for c in standing["required_checks"]] == ["PASSED"] * 3
    clear_move = next(m for m in standing["allowed_moves"] if m["to_value"] == "CLEAR")
    assert clear_move["approval_required"] is True

    # A proposal, refused to the RM and DEVELOPER, rejected by the second officer.
    first = await api.call("maker", "POST", f"{check}/decisions", 202,
                           json={"to_value": "CLEAR", "reason": "All checks passed.",
                                 "risk_rating": "LOW", "from_value": "IN_REVIEW"})
    assert (await api.standing(company))["awaiting_approval"] is True
    assert await api.journey(company) == "PROSPECT"  # pending: not promoted
    await api.call("rm", "POST", f"{check}/proposals/{first['id']}/approve", 403)
    await api.call("developer", "GET", check, 403)
    await api.call("maker", "POST", f"{check}/proposals/{first['id']}/approve", 403)
    await api.call("checker", "POST", f"{check}/proposals/{first['id']}/reject", 200,
                   json={"reason": "Risk should be MEDIUM."})
    assert await api.journey(company) == "PROSPECT"  # rejected: not promoted
    assert (await api.standing(company))["value"] == "IN_REVIEW"

    # Proposed again and approved: CLEAR, with both names and an expiry; promoted.
    second = await api.call("maker", "POST", f"{check}/decisions", 202,
                            json={"to_value": "CLEAR", "reason": "All checks passed.",
                                  "risk_rating": "MEDIUM"})
    approved = await api.call("checker", "POST", f"{check}/proposals/{second['id']}/approve", 200)
    decision = approved["decision"]
    assert (decision["decided_by"], decision["approved_by"]) == (
        people["maker"][0],
        people["checker"][0],
    )
    decided_at = datetime.fromisoformat(decision["decided_at"])
    expires_at = datetime.fromisoformat(decision["expires_at"])
    assert expires_at - decided_at == timedelta(days=365)
    assert await api.journey(company) == "CUSTOMER"  # a current Clear promotes
    standing = await api.standing(company)
    assert standing["compliance"]["is_clear_current"] is True and standing["rekyc_due"] is False
    proposals = await api.call("maker", "GET", f"{check}/proposals", 200)
    assert [p["status"] for p in proposals["proposals"]] == ["APPROVED", "REJECTED"]

    # On the Re-KYC list once the cut-off passes its expiry.
    due = await api.call("rm", "GET", "/background-check/due", 200,
                         params={"before": (expires_at + timedelta(days=1)).isoformat(),
                                 "limit": 100, "offset": 0})
    assert due["total"] >= 1

    # A Re-KYC: cycle 2, reopened, nothing carried over; still a customer.
    started = await api.call("maker", "POST", f"{check}/cycles", 201,
                             json={"kind": "RE_KYC", "reason": "Annual Re-KYC"})
    assert started["cycle"]["number"] == 2 and started["reopen_decision"]["to_value"] == "IN_REVIEW"
    standing = await api.standing(company)
    assert standing["value"] == "IN_REVIEW" and standing["current_cycle"]["number"] == 2
    assert [c["state"] for c in standing["required_checks"]] == ["MISSING"] * 3
    assert await api.journey(company) == "CUSTOMER"  # a reopen never demotes

    # The whole story is in the history log — not for DEVELOPER.
    history = await api.call("maker", "GET", f"/exporters/{company}/history", 200,
                             params={"limit": 200})
    dimensions = {e["dimension"] for e in history["entries"]}
    assert {"background_check", "background_check_approval", "check_cycle", "verification",
            "screening", "journey"} <= dimensions
    hidden = await api.call("developer", "GET", f"/exporters/{company}/history", 200,
                            params={"limit": 200})
    assert not {"background_check", "background_check_approval", "check_cycle"} & {
        e["dimension"] for e in hidden["entries"]
    }


COMPLIANCE_ROUTES = [
    ("GET", f"/exporters/{_ID}/background-check"),
    ("POST", f"/exporters/{_ID}/background-check/decisions"),
    ("GET", f"/exporters/{_ID}/background-check/decisions"),
    ("GET", f"/exporters/{_ID}/background-check/decisions/{_ID}/evidence"),
    ("GET", f"/exporters/{_ID}/background-check/cycles"),
    ("POST", f"/exporters/{_ID}/background-check/cycles"),
    ("GET", f"/exporters/{_ID}/background-check/proposals"),
    ("POST", f"/exporters/{_ID}/background-check/proposals/{_ID}/approve"),
    ("POST", f"/exporters/{_ID}/background-check/proposals/{_ID}/reject"),
    ("POST", f"/exporters/{_ID}/background-check/proposals/{_ID}/withdraw"),
    ("GET", "/background-check/proposals"),
    ("GET", "/background-check/due"),
]


@pytest.mark.parametrize(("method", "path"), COMPLIANCE_ROUTES, ids=[f"{m} {p}" for m, p in COMPLIANCE_ROUTES])
async def test_every_compliance_route_refuses_a_caller_with_no_token(client: AsyncClient, method, path):
    response = await client.request(method, f"{BASE}{path}", json={})
    assert response.status_code == 401, response.text


@pytest.mark.parametrize(("method", "path"), COMPLIANCE_ROUTES, ids=[f"{m} {p}" for m, p in COMPLIANCE_ROUTES])
async def test_every_compliance_route_refuses_developer_and_api_user(
    client: AsyncClient, people, method, path
):
    for who in ("developer", "api_user"):
        response = await client.request(
            method, f"{BASE}{path}", json={}, headers=auth_header(people[who][1])
        )
        assert response.status_code == 403, (who, response.text)
