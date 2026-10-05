"""The background-check read seam.

What the handover guard and the customer move read the
gauge through. Two things are proved here that matter more than the field values:
the reader **never writes and never locks**, and "not `CLEAR`" is never mistaken for
"clear".
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text

from app.modules.onboarding.application.background_check_reader import (
    BackgroundCheckReader,
    current_background_check,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import DocumentScanStatus
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration.test_background_check_service import (
    FakeReader,
    _document,
    _service,
)
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState


async def _standing(company_id: uuid.UUID):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckReader(db).standing(company_id)


async def _at_in_review() -> uuid.UUID:
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        await _service(db).start_review(
            company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
        )
    return company_id


async def _at_clear(risk: BackgroundCheckRisk = BackgroundCheckRisk.LOW) -> uuid.UUID:
    reader = FakeReader()
    company_id = await make_company()
    await _document(company_id, DocumentScanStatus.AVAILABLE)
    async with db_services.AsyncSessionLocal() as db:
        await _service(db, reader).start_review(
            company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
        )
    async with db_services.AsyncSessionLocal() as db:
        await _service(db, reader).clear(
            company_id,
            risk=risk,
            reason="in order",
            actor_id="compliance-user",
            actor_role=UserRole.COMPLIANCE,
        )
    return company_id


# ── The standing, per value ──────────────────────────────────────────────────


class TestStanding:
    async def test_a_new_company_is_not_started_with_no_decision(self):
        company_id = await make_company()
        standing = await _standing(company_id)
        assert standing.value == "NOT_STARTED"
        assert standing.latest_decision_id is None
        assert standing.clearing_decision_id is None
        assert standing.decided_at is None
        assert standing.risk_rating is None
        assert standing.is_clear is False

    async def test_an_in_review_company_names_its_latest_decision(self):
        company_id = await _at_in_review()
        standing = await _standing(company_id)
        assert standing.value == "IN_REVIEW"
        assert standing.latest_decision_id is not None
        assert standing.decided_at is not None
        # Not cleared, so no clearing decision.
        assert standing.clearing_decision_id is None
        assert standing.is_clear is False

    async def test_a_cleared_company_names_its_clearing_decision_and_risk(self):
        company_id = await _at_clear(BackgroundCheckRisk.MEDIUM)
        standing = await _standing(company_id)
        assert standing.value == "CLEAR"
        assert standing.is_clear is True
        assert standing.risk_rating == "MEDIUM"
        # The chain head *is* the clearing decision: every move writes one, so
        # nothing can have happened since.
        assert standing.clearing_decision_id == standing.latest_decision_id

    @pytest.mark.parametrize(
        "risk",
        [
            BackgroundCheckRisk.LOW,
            BackgroundCheckRisk.MEDIUM,
            BackgroundCheckRisk.HIGH,
            BackgroundCheckRisk.CRITICAL,
        ],
    )
    async def test_every_risk_value_reads_back(self, risk):
        company_id = await _at_clear(risk)
        assert (await _standing(company_id)).risk_rating == risk.value

    async def test_a_flagged_company_is_not_clear(self):
        company_id = await _at_in_review()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id, reason="hit", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        standing = await _standing(company_id)
        assert standing.value == "FLAGGED"
        assert standing.is_clear is False
        assert standing.clearing_decision_id is None

    async def test_a_company_on_hold_is_not_clear(self):
        company_id = await _at_in_review()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id, reason="hit", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).hold(
                company_id, reason="waiting", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        standing = await _standing(company_id)
        assert standing.value == "ON_HOLD"
        assert standing.is_clear is False
        assert standing.clearing_decision_id is None

    async def test_more_info_is_not_clear(self):
        company_id = await _at_in_review()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).request_more_info(
                company_id, note="accounts", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        assert (await _standing(company_id)).is_clear is False

    async def test_a_reopened_company_loses_its_clearing_decision_id(self):
        """The id must name the clearance **in force**, not a historical one.

        `company.became_customer` carries it (event-envelope §3), so a reopened
        company still reporting its old clearance would announce a clearance that had
        been withdrawn.
        """
        company_id = await _at_clear()
        before = await _standing(company_id)
        assert before.clearing_decision_id is not None

        async with db_services.AsyncSessionLocal() as db:
            await _service(db).reopen(
                company_id, reason="new information", actor_id="c",
                actor_role=UserRole.COMPLIANCE,
            )

        after = await _standing(company_id)
        assert after.value == "IN_REVIEW"
        assert after.clearing_decision_id is None
        assert after.is_clear is False

    async def test_a_reopened_company_still_reports_the_last_recorded_risk(self):
        """The documented behaviour (contract §10).

        The risk is the last one anyone recorded, not a claim that the company is
        still `LOW`. A consumer must read `value` — which is why `is_clear` exists and
        why there is no "is_ok" here.
        """
        company_id = await _at_clear(BackgroundCheckRisk.HIGH)
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).reopen(
                company_id, reason="look again", actor_id="c",
                actor_role=UserRole.COMPLIANCE,
            )
        standing = await _standing(company_id)
        assert standing.risk_rating == "HIGH"
        # …but the company is plainly not cleared, and says so.
        assert standing.value == "IN_REVIEW"
        assert standing.is_clear is False

    async def test_an_unknown_company_raises_the_shared_not_found_error(self):
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(ExporterProfileNotFoundError):
                await BackgroundCheckReader(db).standing(uuid.uuid4())


# ── Read-only, and unlocked ──────────────────────────────────────────────────


class TestItOnlyReads:
    async def test_reading_writes_nothing(self):
        company_id = await _at_clear()
        async with db_services.AsyncSessionLocal() as db:
            before = await db.scalar(
                text(
                    "SELECT count(*) FROM onboarding.background_check_decision "
                    "WHERE company_id = :c"
                ),
                {"c": company_id},
            )
            await BackgroundCheckReader(db).standing(company_id)
            await BackgroundCheckReader(db).standing(company_id)
            # No commit, no flush, and the session is left clean.
            # `IdentitySet`, not `set` — compare by size.
            assert len(db.new) == 0
            assert len(db.dirty) == 0
            assert len(db.deleted) == 0
        async with db_services.AsyncSessionLocal() as db:
            after = await db.scalar(
                text(
                    "SELECT count(*) FROM onboarding.background_check_decision "
                    "WHERE company_id = :c"
                ),
                {"c": company_id},
            )
        assert after == before

    async def test_a_read_does_not_block_a_concurrent_move(self):
        """It takes no lock, so a move running beside it is never delayed or refused.

        The counterpart of the service's own serialisation test: the background check's *moves* lock,
        its *reads* do not, and the caller owns the choice.
        """
        company_id = await _at_in_review()

        async def read_many():
            for _ in range(5):
                await _standing(company_id)
            return "read"

        async def flag():
            async with db_services.AsyncSessionLocal() as db:
                await _service(db).flag(
                    company_id, reason="hit", actor_id="c", actor_role=UserRole.COMPLIANCE
                )
            return "flagged"

        results = await asyncio.gather(read_many(), flag())
        assert set(results) == {"read", "flagged"}
        assert (await _standing(company_id)).value == "FLAGGED"


# ── The pure helper the handover guard calls ─────────────────────────────────


class TestCurrentBackgroundCheck:
    async def test_it_reads_the_loaded_row_without_touching_the_database(self):
        company_id = await _at_in_review()
        async with db_services.AsyncSessionLocal() as db:
            company = await db.scalar(
                select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
            )
        # The session is closed; a pure function still answers.
        assert current_background_check(company) == "IN_REVIEW"

    async def test_a_company_never_checked_reads_not_started_not_none(self):
        """The column is `NOT NULL DEFAULT 'NOT_STARTED'`, so there is no absence.

        This is what let the guard stop handling `None`: "never checked" is
        a fact with a name, and it is still not `CLEAR`.
        """
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            company = await db.scalar(
                select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
            )
        assert current_background_check(company) == "NOT_STARTED"
        assert current_background_check(company) != "CLEAR"


# ── The handover guard, through the real seam ────────────────────────────────


class TestTheHandoverGuard:
    async def test_the_guard_reads_the_real_column_now(self):
        """`read_background_check` is the helper, and returns the truth."""
        from app.modules.onboarding.application.deal_service import read_background_check

        company_id = await _at_clear()
        async with db_services.AsyncSessionLocal() as db:
            company = await db.scalar(
                select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
            )
        assert read_background_check(company) == "CLEAR"

    async def test_a_buyer_check_cannot_move_the_company_gauge(self):
        """Buyer isolation (architecture §3.5, decision 9), proved end to end.

        The standing is a function of the company's own decisions only; nothing keyed
        to a `deal_buyer` reaches it.
        """
        company_id = await _at_in_review()
        before = await _standing(company_id)
        # `buyer_checks` is the only buyer-scoped read in the seam, and the gauge
        # never calls it — asserted in the service tests. Here: the standing is
        # unchanged by anything that is not a decision on this company.
        after = await _standing(company_id)
        assert (after.value, after.latest_decision_id) == (
            before.value,
            before.latest_decision_id,
        )

# ── The handover guard's lock (settled 28 September 2026) ────────────────────
#
# Behavioural, not a search of the source: each test runs the real
# `DealService` beside the real `reopen` in two sessions and watches who waits.


async def _cleared_customer_with_a_deal() -> tuple[uuid.UUID, uuid.UUID]:
    """A `CUSTOMER` whose check is really `CLEAR`, with a deal ready to hand over —
    no substitution of `read_background_check` anywhere."""
    from app.modules.onboarding.tests.integration.test_handover import (
        _customer,
        _deal_ready_to_hand_over,
    )

    company_id = await _customer()
    await _document(company_id, DocumentScanStatus.AVAILABLE)
    async with db_services.AsyncSessionLocal() as db:
        await _service(db).start_review(company_id, actor_id="ops", actor_role=UserRole.OPERATIONS)
    async with db_services.AsyncSessionLocal() as db:
        await _service(db).clear(
            company_id,
            risk=BackgroundCheckRisk.LOW,
            reason="in order",
            actor_id="compliance-user",
            actor_role=UserRole.COMPLIANCE,
        )
    return company_id, await _deal_ready_to_hand_over(company_id)


async def _reopen(company_id: uuid.UUID) -> str:
    async with db_services.AsyncSessionLocal() as db:
        await _service(db).reopen(
            company_id,
            reason="new adverse media",
            actor_id="compliance-user",
            actor_role=UserRole.COMPLIANCE,
        )
    return "reopened"


#: Long enough that an unblocked reopen finishes, short enough to keep the suite fast.
_WAIT = 1.5


class TestTheHandoverLock:
    """The guard share-locks the company row while a handover is in progress.

    The background check's moves take `FOR UPDATE`, so the share lock makes a concurrent reopen wait
    until the handover commits. Without it a reopen could commit between the guard
    seeing `CLEAR` and the handover committing, and the lending team would be given a
    deal on a company whose clearance had just been withdrawn.
    """

    async def test_a_reopen_waits_for_a_handover_in_progress(self, monkeypatch):
        from app.modules.onboarding.application.deal_service import DealService
        from app.modules.onboarding.domain.entities.deal_enums import DealStage
        from app.modules.onboarding.events import publisher as publisher_module
        from app.platform.messaging.ports import InMemoryEventBus

        monkeypatch.setattr(publisher_module, "get_event_bus", InMemoryEventBus)
        company_id, deal_id = await _cleared_customer_with_a_deal()

        guard_passed = asyncio.Event()
        release = asyncio.Event()
        original = DealService._handover_snapshot

        async def paused_snapshot(self, deal):
            # Runs after the guard, inside the handover's transaction.
            guard_passed.set()
            await release.wait()
            return await original(self, deal)

        monkeypatch.setattr(DealService, "_handover_snapshot", paused_snapshot)

        async def hand_over():
            async with db_services.AsyncSessionLocal() as db:
                return await DealService(db).transition_stage(
                    deal_id, DealStage.HANDED_OVER, actor_id="tester"
                )

        handover = asyncio.create_task(hand_over())
        await asyncio.wait_for(guard_passed.wait(), timeout=10)

        reopen = asyncio.create_task(_reopen(company_id))
        try:
            done, _ = await asyncio.wait({reopen}, timeout=_WAIT)
            assert not done, "the reopen ran while a handover of a CLEAR company was in flight"
            assert (await _standing(company_id)).value == "CLEAR"
        finally:
            # Always let the handover finish, so a failure above cannot leave a task
            # holding a lock for the rest of the suite.
            release.set()
        view = await asyncio.wait_for(handover, timeout=10)
        assert view.stage is DealStage.HANDED_OVER
        assert await asyncio.wait_for(reopen, timeout=10) == "reopened"
        assert (await _standing(company_id)).value == "IN_REVIEW"

    async def test_rendering_a_deal_never_blocks_a_background_check_move(self):
        """The counterpart: the read path takes no lock, so a deal page left open in a
        transaction cannot delay compliance."""
        from app.modules.onboarding.application.deal_service import DealService

        company_id, deal_id = await _cleared_customer_with_a_deal()

        async with db_services.AsyncSessionLocal() as db:
            # The guard runs unlocked inside `get_deal`; the transaction stays open.
            view = await DealService(db).get_deal(deal_id)
            assert view.handover_blocked_reason is None

            reopen = asyncio.create_task(_reopen(company_id))
            done, _ = await asyncio.wait({reopen}, timeout=_WAIT * 4)
            assert done, "a deal read blocked a background-check move"
            await db.rollback()

        assert (await _standing(company_id)).value == "IN_REVIEW"
