"""What one compliance officer has had a hand in — the *Reviewed* tab's listing.

Both sides of maker-checker, because an officer's own record is not only what they
approved: a proposal they made is their work whatever became of it, and one they
approved or rejected is their work although somebody else wrote it.

Their own work only. There is no parameter for reading another officer's, and these
tests hold that line — the filter is the point of the listing, not a default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.infrastructure.repositories.background_check_proposal_repository import (
    BackgroundCheckProposalRepository,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import ComplianceUser, propose_as
from app.modules.onboarding.tests.integration._compliance_support import (
    CHECKER,
    MAKER,
    ready_to_clear,
)
from app.modules.onboarding.tests.integration._verification_support import pg
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

#: Refuses UPDATE and DELETE on the proposal table (migration 0026).
APPEND_ONLY = "trg_background_check_proposal_append_only"

#: A compliance officer who takes no part in the proposals below.
THIRD = ComplianceUser(user_id="reviewed-third-officer", role=UserRole.COMPLIANCE)


async def _reject(who: ComplianceUser, company_id: uuid.UUID, proposal_id: uuid.UUID) -> None:
    from app.modules.onboarding.application.background_check_service import (
        BackgroundCheckService,
    )

    async with db_services.AsyncSessionLocal() as db:
        await BackgroundCheckService(db).reject(
            company_id,
            proposal_id,
            reason="Not yet",
            actor_id=who.user_id,
            actor_role=who.role,
        )


async def _reviewed(who: str, *, limit: int = 50, **kwargs) -> tuple[list, int]:
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckProposalRepository(db).list_across_companies(
            status=None, reviewed_by=who, limit=limit, **kwargs
        )


async def _company_with_open_proposal(proposer) -> tuple[uuid.UUID, uuid.UUID]:
    company_id = await make_company()
    await ready_to_clear(company_id)
    proposal = await propose_as(
        proposer,
        company_id,
        to_value=BackgroundCheckState.CLEAR,
        reason="Checks are in order",
        risk=BackgroundCheckRisk.LOW,
    )
    return company_id, proposal.id


async def test_a_proposal_i_made_is_mine_even_while_it_waits():
    """Left out, the one proposal an officer is waiting on would be the one missing
    from their own record."""
    _company_id, proposal_id = await _company_with_open_proposal(MAKER)

    rows, total = await _reviewed(MAKER.user_id)

    assert proposal_id in [row[0].id for row in rows]
    assert total >= 1
    # Still open: no resolution beside it.
    mine = next(row for row in rows if row[0].id == proposal_id)
    assert mine[1] is None


async def test_a_proposal_i_rejected_is_mine_though_somebody_else_wrote_it():
    company_id, proposal_id = await _company_with_open_proposal(MAKER)
    await _reject(CHECKER, company_id, proposal_id)

    rows, _total = await _reviewed(CHECKER.user_id)

    listed = next((row for row in rows if row[0].id == proposal_id), None)
    assert listed is not None, "the checker's own rejection is their work"
    assert listed[0].created_by == MAKER.user_id
    assert listed[1] is not None and listed[1].outcome == "REJECTED"


async def test_the_proposer_still_sees_a_proposal_that_was_rejected():
    """The half of this the proposer most needs: what became of what they sent."""
    company_id, proposal_id = await _company_with_open_proposal(MAKER)
    await _reject(CHECKER, company_id, proposal_id)

    rows, _total = await _reviewed(MAKER.user_id)

    listed = next((row for row in rows if row[0].id == proposal_id), None)
    assert listed is not None
    assert listed[1].outcome == "REJECTED"


async def test_somebody_else_s_work_is_not_mine():
    """A proposal a third officer neither made nor resolved is absent from theirs."""
    company_id, proposal_id = await _company_with_open_proposal(MAKER)
    await _reject(CHECKER, company_id, proposal_id)

    rows, _total = await _reviewed(THIRD.user_id)

    assert proposal_id not in [row[0].id for row in rows]


async def test_the_window_bounds_how_far_back_it_reaches():
    """Unbounded it is a slow query and an unreadable list."""
    _company_id, proposal_id = await _company_with_open_proposal(MAKER)

    recent, _ = await _reviewed(MAKER.user_id, since=datetime.now(UTC) - timedelta(days=1))
    ancient, _ = await _reviewed(MAKER.user_id, since=datetime.now(UTC) + timedelta(days=1))

    assert proposal_id in [row[0].id for row in recent]
    assert proposal_id not in [row[0].id for row in ancient]


async def test_work_done_recently_on_an_old_proposal_is_still_mine():
    """The window asks "what have I done lately", so it has to follow the decision as
    well as the proposal.

    On the proposal's date alone, an officer who approved something yesterday did not
    see it in their own 90-day record, because the proposal had been sitting since
    before the window opened. The row is backdated here past the window and then
    resolved, which is exactly that shape.
    """
    company_id, proposal_id = await _company_with_open_proposal(MAKER)
    # The table is append-only, so the age is staged with the trigger off for this one
    # transaction — the convention `test_buyer_checks` uses for the frozen buyer row.
    with pg() as cur:
        cur.execute("BEGIN")
        cur.execute(f"ALTER TABLE onboarding.background_check_proposal DISABLE TRIGGER {APPEND_ONLY}")
        cur.execute(
            "UPDATE onboarding.background_check_proposal "
            "SET created_at = now() - interval '100 days' WHERE id = %s",
            (str(proposal_id),),
        )
        cur.execute(f"ALTER TABLE onboarding.background_check_proposal ENABLE TRIGGER {APPEND_ONLY}")
        cur.execute("COMMIT")

    # Scoped to this one proposal. The listing is newest-first and this row is now
    # the oldest of hundreds this database has accumulated, so any page would miss it
    # for a reason that has nothing to do with the window being tested.
    window = datetime.now(UTC) - timedelta(days=90)
    only_this = [proposal_id]
    before, _ = await _reviewed(MAKER.user_id, since=window, proposal_ids=only_this)
    assert proposal_id not in [row[0].id for row in before], (
        "an old proposal nobody has answered belongs outside the window"
    )

    await _reject(CHECKER, company_id, proposal_id)

    after, _ = await _reviewed(MAKER.user_id, since=window, proposal_ids=only_this)
    assert proposal_id in [row[0].id for row in after], (
        "the proposer's record should show what became of it"
    )
    checker_rows, _ = await _reviewed(
        CHECKER.user_id, since=window, proposal_ids=only_this
    )
    assert proposal_id in [row[0].id for row in checker_rows], (
        "and the officer who decided it yesterday should see their own decision"
    )


async def test_the_listing_carries_the_company_name():
    """A row naming only an id would answer "did I touch this" and not "which company".

    The fixture company is nameless, as most are here, so it is given one — otherwise
    the join would return `None` whether or not it worked.
    """
    company_id, proposal_id = await _company_with_open_proposal(MAKER)
    name = f"Reviewed Co {uuid.uuid4().hex[:8]}"
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .values(name=name)
        )
        await db.commit()

    rows, _total = await _reviewed(MAKER.user_id)

    listed = next(row for row in rows if row[0].id == proposal_id)
    assert listed[2] == name
    assert listed[0].company_id == company_id
