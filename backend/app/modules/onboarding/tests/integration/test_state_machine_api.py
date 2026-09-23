"""
KYC case state machine — the API-level half.

Split out of ``tests/unit/test_state_machine.py``: these 21 tests drive the real
router over ASGI and read ``onboarding.onboarding_case`` /
``onboarding.case_state_transition`` / ``audit.audit_events`` with a live psycopg2
connection. Every one of them fails with ``ConnectionRefusedError`` when Postgres
is not up, so under ``unit/`` they were telling anyone who ran the unit suite on a
bare machine that the state machine was broken.

The 12 genuinely-unit tests — the transition table, the 12x12 legal/illegal matrix,
and the two direct-mutation guards — stay in ``tests/unit/test_state_machine.py``
and still need no infrastructure.

Between them the two files carry the same acceptance criteria as before:

  • Happy-path transition test passes.
  • Illegal transition returns 409 and does not mutate state.
  • Every successful transition writes `case_state_transition` AND `audit_event`.
  • Direct status mutation is blocked by a service-boundary / repository rule.

Plus the definition of done: all 12 states, all 4 sources, and every transition
recording actor, reason, timestamp, previous state, next state, source, and
correlation id.
"""
import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import token_with_role
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

# ── sync DB helpers (per project test conventions) ────────────────────────────

def _pg_connect():
    import psycopg2

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _fetchall(query: str, params: tuple = ()):
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _scalar(query: str, params: tuple = ()):
    rows = _fetchall(query, params)
    return rows[0][0] if rows else None


def _db_state(case_id: str) -> str:
    return _scalar("SELECT state FROM onboarding.onboarding_case WHERE id = %s", (case_id,))


def _transition_rows(case_id: str):
    return _fetchall(
        "SELECT previous_state, next_state, source, actor_id, actor_type, reason, "
        "correlation_id, created_at FROM onboarding.case_state_transition "
        "WHERE case_id = %s ORDER BY created_at",
        (case_id,),
    )


def _audit_rows(case_id: str, event_type: str = "onboarding.case.state_changed"):
    return _fetchall(
        "SELECT payload::text, actor_type, correlation_id FROM audit.audit_events "
        "WHERE event_type = %s AND payload->>'case_id' = %s ORDER BY created_at",
        (event_type, case_id),
    )


# ── auth + request helpers ────────────────────────────────────────────────────

async def _api_token(client: AsyncClient) -> str:
    # COMPLIANCE clears every write gate on these routes; the refusals for the
    # other roles are covered in test_route_authorization.py.
    return await token_with_role(client, UserRole.COMPLIANCE)


