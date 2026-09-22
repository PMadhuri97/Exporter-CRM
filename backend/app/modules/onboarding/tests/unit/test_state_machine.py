"""
KYC case state machine tests.

Covers every acceptance criterion the backlog states for this ticket:

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

from app.modules.onboarding.domain.entities.case import Case
from app.modules.onboarding.domain.entities.enums import CaseState, TransitionSource
from app.modules.onboarding.domain.policies.state_machine import (
    LEGAL_TRANSITIONS,
    DirectStateAssignmentError,
    IllegalTransitionError,
    allowed_next_states,
    assert_legal,
    is_legal,
    permit_state_write,
)
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
    email = f"sm-{uuid.uuid4().hex[:8]}@aner-test.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password1", "role": "API_USER"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password1"}
    )
    return login.json()["access_token"]


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


# ── Unit: the transition table itself ────────────────────────────────────────

def test_table_covers_all_twelve_states():
    """Every state is a key. A missing key would be a KeyError at runtime, not a 409."""
    assert set(LEGAL_TRANSITIONS) == set(CaseState)
    assert len(CaseState) == 12


def test_table_targets_are_all_real_states():
    for previous, targets in LEGAL_TRANSITIONS.items():
        for target in targets:
            assert isinstance(target, CaseState)
            assert target is not previous, "a state may not transition to itself"


def test_every_state_is_reachable_except_the_origin():
    """DRAFT is the only entry point; every other state must be arrivable."""
    reachable = {t for targets in LEGAL_TRANSITIONS.values() for t in targets}
    assert reachable == set(CaseState) - {CaseState.DRAFT}


def test_all_four_transition_sources_are_supported():
    from app.modules.onboarding.application.case_service import CaseService

    for source in TransitionSource:
        assert CaseService._actor_type_for(source) is not None
    assert len(TransitionSource) == 4


def test_a_provider_state_never_reaches_a_decision_by_itself():
    """
    The baseline principle as a table assertion: PROVIDER_FAILED cannot decide a case.

    PROVIDER_COMPLETED *may* move to APPROVED/REJECTED, but only because a decision
    drives that move — never the provider.
    """
    assert CaseState.APPROVED not in allowed_next_states(CaseState.PROVIDER_FAILED)
    assert CaseState.REJECTED not in allowed_next_states(CaseState.PROVIDER_FAILED)


def test_is_legal_and_assert_legal_agree():
    assert is_legal(CaseState.DRAFT, CaseState.SUBMITTED)
    assert not is_legal(CaseState.DRAFT, CaseState.APPROVED)
    assert_legal(CaseState.DRAFT, CaseState.SUBMITTED)
    with pytest.raises(IllegalTransitionError):
        assert_legal(CaseState.DRAFT, CaseState.APPROVED)


def test_illegal_transition_error_is_a_409_with_a_stable_error_code():
    error = IllegalTransitionError(CaseState.DRAFT, CaseState.APPROVED)
    assert error.status_code == 409
    assert error.error_code == "ILLEGAL_CASE_STATE_TRANSITION"
    assert error.previous_state is CaseState.DRAFT
    assert error.next_state is CaseState.APPROVED


# ── Unit: the parametrized legal / illegal matrix ────────────────────────────
#
# 12 × 12 = 144 pairs. Every pair the table names is legal; every pair it does not
# name raises. This is the whole contract of the guard, exhaustively.

@pytest.mark.parametrize("previous", list(CaseState))
@pytest.mark.parametrize("next_state", list(CaseState))
def test_transition_matrix(previous: CaseState, next_state: CaseState):
    if next_state in LEGAL_TRANSITIONS[previous]:
        assert_legal(previous, next_state)  # must not raise
    else:
        with pytest.raises(IllegalTransitionError):
            assert_legal(previous, next_state)


# ── Unit: direct state mutation is impossible ────────────────────────────────

@pytest.mark.asyncio
async def test_repository_refuses_direct_state_mutation():
    """The repository door (already closed earlier; re-asserted here as the state machine's own AC)."""
    from app.modules.onboarding.infrastructure.repositories import (
        CaseRepository,
        DirectStateMutationError,
    )

    repo = CaseRepository(session=None)  # never reaches the session
    with pytest.raises(DirectStateMutationError):
        await repo.update(Case(), state=CaseState.APPROVED)


def test_orm_attribute_refuses_direct_state_assignment():
    """
    The ORM door: `case.state = …` on a persisted case raises, so no service can
    bypass the machine by holding the model instance directly.

    A case with a database identity is simulated by giving it a primary key and
    telling the instance state it is persistent — exactly what SQLAlchemy does after
    a flush.
    """
    from sqlalchemy import inspect

    case = Case(state=CaseState.DRAFT)  # transient: initialisation is permitted
    assert case.state is CaseState.DRAFT

    case.id = uuid.uuid4()
    inspect(case).key = (Case, (case.id,), None)  # now it "exists" in the database

    with pytest.raises(DirectStateAssignmentError):
        case.state = CaseState.APPROVED

    assert case.state is CaseState.DRAFT, "a rejected assignment must not mutate state"


def test_the_state_machine_may_assign_state():
    """The same assignment inside `permit_state_write()` is the machine's own path."""
    from sqlalchemy import inspect

    case = Case(state=CaseState.DRAFT)
    case.id = uuid.uuid4()
    inspect(case).key = (Case, (case.id,), None)

    with permit_state_write():
        case.state = CaseState.SUBMITTED

    assert case.state is CaseState.SUBMITTED


def test_permission_does_not_leak_out_of_its_context():
    from sqlalchemy import inspect

    case = Case(state=CaseState.DRAFT)
    case.id = uuid.uuid4()
    inspect(case).key = (Case, (case.id,), None)

    with permit_state_write():
        case.state = CaseState.SUBMITTED

    with pytest.raises(DirectStateAssignmentError):
        case.state = CaseState.PROVIDER_PENDING


# ── Integration: happy path ──────────────────────────────────────────────────

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
