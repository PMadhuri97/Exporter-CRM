"""ANER-4.3-S2T2: `EvidenceAggregationService` against a real database.

Epic-4-only slice: every evidence item recorded here originates from RXIL
(the platform's only real data source today — see
application/evidence_aggregation_service.py's module docstring for why
`source_epic="RXIL"`, not an actual platform epic, is the normal value). Raw
SQL for setup/verification of the case row itself, following
`test_s1t1_case_management_schema.py`'s precedent; the service under test is
exercised through its real async API against a real `AsyncSession`.
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.evidence_aggregation_service import (
    EvidenceAggregationService,
)
from app.modules.cases.domain.entities.enums import EvidenceType
from app.modules.cases.exceptions import CaseNotFoundError
from app.modules.cases.tests.fixtures.case_sql import fetchone, insert_case

# Imported as a module — see test_s1t2_sla_seed_loading.py's identical note.
from app.platform.database import services as database


@pytest.fixture
def service() -> EvidenceAggregationService:
    return EvidenceAggregationService()


# ── add_evidence_item ────────────────────────────────────────────────────────────


async def test_add_evidence_item_creates_a_row(service):
    case = insert_case()
    source_reference_id = uuid.uuid4()

    async with database.AsyncSessionLocal() as session:
        item = await service.add_evidence_item(
            session,
            case_id=uuid.UUID(case["id"]),
            evidence_type=EvidenceType.BUYER_RATING,
            source_epic="RXIL",
            source_reference_id=source_reference_id,
            evidence_data={"rating": "A2", "rated_entity": "Acme Traders Pvt Ltd"},
            added_by="rxil.integration",
        )

    assert item.id is not None
    row = fetchone(
        "SELECT case_id, evidence_type, source_epic, source_reference_id, "
        "evidence_data, added_by, is_key_evidence "
        "FROM cases.case_evidence_item WHERE id = %s",
        (str(item.id),),
    )
    assert row is not None
    assert str(row[0]) == case["id"]
    assert row[1] == "BUYER_RATING"
    assert row[2] == "RXIL"
    assert str(row[3]) == str(source_reference_id)
    assert row[4] == {"rating": "A2", "rated_entity": "Acme Traders Pvt Ltd"}
    assert row[5] == "rxil.integration"
    assert row[6] is False


async def test_add_evidence_item_defaults_is_key_evidence_to_false(service):
    case = insert_case()
    async with database.AsyncSessionLocal() as session:
        item = await service.add_evidence_item(
            session,
            case_id=uuid.UUID(case["id"]),
            evidence_type=EvidenceType.VESSEL_TRACKING,
            source_epic="RXIL",
            source_reference_id=uuid.uuid4(),
            evidence_data={"vessel": "MV Example", "eta": "2026-10-01"},
            added_by="rxil.integration",
        )
    assert item.is_key_evidence is False


async def test_add_evidence_item_respects_is_key_evidence_true(service):
    case = insert_case()
    async with database.AsyncSessionLocal() as session:
        item = await service.add_evidence_item(
            session,
            case_id=uuid.UUID(case["id"]),
            evidence_type=EvidenceType.INSURANCE_CERTIFICATE,
            source_epic="RXIL",
            source_reference_id=uuid.uuid4(),
            evidence_data={"policy_number": "INS-2026-001", "insured": "Jane Doe"},
            added_by="rxil.integration",
            is_key_evidence=True,
        )
    assert item.is_key_evidence is True


async def test_add_evidence_item_raises_for_an_unknown_case(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.add_evidence_item(
                session,
                case_id=uuid.uuid4(),
                evidence_type=EvidenceType.DUPLICATION_CHECK,
                source_epic="RXIL",
                source_reference_id=uuid.uuid4(),
                evidence_data={},
                added_by="rxil.integration",
            )


# ── aggregate_evidence_package ───────────────────────────────────────────────────


async def test_aggregate_evidence_package_rolls_up_multiple_evidence_types(service):
    case = insert_case()
    case_id = uuid.UUID(case["id"])

    async with database.AsyncSessionLocal() as session:
        await service.add_evidence_item(
            session,
            case_id=case_id,
            evidence_type=EvidenceType.DUPLICATION_CHECK,
            source_epic="RXIL",
            source_reference_id=uuid.uuid4(),
            evidence_data={"is_duplicate": False, "invoice_number": "INV-1001"},
            added_by="rxil.integration",
        )

    async with database.AsyncSessionLocal() as session:
        await service.add_evidence_item(
            session,
            case_id=case_id,
            evidence_type=EvidenceType.BILL_OF_LADING,
            source_epic="RXIL",
            source_reference_id=uuid.uuid4(),
            evidence_data={"mletr_verified": True, "bol_number": "BOL-2026-77"},
            added_by="rxil.integration",
        )

    async with database.AsyncSessionLocal() as session:
        package = await service.aggregate_evidence_package(session, case_id)

    assert set(package.keys()) == {"DUPLICATION_CHECK", "BILL_OF_LADING"}
    assert len(package["DUPLICATION_CHECK"]) == 1
    assert len(package["BILL_OF_LADING"]) == 1
    assert package["DUPLICATION_CHECK"][0]["evidence_data"] == {
        "is_duplicate": False,
        "invoice_number": "INV-1001",
    }
    assert package["DUPLICATION_CHECK"][0]["source_epic"] == "RXIL"
    assert package["BILL_OF_LADING"][0]["evidence_data"]["bol_number"] == "BOL-2026-77"


async def test_aggregate_evidence_package_groups_repeated_evidence_type_into_one_list(service):
    """Multiple items of the same evidence_type (e.g. RXIL pushing an updated
    buyer rating) must all survive the rollup, not overwrite one another."""
    case = insert_case()
    case_id = uuid.UUID(case["id"])

    for rating in ("A2", "A1"):
        async with database.AsyncSessionLocal() as session:
            await service.add_evidence_item(
                session,
                case_id=case_id,
                evidence_type=EvidenceType.BUYER_RATING,
                source_epic="RXIL",
                source_reference_id=uuid.uuid4(),
                evidence_data={"rating": rating},
                added_by="rxil.integration",
            )

    async with database.AsyncSessionLocal() as session:
        package = await service.aggregate_evidence_package(session, case_id)

    assert list(package.keys()) == ["BUYER_RATING"]
    assert len(package["BUYER_RATING"]) == 2
    assert {item["evidence_data"]["rating"] for item in package["BUYER_RATING"]} == {"A2", "A1"}


async def test_aggregate_evidence_package_persists_onto_the_case_row(service):
    case = insert_case()
    case_id = uuid.UUID(case["id"])

    async with database.AsyncSessionLocal() as session:
        await service.add_evidence_item(
            session,
            case_id=case_id,
            evidence_type=EvidenceType.VESSEL_TRACKING,
            source_epic="RXIL",
            source_reference_id=uuid.uuid4(),
            evidence_data={"vessel": "MV Example"},
            added_by="rxil.integration",
        )

    async with database.AsyncSessionLocal() as session:
        returned_package = await service.aggregate_evidence_package(session, case_id)

    row = fetchone(
        "SELECT evidence_package FROM cases.compliance_case WHERE id = %s", (case["id"],)
    )
    assert row is not None
    assert row[0] == returned_package
    assert row[0]["VESSEL_TRACKING"][0]["evidence_data"] == {"vessel": "MV Example"}


async def test_aggregate_evidence_package_is_empty_for_a_case_with_no_evidence(service):
    case = insert_case()
    async with database.AsyncSessionLocal() as session:
        package = await service.aggregate_evidence_package(session, uuid.UUID(case["id"]))
    assert package == {}

    row = fetchone(
        "SELECT evidence_package FROM cases.compliance_case WHERE id = %s", (case["id"],)
    )
    assert row[0] == {}


async def test_aggregate_evidence_package_raises_for_an_unknown_case(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.aggregate_evidence_package(session, uuid.uuid4())