async def _create_case(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/onboarding/cases",
        json={
            "tenant_id": str(uuid.uuid4()),
            "country_code": "IN",
            "case_type": "KYC",
            "subject_type": "INDIVIDUAL",
            "required_checks": ["IDENTITY"],
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _transition(
    client: AsyncClient,
    token: str,
    case_id: str,
    next_state: str,
    *,
    source: str = "USER_ACTION",
    reason: str | None = "test transition",
    correlation_id: str | None = None,
):
    headers = {"Authorization": f"Bearer {token}"}
    if correlation_id is not None:
        headers["X-Correlation-Id"] = correlation_id
    body = {"next_state": next_state, "source": source}
    if reason is not None:
        body["reason"] = reason
    return await client.post(
        f"/api/v1/onboarding/cases/{case_id}/transitions", json=body, headers=headers
    )


async def _drive(client: AsyncClient, token: str, case_id: str, *states: str) -> None:
    """Walk a case along a legal path, asserting each hop succeeds."""
    for state in states:
        resp = await _transition(client, token, case_id, state)
        assert resp.status_code == 200, f"{state}: {resp.text}"


@pytest.mark.asyncio
async def test_happy_path_transition(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    resp = await _transition(client, token, case_id, "SUBMITTED")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "SUBMITTED"
    assert _db_state(case_id) == "SUBMITTED"


@pytest.mark.asyncio
async def test_full_lifecycle_to_approved(client: AsyncClient):
    """DRAFT → SUBMITTED → PROVIDER_PENDING → PROVIDER_COMPLETED → APPROVED."""
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    await _drive(
        client, token, case_id,
        "SUBMITTED", "PROVIDER_PENDING", "PROVIDER_COMPLETED", "APPROVED",
    )
    assert _db_state(case_id) == "APPROVED"
    assert len(_transition_rows(case_id)) == 4


@pytest.mark.asyncio
async def test_provider_failure_can_be_retried_but_never_decides(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)
    await _drive(client, token, case_id, "SUBMITTED", "PROVIDER_PENDING", "PROVIDER_FAILED")

    # A failure cannot approve the case…
    illegal = await _transition(client, token, case_id, "APPROVED", source="PROVIDER_CALLBACK")
    assert illegal.status_code == 409
    assert _db_state(case_id) == "PROVIDER_FAILED"

    # …but the run can be retried.
    retry = await _transition(client, token, case_id, "PROVIDER_PENDING", source="SYSTEM")
    assert retry.status_code == 200
    assert _db_state(case_id) == "PROVIDER_PENDING"


@pytest.mark.asyncio
async def test_reopen_by_exception_from_a_closed_case(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)
    await _drive(client, token, case_id, "CLOSED")

    resp = await _transition(
        client, token, case_id, "REOPENED_BY_EXCEPTION", source="ADMIN_OVERRIDE"
    )
    assert resp.status_code == 200
    assert _db_state(case_id) == "REOPENED_BY_EXCEPTION"


@pytest.mark.asyncio
async def test_every_transition_source_is_accepted(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    # One legal hop per source, so all four reach the database.
    await _transition(client, token, case_id, "SUBMITTED", source="USER_ACTION")
    await _transition(client, token, case_id, "PROVIDER_PENDING", source="SYSTEM")
    await _transition(client, token, case_id, "PROVIDER_COMPLETED", source="PROVIDER_CALLBACK")
    resp = await _transition(client, token, case_id, "APPROVED", source="ADMIN_OVERRIDE")
    assert resp.status_code == 200

    sources = [row[2] for row in _transition_rows(case_id)]
    assert sources == ["USER_ACTION", "SYSTEM", "PROVIDER_CALLBACK", "ADMIN_OVERRIDE"]


# ── Integration: illegal transitions ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_illegal_transition_returns_409_and_does_not_mutate_state(client: AsyncClient):
    """The headline acceptance criterion."""
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    resp = await _transition(client, token, case_id, "APPROVED")
    assert resp.status_code == 409
    assert _db_state(case_id) == "DRAFT", "an illegal transition must not mutate state"


@pytest.mark.asyncio
async def test_illegal_transition_body_carries_error_code_and_correlation_id(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)
    correlation_id = str(uuid.uuid4())

    resp = await _transition(
        client, token, case_id, "APPROVED", correlation_id=correlation_id
    )
    assert resp.status_code == 409

    body = resp.json()
    assert body["error_code"] == "ILLEGAL_CASE_STATE_TRANSITION"
    assert body["correlation_id"] == correlation_id
    assert "DRAFT" in body["detail"] and "APPROVED" in body["detail"]


@pytest.mark.asyncio
async def test_illegal_transition_writes_no_transition_row_and_no_audit_event(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    resp = await _transition(client, token, case_id, "REJECTED")
    assert resp.status_code == 409
    assert _transition_rows(case_id) == []
    assert _audit_rows(case_id) == []


@pytest.mark.asyncio
async def test_self_transition_is_illegal(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    resp = await _transition(client, token, case_id, "DRAFT")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_transition_on_unknown_case_returns_404(client: AsyncClient):
    token = await _api_token(client)
    resp = await _transition(client, token, str(uuid.uuid4()), "SUBMITTED")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_transition_requires_auth(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/onboarding/cases/{uuid.uuid4()}/transitions",
        json={"next_state": "SUBMITTED", "source": "USER_ACTION"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unknown_state_or_source_is_422(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    bad_state = await _transition(client, token, case_id, "NOT_A_STATE")
    assert bad_state.status_code == 422

    bad_source = await _transition(client, token, case_id, "SUBMITTED", source="GOD_MODE")
    assert bad_source.status_code == 422
    assert _db_state(case_id) == "DRAFT"


# ── Integration: what a successful transition records ────────────────────────

@pytest.mark.asyncio
async def test_transition_records_every_required_field(client: AsyncClient):
    """
    Rule: "Every transition records actor, reason, timestamp, previous state,
    next state, source, and correlation id."
    """
    token = await _api_token(client)
    case_id = await _create_case(client, token)
    correlation_id = str(uuid.uuid4())

    resp = await _transition(
        client,
        token,
        case_id,
        "SUBMITTED",
        source="USER_ACTION",
        reason="subject completed the form",
        correlation_id=correlation_id,
    )
    assert resp.status_code == 200

    rows = _transition_rows(case_id)
    assert len(rows) == 1
    previous, next_state, source, actor_id, actor_type, reason, corr, created_at = rows[0]

    assert previous == "DRAFT"
    assert next_state == "SUBMITTED"
    assert source == "USER_ACTION"
    assert actor_id is not None, "a USER_ACTION transition has a human actor"
    assert actor_type == "API_CLIENT"
    assert reason == "subject completed the form"
    assert str(corr) == correlation_id
    assert created_at is not None


@pytest.mark.asyncio
async def test_transition_writes_both_a_transition_row_and_an_audit_event(client: AsyncClient):
    """Acceptance criterion: `case_state_transition` AND `audit_event`, on every move."""
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    await _drive(client, token, case_id, "SUBMITTED", "PROVIDER_PENDING")

    assert len(_transition_rows(case_id)) == 2
    assert len(_audit_rows(case_id)) == 2


@pytest.mark.asyncio
async def test_audit_event_carries_the_transition_detail(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)
    correlation_id = str(uuid.uuid4())

    await _transition(
        client, token, case_id, "SUBMITTED", reason="ready", correlation_id=correlation_id
    )

    payload, actor_type, corr = _audit_rows(case_id)[0]
    assert '"previous_state": "DRAFT"' in payload
    assert '"next_state": "SUBMITTED"' in payload
    assert '"source": "USER_ACTION"' in payload
    assert '"reason": "ready"' in payload
    assert actor_type == "API_CLIENT"
    assert str(corr) == correlation_id


@pytest.mark.asyncio
async def test_system_and_provider_transitions_record_no_human_actor(client: AsyncClient):
    """§4.11: a null `actor_id` means the platform itself acted."""
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    await _transition(client, token, case_id, "SUBMITTED", source="SYSTEM")
    await _transition(client, token, case_id, "PROVIDER_PENDING", source="PROVIDER_CALLBACK")

    for _, _, _, actor_id, actor_type, _, _, _ in _transition_rows(case_id):
        assert actor_id is None
        assert actor_type == "SYSTEM"


@pytest.mark.asyncio
async def test_admin_override_is_recorded_as_a_compliance_officer(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    await _transition(client, token, case_id, "CLOSED", source="ADMIN_OVERRIDE")

    _, _, _, actor_id, actor_type, _, _, _ = _transition_rows(case_id)[0]
    assert actor_type == "COMPLIANCE_OFFICER"
    assert actor_id is not None


@pytest.mark.asyncio
async def test_transition_audit_payload_carries_no_pii(client: AsyncClient):
    """§5.3 again: the audit payload stays PII-free on the transition path too."""
    token = await _api_token(client)
    resp = await client.post(
        "/api/v1/onboarding/cases",
        json={
            "tenant_id": str(uuid.uuid4()),
            "country_code": "IN",
            "case_type": "KYC",
            "subject_type": "INDIVIDUAL",
            "profile": {"first_name": "Meera", "last_name": "Iyer", "email": "m@example.com"},
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    case_id = resp.json()["id"]
    await _transition(client, token, case_id, "SUBMITTED")

    payload, _, _ = _audit_rows(case_id)[0]
    for pii in ("Meera", "Iyer", "m@example.com"):
        assert pii not in payload


@pytest.mark.asyncio
async def test_reason_is_optional(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    resp = await _transition(client, token, case_id, "SUBMITTED", reason=None)
    assert resp.status_code == 200
    assert _transition_rows(case_id)[0][5] is None


# ── Integration: the state history endpoint ──────────────────────────────────

@pytest.mark.asyncio
async def test_state_history_is_ordered_oldest_first(client: AsyncClient):
    token = await _api_token(client)
    case_id = await _create_case(client, token)
    await _drive(client, token, case_id, "SUBMITTED", "PROVIDER_PENDING", "PROVIDER_COMPLETED")

    resp = await client.get(
        f"/api/v1/onboarding/cases/{case_id}/transitions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 3
    assert [t["next_state"] for t in body["transitions"]] == [
        "SUBMITTED",
        "PROVIDER_PENDING",
        "PROVIDER_COMPLETED",
    ]
    assert body["transitions"][0]["previous_state"] == "DRAFT"


@pytest.mark.asyncio
async def test_state_history_of_an_untouched_case_is_empty(client: AsyncClient):
    """
    Decision D14: case creation writes **no genesis transition row**. `DRAFT` is the
    origin of the machine, not a move into it.
    """
    token = await _api_token(client)
    case_id = await _create_case(client, token)

    resp = await client.get(
        f"/api/v1/onboarding/cases/{case_id}/transitions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["transitions"] == []


@pytest.mark.asyncio
async def test_state_history_of_an_unknown_case_is_404(client: AsyncClient):
    token = await _api_token(client)
    resp = await client.get(
        f"/api/v1/onboarding/cases/{uuid.uuid4()}/transitions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
