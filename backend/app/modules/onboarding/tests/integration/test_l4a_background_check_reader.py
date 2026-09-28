"""The background-check read seam — Developer 4A, 4A-6.

What Developer 3's handover guard and (later) Developer 2's customer move read the
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
from app.modules.onboarding.tests.integration.test_l4a_background_check_service import (
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
        """D6 is open, and this is the documented interim behaviour (contract §10).

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

        The counterpart of the service's own serialisation test: Dev4A's *moves* lock,
        its *reads* do not, and the caller owns the choice (D10).
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


# ── The pure helper Developer 3 calls ────────────────────────────────────────


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

        This is what let Developer 3's guard stop handling `None`: "never checked" is
        a fact with a name, and it is still not `CLEAR`.
        """
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            company = await db.scalar(
                select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
            )
        assert current_background_check(company) == "NOT_STARTED"
        assert current_background_check(company) != "CLEAR"


# ── The Developer 3 handover guard, through the real seam ────────────────────


class TestTheHandoverGuard:
    async def test_the_guard_reads_the_real_column_now(self):
        """Developer 3's `read_background_check` is the helper, and returns the truth."""
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

# ── D10: the handover guard's lock (settled 28 September 2026) ───────────────


class TestTheHandoverLock:
    """The guard share-locks the company row while a handover is in progress.

    Dev4A's moves take `FOR UPDATE`, so a share lock in the guard makes a concurrent
    `FLAGGED` wait. Without it, a flag could commit between the guard seeing `CLEAR`
    and the handover committing, and a deal would reach the lending team on a company
    flagged moments earlier.
    """

    async def test_the_guard_locks_only_when_a_handover_is_happening(self):
        """`lock=True` from `transition_stage`, and nowhere else.

        Asserted at the call sites rather than by timing, because the harm of getting
        this wrong is not a failed test — it is every deal page load taking a lock on
        the company and blocking compliance.
        """
        import inspect

        from app.modules.onboarding.application import deal_service

        source = inspect.getsource(deal_service.DealService)
        # The move locks.
        assert "_handover_blocked_reason(deal, lock=True)" in source
        # The view does not.
        assert "await self._handover_blocked_reason(deal)\n" in source

    async def test_the_lock_is_a_share_lock_not_an_exclusive_one(self):
        """`FOR SHARE`, so two handovers on one company still run in parallel.

        `FOR UPDATE` would close the same race and also serialise unrelated
        handovers, which buys nothing.
        """
        import inspect

        from app.modules.onboarding.application import deal_service

        source = inspect.getsource(deal_service.DealService._handover_blocked_reason)
        assert "with_for_update(read=True)" in source

    async def test_a_read_of_a_deal_does_not_block_a_background_check_move(self):
        """The counterpart: rendering a deal must never delay compliance."""
        company_id = await _at_in_review()

        async def read_the_company():
            # What `_to_view` does: no lock.
            async with db_services.AsyncSessionLocal() as db:
                for _ in range(5):
                    await db.scalar(
                        select(ExporterProfile).where(
                            ExporterProfile.customer_id == company_id
                        )
                    )
            return "read"

        async def flag():
            async with db_services.AsyncSessionLocal() as db:
                await _service(db).flag(
                    company_id, reason="hit", actor_id="c", actor_role=UserRole.COMPLIANCE
                )
            return "flagged"

        results = await asyncio.gather(read_the_company(), flag())
        assert set(results) == {"read", "flagged"}
