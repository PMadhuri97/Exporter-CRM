"""The legacy owner backfill: free text to exactly one active RM, or nothing.

Exact matching apart from case and repeated spaces; an ambiguous name, a name that
belongs only to a non-RM or a deactivated account, and an unknown name are reported and
left alone; a run writes history with its run id; a second run does nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from app.modules.onboarding.backfill_relationship_managers import apply, resolve, validate
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.auth import deactivate
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import create_user_direct
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


def _user(role: UserRole, name: str) -> str:
    return create_user_direct(f"bf-{uuid.uuid4().hex[:10]}@aner-test.com", role, full_name=name)


async def _company_owned_by(text: str) -> uuid.UUID:
    company_id = await make_company(relationship_manager=False)
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .values(relationship_manager=text)
        )
        await db.commit()
    return company_id


async def _rm(company_id: uuid.UUID):
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.relationship_manager_user_id).where(
                ExporterProfile.customer_id == company_id
            )
        )


async def test_the_backfill_matches_only_one_active_rm_and_is_idempotent():
    tag = uuid.uuid4().hex[:6]
    unique = _user(UserRole.OPERATIONS, f"Asha Rao {tag}")
    _user(UserRole.OPERATIONS, f"Twin Name {tag}")
    _user(UserRole.OPERATIONS, f"Twin  name {tag}")
    _user(UserRole.COMPLIANCE, f"Compliance Person {tag}")
    leaver = _user(UserRole.OPERATIONS, f"Left Already {tag}")
    deactivate(leaver)

    matched = await _company_owned_by(f"  asha   RAO {tag} ")
    ambiguous = await _company_owned_by(f"Twin Name {tag}")
    not_rm = await _company_owned_by(f"Compliance Person {tag}")
    inactive = await _company_owned_by(f"Left Already {tag}")
    unknown = await _company_owned_by(f"Nobody {tag}")
    fuzzy = await _company_owned_by(f"Asha R {tag}")

    async with db_services.AsyncSessionLocal() as db:
        report = await resolve(db)
    assert (matched, f"  asha   RAO {tag} ", uuid.UUID(unique)) in report.matched
    assert ambiguous in {c for c, _t, _n in report.ambiguous}
    assert {not_rm, inactive} <= {c for c, _t, _w in report.not_an_rm}
    assert {unknown, fuzzy} <= {c for c, _t in report.no_match}
    assert "Dry run" not in report.render()

    run_id = f"test-{tag}"
    async with db_services.AsyncSessionLocal() as db:
        counts = await apply(db, report, run_id=run_id, actor_id="backfill:test")
    assert counts["set"] >= 1
    assert str(await _rm(matched)) == unique
    for company in (ambiguous, not_rm, inactive, unknown, fuzzy):
        assert await _rm(company) is None

    async with db_services.AsyncSessionLocal() as db:
        [row] = (
            await db.scalars(
                select(ExporterLifecycleHistory).where(
                    ExporterLifecycleHistory.customer_id == matched,
                    ExporterLifecycleHistory.dimension == "relationship_manager",
                )
            )
        ).all()
    assert row.event_metadata["bulk_run_id"] == run_id
    assert row.event_metadata["source"] == "backfill_relationship_managers"
    assert row.actor_id == "backfill:test"

    async with db_services.AsyncSessionLocal() as db:
        again = await resolve(db)
    assert matched not in {c for c, _t, _u in again.matched}

    # The checks run (the shared test database holds other tests' deliberate oddities,
    # so their counts are not asserted here).
    async with db_services.AsyncSessionLocal() as db:
        checks = dict(await validate(db))
    assert set(checks) == {
        "companies whose RM is not a user",
        "companies whose RM is not an RM (OPERATIONS) account",
    }
