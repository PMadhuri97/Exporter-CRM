"""ANER-4.3-S6T1: `CaseQueryService.get_case_detail` — the case, its evidence
items, and its timeline events assembled together, with PII redaction applied
per caller.

AC (doc, S6T1): "Get case by ID returns the complete case including
evidence_package. PII evidence data is withheld for non-compliance callers."
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.case_query_service import CaseQueryService
from app.modules.cases.application.evidence_aggregation_service import EvidenceAggregationService
from app.modules.cases.domain.entities.enums import ActorType, EvidenceType
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


async def test_get_case_detail_assembles_case_evidence_and_timeline(service):
    """A case with evidence items and timeline events comes back with all
    three assembled — not just the bare `compliance_case` row."""
    case = insert_case()
    insert_evidence_item(case["id"], evidence_type="DUPLICATION_CHECK", is_key_evidence=True)
    insert_evidence_item(case["id"], evidence_type="VESSEL_TRACKING")

    async with database.AsyncSessionLocal() as session:
        detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.COMPLIANCE_OFFICER
        )

    assert detail.case.id == uuid.UUID(case["id"])
    assert detail.case.case_reference == case["case_reference"]
    assert {item.evidence_type for item in detail.evidence_items} == {
        "DUPLICATION_CHECK",
        "VESSEL_TRACKING",
    }
    # CASE_CREATED comes from the fixture's own insert_case, not a separate
    # timeline write, so a bare case has zero timeline rows unless one is
    # inserted directly — this proves the (currently empty) list assembles
    # without error, and the evidence-bearing case below proves non-empty.
    assert detail.timeline_events == []


async def test_get_case_detail_evidence_items_are_not_n_plus_one(service):
    """Ten evidence items and ten timeline events on one case still assemble
    through the same single `get_case_detail` call — proving the eager-loaded
    relationships return every row, not just the first page a naive join
    might produce."""
    case = insert_case()
    for _ in range(10):
        insert_evidence_item(case["id"], evidence_type="DUPLICATION_CHECK")
    for _ in range(10):
        insert_timeline_event(case["id"], event_type="NOTE_ADDED", to_status="OPEN")

    async with database.AsyncSessionLocal() as session:
        detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.COMPLIANCE_OFFICER
        )

    assert len(detail.evidence_items) == 10
    assert len(detail.timeline_events) == 10


async def test_get_case_detail_unknown_case_raises(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.get_case_detail(
                session, uuid.uuid4(), caller_actor_type=ActorType.COMPLIANCE_OFFICER
            )


# ── PII redaction ────────────────────────────────────────────────────────────


async def test_compliance_officer_sees_pii_evidence_data(service):
    """AC: PII evidence data is returned in full for a compliance-officer caller."""
    case = insert_case()
    insert_evidence_item(
        case["id"],
        evidence_type="SCREENING_RESULT",  # PII-bearing per enums.PII_BEARING_EVIDENCE_TYPES
        evidence_data='{"match_name": "Jane Doe"}',
    )

    async with database.AsyncSessionLocal() as session:
        detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.COMPLIANCE_OFFICER
        )

    assert detail.evidence_items[0].evidence_data == {"match_name": "Jane Doe"}


async def test_non_compliance_caller_has_pii_evidence_data_withheld(service):
    """AC: PII evidence data is withheld for non-compliance callers."""
    case = insert_case()
    insert_evidence_item(
        case["id"],
        evidence_type="SCREENING_RESULT",
        evidence_data='{"match_name": "Jane Doe"}',
    )

    async with database.AsyncSessionLocal() as session:
        detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.OPERATIONS_OFFICER
        )

    assert detail.evidence_items[0].evidence_data is None
    # Metadata is still visible even though the payload is withheld.
    assert detail.evidence_items[0].evidence_type == "SCREENING_RESULT"
    assert detail.evidence_items[0].is_key_evidence is False


async def test_non_pii_evidence_data_is_never_withheld(service):
    """DUPLICATION_CHECK is not in PII_BEARING_EVIDENCE_TYPES — a
    non-compliance caller still sees its evidence_data in full."""
    case = insert_case()
    insert_evidence_item(
        case["id"],
        evidence_type="DUPLICATION_CHECK",
        evidence_data='{"duplicate_found": false}',
    )

    async with database.AsyncSessionLocal() as session:
        detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.OPERATIONS_OFFICER
        )

    assert detail.evidence_items[0].evidence_data == {"duplicate_found": False}


async def test_evidence_package_pii_fields_are_redacted_for_non_compliance_caller(service):
    """`evidence_package` (the rolled-up JSON on `compliance_case`) applies
    the same per-type redaction as individual evidence items."""
    case = insert_case()

    async with database.AsyncSessionLocal() as session:
        aggregation = EvidenceAggregationService()
        await aggregation.add_evidence_item(
            session,
            uuid.UUID(case["id"]),
            evidence_type=EvidenceType.SCREENING_RESULT,
            source_epic="Epic 3.2",
            source_reference_id=uuid.uuid4(),
            evidence_data={"match_name": "Jane Doe"},
            added_by="compliance.officer",
        )
        await aggregation.add_evidence_item(
            session,
            uuid.UUID(case["id"]),
            evidence_type=EvidenceType.VESSEL_TRACKING,
            source_epic="RXIL",
            source_reference_id=uuid.uuid4(),
            evidence_data={"vessel": "MV Test"},
            added_by="compliance.officer",
        )
        await aggregation.aggregate_evidence_package(session, uuid.UUID(case["id"]))

    async with database.AsyncSessionLocal() as session:
        detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.OPERATIONS_OFFICER
        )

    assert "evidence_data" not in detail.evidence_package["SCREENING_RESULT"][0]
    assert detail.evidence_package["VESSEL_TRACKING"][0]["evidence_data"] == {"vessel": "MV Test"}

    async with database.AsyncSessionLocal() as session:
        officer_detail = await service.get_case_detail(
            session, uuid.UUID(case["id"]), caller_actor_type=ActorType.COMPLIANCE_OFFICER
        )
    assert officer_detail.evidence_package["SCREENING_RESULT"][0]["evidence_data"] == {
        "match_name": "Jane Doe"
    }
