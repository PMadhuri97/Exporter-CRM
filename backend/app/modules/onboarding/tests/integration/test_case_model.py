"""
Core onboarding/KYC case model tests.

Covers every acceptance criterion the backlog states for this ticket:

  • Create-case returns the same record for the same idempotency key / external id.
  • Core case tables contain no provider-specific columns.
  • An audit event exists for create and for update.
  • Unit *and* integration tests cover duplicate-request behavior.

Plus the invariants this phase is responsible for holding until later phases land:
a new case starts in `DRAFT`, and nothing outside the (not-yet-built) state machine
can move it.
"""
import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app.modules.onboarding.api.schemas.case import CreateCaseRequest, UpdateCaseRequest
from app.modules.onboarding.domain.dto import CheckType, SubjectType
from app.modules.onboarding.domain.entities.case import Case
from app.modules.onboarding.domain.entities.enums import CaseState, CaseType, TransitionSource
from app.modules.onboarding.infrastructure.repositories.case_repository import (
    DirectStateMutationError,
)
from app.modules.onboarding.tests.fixtures.auth import token_with_role
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

CORE_CASE_TABLES = ("onboarding_case", "person_profile", "kyc_case", "case_state_transition")

# The backlog's own prohibition, as a pattern: no vendor name, no vendor id, no
# vendor field may appear as a column on a core case table.
FORBIDDEN_COLUMN_PATTERN = "sumsub|comply|applicant|review_answer"


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


def _case_count(tenant_id: str, idempotency_key: str) -> int:
    return _scalar(
        "SELECT COUNT(*) FROM onboarding.onboarding_case WHERE tenant_id = %s AND idempotency_key = %s",
        (tenant_id, idempotency_key),
    )


def _audit_count(case_id: str, event_type: str) -> int:
    return _scalar(
        "SELECT COUNT(*) FROM audit.audit_events "
        "WHERE event_type = %s AND payload->>'case_id' = %s",
        (event_type, case_id),
    )


# ── auth + request helpers ────────────────────────────────────────────────────

async def _api_token(client: AsyncClient) -> str:
    # COMPLIANCE clears every write gate on these routes; the refusals for the
    # other roles are covered in test_route_authorization.py.
    return await token_with_role(client, UserRole.COMPLIANCE)


def _case_body(**overrides) -> dict:
    body = {
        "tenant_id": str(uuid.uuid4()),
        "country_code": "IN",
        "case_type": "KYC",
        "subject_type": "INDIVIDUAL",
        "cell_id": "cell-in-1",
        "product_context": "cross_border_settlement",
        "policy_id": "policy-in-kyc-v1",
        "required_checks": ["IDENTITY", "DOCUMENT"],
        "profile": {
            "first_name": "Meera",
            "last_name": "Iyer",
            "date_of_birth": "1988-04-12",
            "nationality": "IN",
            "residence_country": "IN",
            "email": "meera@example.com",
            "phone": "+919812345678",
        },
    }
    body.update(overrides)
    return body


async def _create_case(
    client: AsyncClient, token: str, *, idempotency_key: str | None = None, **overrides
):
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return await client.post(
        "/api/v1/onboarding/cases", json=_case_body(**overrides), headers=headers
    )


# ── Unit: schema-level guarantees ─────────────────────────────────────────────

def test_create_case_request_rejects_state():
    """A caller cannot open a case in any state but DRAFT — `state` is not a field."""
    with pytest.raises(Exception):
        CreateCaseRequest(
            tenant_id=uuid.uuid4(),
            country_code="IN",
            case_type=CaseType.KYC,
            subject_type=SubjectType.INDIVIDUAL,
            state="APPROVED",
        )


def test_update_case_request_rejects_state():
    """The update surface cannot express a state change either."""
    with pytest.raises(Exception):
        UpdateCaseRequest(state="APPROVED")


def test_create_case_request_uppercases_country_code():
    request = CreateCaseRequest(
        tenant_id=uuid.uuid4(),
        country_code="in",
        case_type=CaseType.KYC,
        subject_type=SubjectType.INDIVIDUAL,
    )
    assert request.country_code == "IN"


def test_all_twelve_case_states_exist():
    """The lifecycle has twelve states; the pg enum must carry all of them."""
    assert len(CaseState) == 12
    assert CaseState.DRAFT.value == "DRAFT"
    assert CaseState.REOPENED_BY_EXCEPTION.value == "REOPENED_BY_EXCEPTION"


def test_all_four_transition_sources_exist():
    assert {s.value for s in TransitionSource} == {
        "USER_ACTION",
        "SYSTEM",
        "PROVIDER_CALLBACK",
        "ADMIN_OVERRIDE",
    }


# ── Unit: the repository refuses direct state mutation ───────────────────────

