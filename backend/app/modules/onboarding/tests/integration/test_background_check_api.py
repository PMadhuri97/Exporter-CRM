"""The background-check routes.

Contract §3 and §13 through HTTP. The service's rules are proved in
``test_background_check_service.py``; what is proved here is the boundary: that
the status codes match §13, that the server decides what the client may do next, and
above all that **a client cannot supply what is the server's** — the actor, the
source, the decided-by kind or the evidence.

Role refusals for these three routes also have rows in both authorisation tables;
these tests cover the behaviour those tables cannot express.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.domain.storage import DocumentScanStatus
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import make_compliance_user
from app.modules.onboarding.tests.integration.test_background_check_service import (
    _document,
    _service,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _url(company_id: uuid.UUID) -> str:
    return f"{BASE}/exporters/{company_id}/background-check"


async def _start(company_id: uuid.UUID) -> None:
    async with db_services.AsyncSessionLocal() as db:
        await _service(db).start_review(
            company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
        )


# ── GET the standing ─────────────────────────────────────────────────────────


class TestGetBackgroundCheck:
    async def test_a_new_company_reads_not_started_with_the_start_offered(
        self, client: AsyncClient
    ):
        token = await token_with_role(client, UserRole.OPERATIONS)
        company_id = await make_company()

        response = await client.get(_url(company_id), headers=auth_header(token))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["value"] == "NOT_STARTED"
        assert body["risk_rating"] is None
        assert body["latest_decision_id"] is None
        assert body["clearing_decision_id"] is None
        assert [move["to_value"] for move in body["allowed_moves"]] == ["IN_REVIEW"]
        assert body["allowed_moves"][0]["reason_required"] is False

    async def test_the_moves_offered_depend_on_the_caller_s_role(
        self, client: AsyncClient
    ):
        """The same company, two roles, two different answers.

        This is the whole point of serving the moves: the screen never decides what a
        role may do.
        """
        company_id = await make_company()
        await _start(company_id)

        ops = await token_with_role(client, UserRole.OPERATIONS)
        compliance = await token_with_role(client, UserRole.COMPLIANCE)

        ops_body = (await client.get(_url(company_id), headers=auth_header(ops))).json()
        compliance_body = (
            await client.get(_url(company_id), headers=auth_header(compliance))
        ).json()

        # OPERATIONS may make no move from IN_REVIEW.
        assert ops_body["allowed_moves"] == []
        assert {move["to_value"] for move in compliance_body["allowed_moves"]} == {
            "CLEAR",
            "MORE_INFO",
            "FLAGGED",
        }

    async def test_clear_is_offered_with_its_outstanding_prerequisites_named(
        self, client: AsyncClient
    ):
        """So the screen says what is missing rather than showing a 409 afterwards."""
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        body = (await client.get(_url(company_id), headers=auth_header(token))).json()

        clear = next(m for m in body["allowed_moves"] if m["to_value"] == "CLEAR")
        assert clear["risk_required"] is True
        assert clear["reason_required"] is True
        # A fresh company has answered nothing, so at least the screening gate is open.
        assert "screening_items_answered" in body["clear_blocked_reasons"]

    async def test_an_unknown_company_is_404(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.OPERATIONS)
        response = await client.get(_url(uuid.uuid4()), headers=auth_header(token))
        assert response.status_code == 404

    async def test_without_a_token_it_is_401(self, client: AsyncClient):
        company_id = await make_company()
        assert (await client.get(_url(company_id))).status_code == 401

    async def test_developer_is_refused(self, client: AsyncClient):
        """Settled 28 September 2026: DEVELOPER is refused here, reads included.

        DEVELOPER reads deals and documents but not this: a decision's reason is free
        text a compliance officer wrote about a company.
        """
        token = await token_with_role(client, UserRole.DEVELOPER)
        company_id = await make_company()
        response = await client.get(_url(company_id), headers=auth_header(token))
        assert response.status_code == 403


# ── POST a decision ──────────────────────────────────────────────────────────


class TestRecordDecision:
    async def test_operations_can_start_a_check(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.OPERATIONS)
        company_id = await make_company()

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "IN_REVIEW"},
            headers=auth_header(token),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["from_value"] == "NOT_STARTED"
        assert body["to_value"] == "IN_REVIEW"
        assert body["decided_by_kind"] == "MANUAL"
        assert body["source"] == "MANUAL"
        assert body["supersedes_decision_id"] is None

    async def test_the_actor_comes_from_the_session_not_the_body(
        self, client: AsyncClient
    ):
        """`decided_by` is the logged-in user, and the client never chose it."""
        token = await token_with_role(client, UserRole.OPERATIONS)
        company_id = await make_company()

        body = (
            await client.post(
                f"{_url(company_id)}/decisions",
                json={"to_value": "IN_REVIEW"},
                headers=auth_header(token),
            )
        ).json()

        assert body["decided_by"]
        # A real user id, not something the request could have supplied.
        uuid.UUID(body["decided_by"])

    @pytest.mark.parametrize(
        "forbidden",
        [
            {"decided_by": "someone-else"},
            {"decided_by_kind": "AUTOMATED"},
            {"source": "RXIL"},
            {"evidence": []},
            {"evidence_ids": ["00000000-0000-4000-8000-000000000000"]},
            {"company_id": "00000000-0000-4000-8000-000000000000"},
            {"decided_at": "2020-01-01T00:00:00Z"},
            {"supersedes_decision_id": "00000000-0000-4000-8000-000000000000"},
        ],
    )
    async def test_a_field_that_is_the_server_s_is_refused_not_ignored(
        self, client: AsyncClient, forbidden
    ):
        """`extra="forbid"`: the caller learns the field is not theirs.

        Silently ignoring these would be worse than refusing them — a caller could
        believe it had recorded an `AUTOMATED` decision from `RXIL` on behalf of
        another user, and nothing would say otherwise.
        """
        token = await token_with_role(client, UserRole.OPERATIONS)
        company_id = await make_company()

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "IN_REVIEW", **forbidden},
            headers=auth_header(token),
        )

        assert response.status_code == 422, response.text

    async def test_a_move_the_company_cannot_make_is_409(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()  # NOT_STARTED

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "FLAGGED", "reason": "a hit"},
            headers=auth_header(token),
        )

        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "BACKGROUND_CHECK_MOVE_NOT_ALLOWED"
        # Plain values, not `BackgroundCheckState.NOT_STARTED`: a client reads these.
        assert body["error_context"] == {"from_value": "NOT_STARTED", "to_value": "FLAGGED"}
        assert "BackgroundCheckState" not in body["detail"]

    async def test_operations_flagging_is_403_by_the_service_not_the_route(
        self, client: AsyncClient
    ):
        """The route admits OPERATIONS; the per-move rule is what refuses them.

        The refusal that a route-level check alone would miss, since this same route
        serves the move OPERATIONS *is* allowed to make.
        """
        token = await token_with_role(client, UserRole.OPERATIONS)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "FLAGGED", "reason": "a hit"},
            headers=auth_header(token),
        )

        assert response.status_code == 403
        assert response.json()["error_code"] == "BACKGROUND_CHECK_ROLE_NOT_ALLOWED"

    async def test_a_move_without_its_reason_is_422(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "FLAGGED"},
            headers=auth_header(token),
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "BACKGROUND_CHECK_REASON_REQUIRED"

    async def test_clearing_without_a_risk_rating_is_422(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "CLEAR", "reason": "looks fine"},
            headers=auth_header(token),
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "BACKGROUND_CHECK_RISK_REQUIRED"

    async def test_clearing_with_prerequisites_outstanding_is_409_naming_them(
        self, client: AsyncClient
    ):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "CLEAR", "reason": "ready", "risk_rating": "LOW"},
            headers=auth_header(token),
        )

        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "BACKGROUND_CHECK_PREREQUISITES_UNMET"
        assert "screening_items_answered" in body["error_context"]["unmet"]

    async def test_operations_cannot_set_a_risk_by_starting_a_check(self, client: AsyncClient):
        """Risk is compliance's, and only on CLEAR — refused, not stored."""
        token = await token_with_role(client, UserRole.OPERATIONS)
        company_id = await make_company()

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "IN_REVIEW", "risk_rating": "CRITICAL"},
            headers=auth_header(token),
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "BACKGROUND_CHECK_RISK_NOT_ALLOWED"
        standing = await client.get(_url(company_id), headers=auth_header(token))
        assert standing.json()["value"] == "NOT_STARTED"
        assert standing.json()["risk_rating"] is None

    async def test_a_request_from_a_stale_screen_is_409(self, client: AsyncClient):
        """The screen saw NOT_STARTED; someone started the check meanwhile."""
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "IN_REVIEW", "from_value": "NOT_STARTED"},
            headers=auth_header(token),
        )

        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "BACKGROUND_CHECK_STATE_CHANGED"
        assert body["error_context"] == {"expected": "NOT_STARTED", "current": "IN_REVIEW"}

    async def test_a_request_naming_the_current_value_is_accepted(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "FLAGGED", "reason": "a hit", "from_value": "IN_REVIEW"},
            headers=auth_header(token),
        )

        # FLAGGED needs a second approver (maker-checker): proposed, not moved.
        assert response.status_code == 202, response.text
        body = response.json()
        assert (body["from_value"], body["to_value"], body["status"]) == (
            "IN_REVIEW",
            "FLAGGED",
            "OPEN",
        )

    async def test_an_invalid_risk_value_is_422(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)

        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "CLEAR", "reason": "r", "risk_rating": "PROHIBITED"},
            headers=auth_header(token),
        )

        # "Prohibited" is an outcome (`FLAGGED`), never a risk value (decision 6).
        assert response.status_code == 422

    async def test_an_unknown_value_is_422(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        response = await client.post(
            f"{_url(company_id)}/decisions",
            json={"to_value": "APPROVED"},
            headers=auth_header(token),
        )
        assert response.status_code == 422

    async def test_an_unknown_company_is_404(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.OPERATIONS)
        response = await client.post(
            f"{_url(uuid.uuid4())}/decisions",
            json={"to_value": "IN_REVIEW"},
            headers=auth_header(token),
        )
        assert response.status_code == 404

    async def test_without_a_token_it_is_401(self, client: AsyncClient):
        company_id = await make_company()
        response = await client.post(
            f"{_url(company_id)}/decisions", json={"to_value": "IN_REVIEW"}
        )
        assert response.status_code == 401

    async def test_a_full_journey_through_the_api(self, client: AsyncClient):
        """Start, ask for more, record what arrived, flag, hold, reassess — all through
        HTTP; the flag and the hold proposed by one officer and approved by another."""
        ops = await token_with_role(client, UserRole.OPERATIONS)
        compliance = await token_with_role(client, UserRole.COMPLIANCE)
        checker = (await make_compliance_user(client, label="api-checker")).token
        company_id = await make_company()
        await _document(company_id, DocumentScanStatus.AVAILABLE)

        async def move(token, **body):
            return await client.post(
                f"{_url(company_id)}/decisions", json=body, headers=auth_header(token)
            )

        async def two_person(**body) -> int:
            """Proposed by `compliance` (202), approved by `checker` (200)."""
            proposed = await move(compliance, **body)
            assert proposed.status_code == 202, proposed.text
            approved = await client.post(
                f"{_url(company_id)}/proposals/{proposed.json()['id']}/approve",
                headers=auth_header(checker),
            )
            return approved.status_code

        assert (await move(ops, to_value="IN_REVIEW")).status_code == 201
        assert (
            await move(compliance, to_value="MORE_INFO", reason="need the accounts")
        ).status_code == 201
        assert (
            await move(ops, to_value="IN_REVIEW", reason="accounts received")
        ).status_code == 201
        assert await two_person(to_value="FLAGGED", reason="a director matched") == 200
        assert await two_person(to_value="ON_HOLD", reason="awaiting the regulator") == 200
        assert (
            await move(compliance, to_value="IN_REVIEW", reason="the regulator replied")
        ).status_code == 201

        standing = (
            await client.get(_url(company_id), headers=auth_header(compliance))
        ).json()
        assert standing["value"] == "IN_REVIEW"

        decisions = (
            await client.get(
                f"{_url(company_id)}/decisions", headers=auth_header(compliance)
            )
        ).json()
        assert decisions["total"] == 6
        # Newest first, and one unbroken chain.
        assert decisions["decisions"][0]["to_value"] == "IN_REVIEW"
        assert decisions["decisions"][-1]["from_value"] == "NOT_STARTED"


# ── GET the decisions ────────────────────────────────────────────────────────


class TestListDecisions:
    async def test_a_company_with_no_decisions_lists_none(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()

        body = (
            await client.get(
                f"{_url(company_id)}/decisions", headers=auth_header(token)
            )
        ).json()

        assert body["total"] == 0
        assert body["decisions"] == []

    async def test_each_decision_carries_its_evidence_snapshot(
        self, client: AsyncClient
    ):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        document_id = await _document(company_id, DocumentScanStatus.AVAILABLE)
        await _start(company_id)

        body = (
            await client.get(
                f"{_url(company_id)}/decisions", headers=auth_header(token)
            )
        ).json()

        evidence = body["decisions"][0]["evidence"]
        documents = [
            item["crm_document_id"] for item in evidence if item["kind"] == "DOCUMENT"
        ]
        assert str(document_id) in documents

    async def test_an_unknown_company_is_404_not_an_empty_list(
        self, client: AsyncClient
    ):
        """An empty list would read as "this company has no decisions"."""
        token = await token_with_role(client, UserRole.COMPLIANCE)
        response = await client.get(
            f"{_url(uuid.uuid4())}/decisions", headers=auth_header(token)
        )
        assert response.status_code == 404

    async def test_it_pages(self, client: AsyncClient):
        token = await token_with_role(client, UserRole.COMPLIANCE)
        company_id = await make_company()
        await _start(company_id)
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).request_more_info(
                company_id, note="n", actor_id="c", actor_role=UserRole.COMPLIANCE
            )

        body = (
            await client.get(
                f"{_url(company_id)}/decisions?limit=1&offset=0",
                headers=auth_header(token),
            )
        ).json()

        assert body["total"] == 2
        assert len(body["decisions"]) == 1
        assert body["limit"] == 1

    async def test_without_a_token_it_is_401(self, client: AsyncClient):
        company_id = await make_company()
        assert (await client.get(f"{_url(company_id)}/decisions")).status_code == 401
