"""The onboarding ↔ cases bridge, end to end over HTTP.

B6: CRM writes publish events, and a failing bus never fails the write.
B7: entering COMPLIANCE_REVIEW opens exactly one case, linked to the exporter.
Cases router: a decision records its rationale, then drives the lifecycle.
Snapshot: the evidence a proposal rested on does not change when more arrives.
B1: the evidence package is reachable, and says what it lacks.

A fresh InMemoryEventBus is installed for the module. The case bridge
subscribes itself to whichever bus the publisher uses, so nothing else is wired.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg2
import psycopg2.extras
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.messaging.ports import InMemoryEventBus, set_event_bus
from app.platform.messaging.schemas import EventEnvelope, EventType

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
RATIONALE = (
    "Verification and screening evidence reviewed in full; no adverse findings "
    "and the business profile is consistent."
)
TWO_PERSON_FLAGS = (
    "app.modules.cases.application.case_lifecycle_service.REQUIRE_TWO_PERSON_RESOLUTION",
    "app.modules.onboarding.application.case_bridge_service.REQUIRE_TWO_PERSON_RESOLUTION",
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _rows(query: str, params: tuple) -> list[dict]:
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _cases_for(customer_id: str) -> list[dict]:
    return _rows(
        "SELECT * FROM cases.compliance_case WHERE customer_id = %s ORDER BY created_at",
        (customer_id,),
    )


def _lifecycle_rows(customer_id: str) -> list[dict]:
    return _rows(
        "SELECT * FROM onboarding.exporter_lifecycle_history "
        "WHERE customer_id = %s ORDER BY created_at",
        (customer_id,),
    )


def _lifecycle_events(bus: InMemoryEventBus, customer_id: str) -> list[EventEnvelope]:
    return [
        e
        for e in bus.events_of_type(EventType.EXPORTER_LIFECYCLE_CHANGED)
        if e.payload["customer_id"] == customer_id
    ]


async def _create_exporter(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        f"{BASE}/exporters", json={"source": "SALES"}, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["customer_id"]


async def _move(client: AsyncClient, token: str, customer_id: str, to_status: str):
    return await client.post(
        f"{BASE}/exporters/{customer_id}/transition",
        json={"to_status": to_status},
        headers=auth_header(token),
    )


async def _walk_to_compliance_review(client: AsyncClient, token: str, customer_id: str) -> None:
    for to_status in ("CONTACTED", "DATA_COLLECTION", "VERIFICATION_IN_PROGRESS", "COMPLIANCE_REVIEW"):
        resp = await _move(client, token, customer_id, to_status)
        assert resp.status_code == 200, (to_status, resp.text)


async def _screening_decision(
    client: AsyncClient, token: str, customer_id: str, item_key: str
) -> None:
    resp = await client.put(
        f"{BASE}/exporters/{customer_id}/screening-review/{item_key}",
        json={"status": "PASSED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text


async def _decide(client: AsyncClient, token: str, case_id: str, outcome: str = "APPROVE"):
    return await client.post(
        f"{BASE}/compliance-cases/{case_id}/decision",
        json={"outcome": outcome, "rationale": RATIONALE},
        headers=auth_header(token),
    )


async def _detail(client: AsyncClient, token: str, case_id: str) -> dict:
    resp = await client.get(f"{BASE}/compliance-cases/{case_id}", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def bus() -> Iterator[InMemoryEventBus]:
    bus = InMemoryEventBus()
    set_event_bus(bus)
    yield bus
    set_event_bus(None)


@pytest.fixture(scope="module")
async def compliance(client: AsyncClient) -> tuple[str, str]:
    return await user_with_role(client, UserRole.COMPLIANCE)


@pytest.fixture(scope="module")
async def ops_token(client: AsyncClient) -> str:
    _, token = await user_with_role(client, UserRole.OPERATIONS)
    return token


class _ExplodingBus(InMemoryEventBus):
    async def publish(self, envelope: EventEnvelope) -> None:
        raise ConnectionError("broker unreachable")


# ── B6: publishing ──────────────────────────────────────────────────────────


async def test_a_lifecycle_transition_publishes_an_event(
    client: AsyncClient, bus: InMemoryEventBus, ops_token: str
):
    customer_id = await _create_exporter(client, ops_token)
    resp = await _move(client, ops_token, customer_id, "CONTACTED")
    assert resp.status_code == 200, resp.text

    created, moved = _lifecycle_events(bus, customer_id)
    assert (created.payload["from_status"], created.payload["to_status"]) == (None, "LEAD")
    assert (moved.payload["from_status"], moved.payload["to_status"]) == ("LEAD", "CONTACTED")
    # Notification alongside, not instead of, the durable record.
    assert [r["to_status"] for r in _lifecycle_rows(customer_id)] == ["LEAD", "CONTACTED"]


async def test_a_lifecycle_transition_does_not_fail_when_the_bus_does(
    client: AsyncClient, bus: InMemoryEventBus, ops_token: str
):
    customer_id = await _create_exporter(client, ops_token)
    set_event_bus(_ExplodingBus())
    try:
        resp = await _move(client, ops_token, customer_id, "CONTACTED")
    finally:
        set_event_bus(bus)

    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "CONTACTED"
    assert _lifecycle_rows(customer_id)[-1]["to_status"] == "CONTACTED"


async def test_screening_and_verification_reviews_publish(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str]
):
    _, token = compliance
    customer_id = await _create_exporter(client, token)
    await _screening_decision(client, token, customer_id, "website-reviewed")

    triggered = await client.post(
        f"{BASE}/verifications",
        json={
            "verification_type": "KYB",
            "entity_type": "EXPORTER",
            "entity_reference": customer_id,
            "provider": "manual",
            "payload": {"status": "PASSED"},
        },
        headers=auth_header(token),
    )
    assert triggered.status_code == 201, triggered.text
    result_id = triggered.json()["id"]
    reviewed = await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"review_status": "ACCEPTED"},
        headers=auth_header(token),
    )
    assert reviewed.status_code == 200, reviewed.text

    [screening] = [
        e
        for e in bus.events_of_type(EventType.EXPORTER_SCREENING_REVIEW_UPDATED)
        if e.payload["customer_id"] == customer_id
    ]
    assert screening.payload["item_key"] == "website-reviewed"
    [verification] = [
        e
        for e in bus.events_of_type(EventType.EXPORTER_VERIFICATION_REVIEWED)
        if e.payload["verification_result_id"] == result_id
    ]
    assert verification.payload["review_status"] == "ACCEPTED"


# ── B7: case creation ───────────────────────────────────────────────────────


async def test_entering_compliance_review_creates_exactly_one_linked_case(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    _, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)

    [case] = _cases_for(customer_id)
    assert case["case_type"] == "ONBOARDING_REVIEW"
    assert case["case_status"] == "OPEN"
    assert str(case["customer_id"]) == customer_id
    assert case["sla_deadline"] is not None
    entry = _lifecycle_events(bus, customer_id)[-1]
    assert entry.payload["to_status"] == "COMPLIANCE_REVIEW"
    assert str(case["originating_event_id"]) == entry.event_id

    # Redelivery of the same event (at-least-once) does not open a second case.
    await bus.publish(entry)
    assert len(_cases_for(customer_id)) == 1

    # Sent back and resubmitted while the case is still open: it joins that case.
    assert (await _move(client, token, customer_id, "DATA_COLLECTION")).status_code == 200
    for to_status in ("VERIFICATION_IN_PROGRESS", "COMPLIANCE_REVIEW"):
        assert (await _move(client, ops_token, customer_id, to_status)).status_code == 200
    assert len(_cases_for(customer_id)) == 1


async def test_a_case_starts_with_the_evidence_already_on_file(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    _, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _screening_decision(client, token, customer_id, "website-reviewed")
    await _screening_decision(client, token, customer_id, "address-physical")
    await _walk_to_compliance_review(client, ops_token, customer_id)

    [case] = _cases_for(customer_id)
    detail = await _detail(client, token, str(case["id"]))
    assert len(detail["evidence_items"]) == 2
    assert detail["evidence_snapshot"] is None
    assert [e["event_type"] for e in detail["timeline"]] == ["CASE_CREATED"]


async def test_direct_onboarding_is_refused_while_a_case_is_open(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    _, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)

    resp = await _move(client, token, customer_id, "ONBOARDED")

    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "ONBOARDING_DECIDED_BY_CASE"
    assert _lifecycle_rows(customer_id)[-1]["to_status"] == "COMPLIANCE_REVIEW"


# ── Cases router: decision ──────────────────────────────────────────────────


async def test_a_decision_records_its_rationale_then_drives_the_lifecycle(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    user_id, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)
    [case] = _cases_for(customer_id)

    resp = await _decide(client, token, str(case["id"]))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["awaiting_second_reviewer"] is False
    assert body["exporter_lifecycle_status"] == "ONBOARDED"
    assert body["case"]["case_status"] == "RESOLVED"
    assert body["case"]["resolution_action"] == "APPROVE_ONBOARDING"
    assert body["case"]["resolution_note"] == RATIONALE
    assert body["case"]["resolved_by"] == user_id

    # Order: the case resolution is committed before the lifecycle row exists.
    [resolved] = _cases_for(customer_id)
    onboarded = _lifecycle_rows(customer_id)[-1]
    assert onboarded["to_status"] == "ONBOARDED"
    assert onboarded["from_status"] == "COMPLIANCE_REVIEW"
    assert onboarded["actor_id"] == user_id
    assert resolved["resolved_at"] <= onboarded["created_at"]
    timeline = [e["event_type"] for e in (await _detail(client, token, str(case["id"])))["timeline"]]
    assert timeline[-3:] == ["APPROVAL_REQUESTED", "APPROVAL_RECEIVED", "RESOLVED"]
    assert _lifecycle_events(bus, customer_id)[-1].payload["to_status"] == "ONBOARDED"

    # Resolved is final.
    again = await _decide(client, token, str(case["id"]))
    assert again.status_code == 409, again.text


async def test_a_rejection_sends_the_exporter_back_for_data(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    _, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)
    [case] = _cases_for(customer_id)

    resp = await _decide(client, token, str(case["id"]), outcome="REJECT")

    assert resp.status_code == 200, resp.text
    assert resp.json()["case"]["resolution_action"] == "REJECT_ONBOARDING"
    assert resp.json()["exporter_lifecycle_status"] == "DATA_COLLECTION"


async def test_a_decision_without_a_real_rationale_writes_nothing(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    _, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)
    [case] = _cases_for(customer_id)

    resp = await client.post(
        f"{BASE}/compliance-cases/{case['id']}/decision",
        json={"outcome": "APPROVE", "rationale": "looks fine"},
        headers=auth_header(token),
    )

    assert resp.status_code == 422, resp.text
    assert _cases_for(customer_id)[0]["case_status"] == "OPEN"
    assert _lifecycle_rows(customer_id)[-1]["to_status"] == "COMPLIANCE_REVIEW"


async def test_a_note_is_added_to_the_timeline(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    user_id, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)
    [case] = _cases_for(customer_id)

    resp = await client.post(
        f"{BASE}/compliance-cases/{case['id']}/notes",
        json={"note": "Called the exporter to confirm the registered address."},
        headers=auth_header(token),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["event_type"] == "NOTE_ADDED"
    assert resp.json()["actor_id"] == user_id


async def test_the_queue_filters_by_status_and_type(
    client: AsyncClient, bus: InMemoryEventBus, compliance: tuple[str, str], ops_token: str
):
    _, token = compliance
    customer_id = await _create_exporter(client, ops_token)
    await _walk_to_compliance_review(client, ops_token, customer_id)
    [case] = _cases_for(customer_id)

    resp = await client.get(
        f"{BASE}/compliance-cases",
        params={"status": "OPEN", "case_type": "ONBOARDING_REVIEW", "limit": 200},
        headers=auth_header(token),
    )

    assert resp.status_code == 200, resp.text
    listed = resp.json()["cases"]
    assert str(case["id"]) in {c["id"] for c in listed}
    assert {(c["case_status"], c["case_type"]) for c in listed} == {("OPEN", "ONBOARDING_REVIEW")}


# ── Snapshot at proposal time ───────────────────────────────────────────────


async def test_the_evidence_snapshot_does_not_change_when_a_later_item_arrives(
    client: AsyncClient,
    bus: InMemoryEventBus,
    compliance: tuple[str, str],
    ops_token: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Two-person mode, so the case sits between proposal and decision while
    new evidence arrives."""
    for flag in TWO_PERSON_FLAGS:
        monkeypatch.setattr(flag, True)
    maker_id, maker = compliance
    _, checker = await user_with_role(client, UserRole.ADMIN)
    customer_id = await _create_exporter(client, ops_token)
    await _screening_decision(client, maker, customer_id, "website-reviewed")
    await _walk_to_compliance_review(client, ops_token, customer_id)
    case_id = str(_cases_for(customer_id)[0]["id"])

    proposed = await _decide(client, maker, case_id)
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["awaiting_second_reviewer"] is True
    assert proposed.json()["case"]["case_status"] == "PENDING_APPROVAL"
    assert proposed.json()["exporter_lifecycle_status"] == "COMPLIANCE_REVIEW"

    before = await _detail(client, maker, case_id)
    snapshot = before["evidence_snapshot"]
    assert snapshot is not None
    assert snapshot["taken_by"] == maker_id
    [original] = before["evidence_items"]
    assert original["in_snapshot"] is True

    # New material after the proposal.
    await _screening_decision(client, maker, customer_id, "address-physical")

    after = await _detail(client, maker, case_id)
    assert after["evidence_snapshot"] == snapshot
    by_id = {item["id"]: item for item in after["evidence_items"]}
    assert len(by_id) == 2
    assert by_id[original["id"]]["in_snapshot"] is True
    assert by_id[original["id"]]["added_after_snapshot"] is False
    [later] = [item for item in by_id.values() if item["id"] != original["id"]]
    assert later["in_snapshot"] is False
    assert later["added_after_snapshot"] is True

    # The proposer cannot also decide; a second reviewer completes it.
    assert (await _decide(client, maker, case_id)).json()["awaiting_second_reviewer"] is True
    decided = await _decide(client, checker, case_id)
    assert decided.status_code == 200, decided.text
    assert decided.json()["exporter_lifecycle_status"] == "ONBOARDED"
    assert (await _detail(client, maker, case_id))["evidence_snapshot"] == snapshot