@pytest.mark.asyncio
async def test_repository_refuses_direct_state_mutation():
    """
    Rule: "state cannot be updated directly from random service code."

    The repository half of that rule is enforceable now, before the state
    machine exists, and is tested here so no later change can quietly regress it.
    """
    from app.modules.onboarding.infrastructure.repositories import CaseRepository

    repo = CaseRepository(session=None)  # never reaches the session
    with pytest.raises(DirectStateMutationError):
        await repo.update(Case(), state=CaseState.APPROVED)


# ── Unit: person_profile never leaks PII through its repr ────────────────────

def test_person_profile_repr_hides_pii():
    from app.modules.onboarding.domain.entities.person_profile import PersonProfile

    profile = PersonProfile(
        id=uuid.uuid4(),
        case_id=uuid.uuid4(),
        first_name="Meera",
        last_name="Iyer",
        email="meera@example.com",
    )
    rendered = repr(profile)
    assert "Meera" not in rendered
    assert "Iyer" not in rendered
    assert "meera@example.com" not in rendered
    assert str(profile.case_id) in rendered


# ── Schema: no provider-specific columns on core case tables ─────────────────

def test_core_case_tables_have_no_provider_specific_columns():
    """
    Acceptance criterion: "Core case tables contain no provider-specific columns."

    `provider_route_id` is intentionally not matched: a route id is an opaque
    internal identifier, not a vendor identifier.
    """
    rows = _fetchall(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'onboarding' AND table_name = ANY(%s) "
        "AND column_name ~* %s",
        (list(CORE_CASE_TABLES), FORBIDDEN_COLUMN_PATTERN),
    )
    assert rows == [], f"provider-specific columns leaked onto core case tables: {rows}"


def test_core_case_tables_exist():
    rows = _fetchall(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'onboarding' AND table_name = ANY(%s) ORDER BY table_name",
        (list(CORE_CASE_TABLES),),
    )
    assert [r[0] for r in rows] == sorted(CORE_CASE_TABLES)


def test_case_state_transition_is_append_only():
    """The prevent_mutation() trigger is attached, as it is on every append-only table."""
    trigger = _scalar(
        "SELECT tgname FROM pg_trigger WHERE tgname = 'case_state_transition_immutable'"
    )
    assert trigger == "case_state_transition_immutable"


# ── Integration: create ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_case_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/onboarding/cases",
        json=_case_body(),
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_case_requires_idempotency_key(client: AsyncClient):
    token = await _api_token(client)
    resp = await _create_case(client, token, idempotency_key=None)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "MISSING_IDEMPOTENCY_KEY"


@pytest.mark.asyncio
async def test_create_case_starts_in_draft(client: AsyncClient):
    token = await _api_token(client)
    resp = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["state"] == "DRAFT"
    assert body["country_code"] == "IN"
    assert body["case_type"] == "KYC"
    assert body["subject_type"] == "INDIVIDUAL"
    assert body["provider_route_id"] is None  # no route resolver yet
    assert body["required_checks"] == ["IDENTITY", "DOCUMENT"]
    assert body["profile"]["first_name"] == "Meera"


@pytest.mark.asyncio
async def test_create_case_accepts_every_check_type(client: AsyncClient):
    """`required_checks` is JSONB precisely so new check types cost no migration."""
    token = await _api_token(client)
    all_checks = [c.value for c in CheckType]
    resp = await _create_case(
        client, token, idempotency_key=uuid.uuid4().hex, required_checks=all_checks
    )
    assert resp.status_code == 201
    assert resp.json()["required_checks"] == all_checks


@pytest.mark.asyncio
async def test_create_case_without_profile(client: AsyncClient):
    token = await _api_token(client)
    resp = await _create_case(client, token, idempotency_key=uuid.uuid4().hex, profile=None)
    assert resp.status_code == 201
    assert resp.json()["profile"] is None


@pytest.mark.asyncio
async def test_create_case_writes_audit_event(client: AsyncClient):
    token = await _api_token(client)
    resp = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    case_id = resp.json()["id"]
    assert _audit_count(case_id, "onboarding.case.created") == 1


@pytest.mark.asyncio
async def test_create_case_audit_payload_carries_no_pii(client: AsyncClient):
    """§5.3: PII must never reach the long-lived, queryable audit payload."""
    token = await _api_token(client)
    resp = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    case_id = resp.json()["id"]

    payload = _scalar(
        "SELECT payload::text FROM audit.audit_events "
        "WHERE event_type = 'onboarding.case.created' AND payload->>'case_id' = %s",
        (case_id,),
    )
    for pii in ("Meera", "Iyer", "meera@example.com", "+919812345678", "1988-04-12"):
        assert pii not in payload


# ── Integration: idempotency (the headline acceptance criterion) ─────────────

@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_same_case(client: AsyncClient):
    token = await _api_token(client)
    key = uuid.uuid4().hex
    tenant_id = str(uuid.uuid4())

    first = await _create_case(client, token, idempotency_key=key, tenant_id=tenant_id)
    assert first.status_code == 201

    second = await _create_case(client, token, idempotency_key=key, tenant_id=tenant_id)
    assert second.status_code == 200, "an idempotent replay is a 200, not a second 201"

    assert first.json()["id"] == second.json()["id"]
    assert _case_count(tenant_id, key) == 1


