"""ANER-4.3-S1T2 acceptance criteria against a real database.

Covers the seed loader and the case-backed `SlaCalculationService` methods end
to end: the real GitOps YAML to `cases.case_sla_config` to
`is_sla_breached` / `calculate_auto_escalate_at` reading a real
`compliance_case` row. `calculate_sla_deadline` is pure and is covered branch
by branch in tests/unit/test_s1t2_sla_calculation.py against a hand-built
config; what only a database can prove is here.

## Why this suite does not need to restore anything

Unlike `compliance`'s sector-registry seed test
(`test_sector_registry_seed_loading.py`), which installs *fake* fixture data
and must restore the real GitOps directory afterwards, every test here loads
the real `sla-config.yaml` — the production reference data — and only reads
`cases.case_sla_config` afterwards. Reloading production data with itself
leaves nothing to restore.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.cases.application.sla_service import SlaCalculationService
from app.modules.cases.domain.entities.case_sla_config import CaseSlaConfig
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.exceptions import CaseNotFoundError
from app.modules.cases.infrastructure.sla_config_loader import (
    EXPECTED_CASE_TYPES,
    EXPECTED_SEVERITIES,
    build_sla_calculation_service,
    load_sla_config_table,
)
from app.modules.cases.tests.fixtures.case_sql import insert_case

# Imported as a module, not `from ... import AsyncSessionLocal`: the
# session-scoped autouse fixture in backend/conftest.py rebinds that attribute
# to a NullPool sessionmaker, and a name bound at import time would keep the
# pooled original — see test_sector_registry_seed_loading.py's identical note.
from app.platform.database import services as database

EXPECTED_PAIR_COUNT = len(EXPECTED_CASE_TYPES) * len(EXPECTED_SEVERITIES)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_config():
    """Seed `case_sla_config` from the real GitOps YAML once for this module."""
    async with database.AsyncSessionLocal() as session:
        mapping = await load_sla_config_table(session)
    return mapping


@pytest_asyncio.fixture(loop_scope="function")
async def sla_service(seeded_config) -> SlaCalculationService:
    """A calculation service built from the same GitOps file just seeded."""
    return build_sla_calculation_service()


# ── Seed loading (AC: table seeds correctly) ────────────────────────────────────


async def test_seed_data_loads_into_case_sla_config(seeded_config):
    async with database.AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(CaseSlaConfig))
    assert count == EXPECTED_PAIR_COUNT


async def test_reloading_the_same_config_is_idempotent(seeded_config):
    """The loader runs on every boot, so a second load must leave one copy per
    pair rather than duplicating rows."""
    async with database.AsyncSessionLocal() as other:
        await load_sla_config_table(other)

    async with database.AsyncSessionLocal() as session:
        rows = (await session.execute(select(CaseSlaConfig))).scalars().all()

    pairs = [(row.case_type, row.severity) for row in rows]
    assert len(pairs) == len(set(pairs))
    assert len(pairs) == EXPECTED_PAIR_COUNT


async def test_seeded_row_matches_the_walk_phase_target_for_critical_transaction_flag(
    seeded_config,
):
    async with database.AsyncSessionLocal() as session:
        row = await session.scalar(
            select(CaseSlaConfig).where(
                CaseSlaConfig.case_type == "TRANSACTION_FLAG",
                CaseSlaConfig.severity == "CRITICAL",
            )
        )
    assert row is not None
    assert row.sla_hours == 1
    assert row.auto_escalate_at_pct == 75


async def test_every_expected_pair_is_present(seeded_config):
    async with database.AsyncSessionLocal() as session:
        rows = (await session.execute(select(CaseSlaConfig))).scalars().all()
    pairs = {(row.case_type, row.severity) for row in rows}
    expected = {(ct, sev) for ct in EXPECTED_CASE_TYPES for sev in EXPECTED_SEVERITIES}
    assert pairs == expected


# ── is_sla_breached ─────────────────────────────────────────────────────────────


async def test_is_sla_breached_true_for_an_open_case_past_deadline(sla_service):
    """AC: is_sla_breached is true for an open case past deadline."""
    deadline = datetime.now(UTC) - timedelta(minutes=30)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="OPEN",
        sla_deadline=deadline.isoformat(),
        sla_breached=False,
    )
    async with database.AsyncSessionLocal() as session:
        breached = await sla_service.is_sla_breached(session, uuid.UUID(case["id"]))
    assert breached is True


async def test_is_sla_breached_false_for_a_resolved_case_past_deadline(sla_service):
    """AC: is_sla_breached is false for a resolved case past deadline."""
    deadline = datetime.now(UTC) - timedelta(hours=5)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="RESOLVED",
        sla_deadline=deadline.isoformat(),
        sla_breached=False,
        resolution_action="NO_ACTION_REQUIRED",
        resolution_note="Resolved before this test read it.",
        resolved_at=datetime.now(UTC).isoformat(),
        resolved_by="compliance.officer",
    )
    async with database.AsyncSessionLocal() as session:
        breached = await sla_service.is_sla_breached(session, uuid.UUID(case["id"]))
    assert breached is False


async def test_is_sla_breached_false_for_a_closed_without_action_case_past_deadline(sla_service):
    deadline = datetime.now(UTC) - timedelta(hours=5)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="CLOSED_WITHOUT_ACTION",
        sla_deadline=deadline.isoformat(),
        sla_breached=False,
    )
    async with database.AsyncSessionLocal() as session:
        breached = await sla_service.is_sla_breached(session, uuid.UUID(case["id"]))
    assert breached is False


async def test_is_sla_breached_false_for_an_open_case_before_its_deadline(sla_service):
    deadline = datetime.now(UTC) + timedelta(hours=1)
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="OPEN",
        sla_deadline=deadline.isoformat(),
        sla_breached=False,
    )
    async with database.AsyncSessionLocal() as session:
        breached = await sla_service.is_sla_breached(session, uuid.UUID(case["id"]))
    assert breached is False


async def test_is_sla_breached_raises_for_an_unknown_case(sla_service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await sla_service.is_sla_breached(session, uuid.uuid4())


# ── calculate_auto_escalate_at ───────────────────────────────────────────────────


async def test_auto_escalate_at_for_a_critical_case_is_forty_five_minutes_after_creation(
    sla_service,
):
    """AC: auto_escalate_at for a critical case (1-hour SLA) is 45 minutes
    after creation (75% of 60 min)."""
    case = insert_case(
        case_type="TRANSACTION_FLAG",
        severity="CRITICAL",
        case_status="OPEN",
        sla_deadline=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        sla_breached=False,
    )

    async with database.AsyncSessionLocal() as session:
        escalate_at = await sla_service.calculate_auto_escalate_at(
            session, uuid.UUID(case["id"])
        )
        created_at = await session.scalar(
            select(ComplianceCase.created_at).where(
                ComplianceCase.id == uuid.UUID(case["id"])
            )
        )

    assert escalate_at == created_at + timedelta(minutes=45)


async def test_auto_escalate_at_raises_for_an_unknown_case(sla_service):
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await sla_service.calculate_auto_escalate_at(session, uuid.uuid4())