# ── B1: evidence package ────────────────────────────────────────────────────


async def test_the_evidence_package_is_served_and_flags_missing_screening(
    client: AsyncClient, compliance: tuple[str, str]
):
    _, token = compliance
    created = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "legal_name": "Meera Textiles Pvt Ltd",
            "incorporation_country": "IN",
            "initial_user_email": f"owner-{uuid.uuid4().hex[:8]}@example.com",
        },
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["customer_id"]
    profile = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    onboarding_id = profile.json()["onboarding_history"][0]["onboarding_id"]

    resp = await client.get(
        f"{BASE}/audit/onboarding-requests/{onboarding_id}/evidence-package",
        headers=auth_header(token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["detail"]["legal_name"] == "Meera Textiles Pvt Ltd"
    assert body["detail"]["sensitive_fields_redacted"] is False
    assert body["screening_evidence"] is None
    assert body["screening_evidence_status"] == "UNAVAILABLE"
    assert "Epic 3.2" in body["screening_evidence_reason"]


async def test_the_evidence_package_is_404_for_an_unknown_request(
    client: AsyncClient, compliance: tuple[str, str]
):
    _, token = compliance
    resp = await client.get(
        f"{BASE}/audit/onboarding-requests/{uuid.uuid4()}/evidence-package",
        headers=auth_header(token),
    )
    assert resp.status_code == 404, resp.text