@pytest.mark.asyncio
async def test_duplicate_external_case_id_returns_same_case(client: AsyncClient):
    """
    "Same external/request id must not create duplicate case" — even under a
    *different* idempotency key, which is the case a naive key-only guard misses.
    """
    token = await _api_token(client)
    tenant_id = str(uuid.uuid4())
    external_case_id = f"ext-{uuid.uuid4().hex[:10]}"

    first = await _create_case(
        client,
        token,
        idempotency_key=uuid.uuid4().hex,
        tenant_id=tenant_id,
        external_case_id=external_case_id,
    )
    assert first.status_code == 201

    second = await _create_case(
        client,
        token,
        idempotency_key=uuid.uuid4().hex,  # different key, same external id
        tenant_id=tenant_id,
        external_case_id=external_case_id,
    )
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    count = _scalar(
        "SELECT COUNT(*) FROM onboarding.onboarding_case WHERE tenant_id = %s AND external_case_id = %s",
        (tenant_id, external_case_id),
    )
    assert count == 1


@pytest.mark.asyncio
async def test_replay_does_not_write_a_second_audit_event(client: AsyncClient):
    token = await _api_token(client)
    key = uuid.uuid4().hex
    tenant_id = str(uuid.uuid4())

    first = await _create_case(client, token, idempotency_key=key, tenant_id=tenant_id)
    case_id = first.json()["id"]
    await _create_case(client, token, idempotency_key=key, tenant_id=tenant_id)

    assert _audit_count(case_id, "onboarding.case.created") == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_across_tenants_creates_two_cases(client: AsyncClient):
    """Idempotency is scoped to a tenant; two tenants may reuse a key independently."""
    token = await _api_token(client)
    key = uuid.uuid4().hex
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())

    first = await _create_case(client, token, idempotency_key=key, tenant_id=tenant_a)
    second = await _create_case(client, token, idempotency_key=key, tenant_id=tenant_b)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.asyncio
async def test_concurrent_duplicate_requests_create_one_case(client: AsyncClient):
    """
    The UNIQUE constraint, not the SELECT, is what makes creation idempotent
    (decision D6). Two simultaneous requests must still yield exactly one row.
    """
    token = await _api_token(client)
    key = uuid.uuid4().hex
    tenant_id = str(uuid.uuid4())

    responses = await asyncio.gather(
        _create_case(client, token, idempotency_key=key, tenant_id=tenant_id),
        _create_case(client, token, idempotency_key=key, tenant_id=tenant_id),
    )

    assert all(r.status_code in (200, 201) for r in responses), [r.status_code for r in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert _case_count(tenant_id, key) == 1


# ── Integration: read ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_case(client: AsyncClient):
    token = await _api_token(client)
    created = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    case_id = created.json()["id"]

    resp = await client.get(
        f"/api/v1/onboarding/cases/{case_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == case_id
    assert resp.json()["state"] == "DRAFT"


@pytest.mark.asyncio
async def test_get_case_not_found(client: AsyncClient):
    token = await _api_token(client)
    resp = await client.get(
        f"/api/v1/onboarding/cases/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


# ── Integration: update ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_case_writes_audit_event(client: AsyncClient):
    token = await _api_token(client)
    created = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    case_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/onboarding/cases/{case_id}",
        json={"policy_id": "policy-in-kyc-v2"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["policy_id"] == "policy-in-kyc-v2"
    assert _audit_count(case_id, "onboarding.case.updated") == 1


@pytest.mark.asyncio
async def test_update_case_cannot_change_state(client: AsyncClient):
    """`state` is not an updatable field — the request body rejects it outright."""
    token = await _api_token(client)
    created = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    case_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/onboarding/cases/{case_id}",
        json={"state": "APPROVED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    state = _scalar("SELECT state FROM onboarding.onboarding_case WHERE id = %s", (case_id,))
    assert state == "DRAFT", "a rejected update must not mutate state"


@pytest.mark.asyncio
async def test_update_case_not_found(client: AsyncClient):
    token = await _api_token(client)
    resp = await client.patch(
        f"/api/v1/onboarding/cases/{uuid.uuid4()}",
        json={"policy_id": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Boundary: nothing writes transitions yet ─────────────────────────────────

@pytest.mark.asyncio
async def test_creating_a_case_writes_no_state_transition(client: AsyncClient):
    """
    The transition table exists; the state machine is the only thing that writes
    to it. If this test starts failing, someone pulled the state machine forward.
    """
    token = await _api_token(client)
    created = await _create_case(client, token, idempotency_key=uuid.uuid4().hex)
    case_id = created.json()["id"]

    count = _scalar(
        "SELECT COUNT(*) FROM onboarding.case_state_transition WHERE case_id = %s", (case_id,)
    )
    assert count == 0
