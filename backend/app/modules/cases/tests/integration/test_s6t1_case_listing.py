"""ANER-4.3-S6T1 (schema-bounded slice of S5T1's filters — see
`case_query_service.py`'s module docstring): `CaseQueryService.list_cases`
filtering by status/type/severity/assignee, and its pagination bounds.
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.case_query_service import CaseQueryService
from app.modules.cases.domain.entities.enums import CaseSeverity, CaseStatus, CaseType
from app.modules.cases.tests.fixtures.case_sql import insert_case
from app.platform.database import services as database
from app.shared.exceptions import ValidationError


@pytest.fixture
def service() -> CaseQueryService:
    return CaseQueryService()


async def test_list_cases_filters_by_status(service):
    marker = f"status-{uuid.uuid4().hex[:8]}"
    open_case = insert_case(case_status="OPEN", title=marker)
    insert_case(case_status="RESOLVED", title=marker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(session, status=CaseStatus.OPEN, limit=200)

    ids = {str(c.id) for c in results}
    assert open_case["id"] in ids
    assert all(c.case_status == CaseStatus.OPEN for c in results)


async def test_list_cases_filters_by_multiple_statuses(service):
    marker = f"multi-{uuid.uuid4().hex[:8]}"
    open_case = insert_case(case_status="OPEN", title=marker)
    assigned_case = insert_case(case_status="ASSIGNED", title=marker)
    insert_case(case_status="RESOLVED", title=marker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(
            session, status=[CaseStatus.OPEN, CaseStatus.ASSIGNED], limit=200
        )

    ids = {str(c.id) for c in results}
    assert open_case["id"] in ids
    assert assigned_case["id"] in ids
    assert all(c.case_status in (CaseStatus.OPEN, CaseStatus.ASSIGNED) for c in results)


async def test_list_cases_filters_by_case_type(service):
    marker = f"type-{uuid.uuid4().hex[:8]}"
    matching = insert_case(case_type="RECONCILIATION_BREAK", title=marker)
    insert_case(case_type="TRANSACTION_FLAG", title=marker)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(
            session, case_type=CaseType.RECONCILIATION_BREAK, limit=200
        )

    ids = {str(c.id) for c in results}
    assert matching["id"] in ids
    assert all(c.case_type == CaseType.RECONCILIATION_BREAK for c in results)


async def test_list_cases_filters_by_severity(service):
    matching = insert_case(severity="CRITICAL")
    insert_case(severity="LOW")

    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(session, severity=CaseSeverity.CRITICAL, limit=200)

    ids = {str(c.id) for c in results}
    assert matching["id"] in ids
    assert all(c.severity == CaseSeverity.CRITICAL for c in results)


async def test_list_cases_filters_by_assignee(service):
    assignee = f"officer-{uuid.uuid4().hex[:8]}"
    matching = insert_case(assigned_to=assignee)
    insert_case(assigned_to=f"someone-else-{uuid.uuid4().hex[:8]}")

    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(session, assigned_to=assignee, limit=200)

    assert len(results) == 1
    assert results[0].id == uuid.UUID(matching["id"])


async def test_list_cases_combines_filters(service):
    assignee = f"combo-{uuid.uuid4().hex[:8]}"
    matching = insert_case(
        case_status="UNDER_INVESTIGATION",
        severity="HIGH",
        assigned_to=assignee,
    )
    insert_case(case_status="UNDER_INVESTIGATION", severity="LOW", assigned_to=assignee)

    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(
            session,
            status=CaseStatus.UNDER_INVESTIGATION,
            severity=CaseSeverity.HIGH,
            assigned_to=assignee,
            limit=200,
        )

    assert len(results) == 1
    assert results[0].id == uuid.UUID(matching["id"])


async def test_list_cases_respects_limit_and_offset(service):
    marker = f"page-{uuid.uuid4().hex[:8]}"
    for _ in range(5):
        insert_case(title=marker, assigned_to=marker)

    async with database.AsyncSessionLocal() as session:
        page_1 = await service.list_cases(session, assigned_to=marker, limit=2, offset=0)
        page_2 = await service.list_cases(session, assigned_to=marker, limit=2, offset=2)

    assert len(page_1) == 2
    assert len(page_2) == 2
    assert {c.id for c in page_1}.isdisjoint({c.id for c in page_2})


async def test_list_cases_with_no_filters_and_default_limit_does_not_raise(service):
    async with database.AsyncSessionLocal() as session:
        results = await service.list_cases(session)
    assert len(results) <= 50


@pytest.mark.parametrize("limit", [0, -1, 500])
async def test_list_cases_rejects_out_of_range_limit(service, limit):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.list_cases(session, limit=limit)


async def test_list_cases_rejects_negative_offset(service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.list_cases(session, offset=-1)
