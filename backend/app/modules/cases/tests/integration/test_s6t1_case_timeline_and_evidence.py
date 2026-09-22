"""ANER-4.3-S6T1: `CaseQueryService.get_case_timeline` and
`.get_case_evidence_items` as standalone operations (distinct from
`get_case_detail`, which composes both — see test_s6t1_case_detail.py).

AC (doc, S6T1): "Get case timeline returns all events in chronological order
for a test case with five events."
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cases.application.case_query_service import CaseQueryService
from app.modules.cases.domain.entities.enums import ActorType
from app.modules.cases.exceptions import CaseNotFoundError
from app.modules.cases.tests.fixtures.case_sql import (
    insert_case,
    insert_evidence_item,
    insert_timeline_event,
)
from app.platform.database import services as database


@pytest.fixture
def service() -> CaseQueryService:
    return CaseQueryService()


# ── get_case_timeline ────────────────────────────────────────────────────────


async def test_get_case_timeline_returns_five_events_in_chronological_order(service):
    """AC: exactly the doc's own acceptance criterion — five events, in order."""
    case = insert_case()
    event_types = ["CASE_CREATED", "ASSIGNED", "STATUS_CHANGED", "NOTE_ADDED", "RESOLVED"]
    base = datetime(2026, 9, 1, tzinfo=UTC)
    # Inserted out of order on purpose — the response must still come back
    # sorted by occurred_at, not by insertion order.
    for i in [4, 0, 2, 1, 3]:
        insert_timeline_event(
            case["id"], event_type=event_types[i], occurred_at=base + timedelta(minutes=i)
        )

    async with database.AsyncSessionLocal() as session:
        timeline = await service.get_case_timeline(session, uuid.UUID(case["id"]))

    assert [e.event_type.value for e in timeline] == event_types
    assert all(
        timeline[i].occurred_at <= timeline[i + 1].occurred_at for i in range(len(timeline) - 1)
    )


async def test_get_case_timeline_empty_for_a_case_with_no_events(service):
    case = insert_case()
    async with database.AsyncSessionLocal() as session:
        timeline = await service.get_case_timeline(session, uuid.UUID(case["id"]))
    assert timeline == []


async def test_get_case_timeline_unknown_case_raises(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.get_case_timeline(session, uuid.uuid4())


# ── get_case_evidence_items ──────────────────────────────────────────────────


async def test_get_case_evidence_items_returns_all_items_oldest_first(service):
    case = insert_case()
    insert_evidence_item(case["id"], evidence_type="BUYER_RATING")
    insert_evidence_item(case["id"], evidence_type="INSURANCE_CERTIFICATE")
    insert_evidence_item(case["id"], evidence_type="BILL_OF_LADING")

    async with database.AsyncSessionLocal() as session:
        items = await service.get_case_evidence_items(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.COMPLIANCE_OFFICER
        )

    assert len(items) == 3
    assert all(
        items[i].added_at <= items[i + 1].added_at for i in range(len(items) - 1)
    )


async def test_get_case_evidence_items_unknown_case_raises(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.get_case_evidence_items(
                session, uuid.uuid4(), caller_actor_type=ActorType.COMPLIANCE_OFFICER
            )


async def test_get_case_evidence_items_metadata_only_for_non_compliance_caller(service):
    """AC: "Returns only metadata (evidence_type, source_epic, added_at,
    is_key_evidence) for other callers." — evidence_data withheld, everything
    else present, for a PII-bearing evidence type."""
    case = insert_case()
    insert_evidence_item(
        case["id"],
        evidence_type="KYB_RESULT",
        source_epic="Epic 2.1",
        evidence_data='{"registry_number": "12345"}',
        is_key_evidence=True,
    )

    async with database.AsyncSessionLocal() as session:
        items = await service.get_case_evidence_items(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.SYSTEM
        )

    assert len(items) == 1
    view = items[0]
    assert view.evidence_data is None
    assert view.evidence_type == "KYB_RESULT"
    assert view.source_epic == "Epic 2.1"
    assert view.is_key_evidence is True
    assert view.added_at is not None
