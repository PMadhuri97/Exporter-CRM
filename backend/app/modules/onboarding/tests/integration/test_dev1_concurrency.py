"""Final-integration concurrency — Developer 1 (allocation §6: "handover vs flag; approve vs
new input; cycle start vs decision"; plan §18.3).

Behavioural, in two sessions, with the project's own locking (no new strategy):

* every background-check move — a decision, an approval, a new cycle — takes
  ``SELECT … FOR UPDATE`` on the company row (``BackgroundCheckService._lock_profile``);
* every writer of a compliance input takes ``FOR SHARE`` on it (``company_input_lock``);
* Developer 2's handover takes ``FOR SHARE`` on it while the guard runs (D10).

Each test pauses one transaction **while it holds its lock**, starts the competing one,
proves the second waits, releases the first, and checks the result is one of the serial
orders — never a mixture. The pause is a one-shot wrapper around a method only the paused
operation calls.

The buyer-company form of scenario A — a flag on the deal's **buyer** company while the
deal is handed over — needs Developer 2's ``deal.buyer_company_id`` (F2) and the guard
that share-locks both companies (P4-7), neither of which exists yet. It is the same lock
as the seller's, proved here.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
)
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.events import publisher as publisher_module
from app.modules.onboarding.exceptions import BackgroundCheckProposalStaleError
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.fixtures.compliance import record_required_checks
from app.modules.onboarding.tests.integration._dev1_support import (
    CHECKER,
    clear,
    flag,
    gauge,
    move,
    propose,
    ready_to_clear,
    start_cycle,
)
from app.modules.onboarding.tests.integration.test_l3b_handover import (
    _customer,
    _deal_ready_to_hand_over,
)
from app.platform.database import services as db_services
from app.platform.messaging.ports import InMemoryEventBus

pytestmark = pytest.mark.asyncio

State = BackgroundCheckState

#: Long enough that an unblocked operation would finish; short enough for the suite.
_WAIT = 1.5


@pytest.fixture(autouse=True)
def _quiet_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher_module, "get_event_bus", InMemoryEventBus)


class _Pause:
    """Wraps ``owner.name`` so its **first** call stops — the caller still holding its
    lock — until :meth:`release`; later calls run straight through."""

    def __init__(self, monkeypatch, owner, name: str, *, after: bool = False) -> None:
        self.reached = asyncio.Event()
        self._release = asyncio.Event()
        self._used = False
        original = getattr(owner, name)

        async def paused(*args, **kwargs):
            if self._used:
                return await original(*args, **kwargs)
            self._used = True
            if after:
                result = await original(*args, **kwargs)
                self.reached.set()
                await self._release.wait()
                return result
            self.reached.set()
            await self._release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(owner, name, paused)

    async def wait_reached(self) -> None:
        await asyncio.wait_for(self.reached.wait(), timeout=15)

    def release(self) -> None:
        self._release.set()


async def _blocked(task: asyncio.Task) -> bool:
    """Whether ``task`` is still waiting after ``_WAIT`` seconds."""
    done, _ = await asyncio.wait({task}, timeout=_WAIT)
    return not done


async def _approve(company_id, proposal_id):
    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).approve(
            company_id, proposal_id, actor_id=CHECKER.user_id, actor_role=CHECKER.role
        )


async def _hand_over(deal_id):
    async with db_services.AsyncSessionLocal() as db:
        return await DealService(db).transition_stage(
            deal_id, DealStage.HANDED_OVER, actor_id="tester"
        )


async def _customer_ready_to_clear() -> tuple[uuid.UUID, uuid.UUID]:
    """A CUSTOMER whose check is IN_REVIEW with every CLEAR prerequisite met (rule B
    included), and a deal ready to hand over but for the check."""
    company_id = await ready_to_clear(await _customer())
    return company_id, await _deal_ready_to_hand_over(company_id)


async def _decisions(company_id) -> list[BackgroundCheckDecision]:
    async with db_services.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(BackgroundCheckDecision)
            .where(BackgroundCheckDecision.company_id == company_id)
            .order_by(BackgroundCheckDecision.decided_at)
        )
        return list(rows.scalars())


def _assert_one_chain(decisions: list[BackgroundCheckDecision]) -> None:
    successors = [d.supersedes_decision_id for d in decisions if d.supersedes_decision_id]
    assert len(successors) == len(set(successors)), "the decision chain forked"
    assert sum(1 for d in decisions if d.supersedes_decision_id is None) == 1


# ── Scenario A: handover vs a compliance move on the same company ────────────


async def test_a_re_kyc_on_the_company_waits_for_a_handover_in_flight(monkeypatch):
    """The handover has passed its guard (CLEAR) and holds FOR SHARE; a Re-KYC — which
    reopens the Clear — waits, so the deal is never handed over on a withdrawn Clear."""
    company_id, deal_id = await _customer_ready_to_clear()
    await clear(company_id)
    pause = _Pause(monkeypatch, DealService, "_handover_snapshot")

    handover = asyncio.create_task(_hand_over(deal_id))
    await pause.wait_reached()
    re_kyc = asyncio.create_task(start_cycle(company_id))
    try:
        assert await _blocked(re_kyc), "a Re-KYC reopened the Clear under an in-flight handover"
        assert await gauge(company_id) is State.CLEAR
    finally:
        pause.release()
    assert (await asyncio.wait_for(handover, timeout=15)).stage is DealStage.HANDED_OVER
    started = await asyncio.wait_for(re_kyc, timeout=15)
    assert started.reopen is not None and await gauge(company_id) is State.IN_REVIEW


async def test_an_approval_in_flight_makes_the_handover_wait_and_then_read_it(monkeypatch):
    """The approval of a CLEAR holds FOR UPDATE until it commits; the handover's guard
    waits for it and then reads the committed CLEAR — never a half-written one."""
    company_id, deal_id = await _customer_ready_to_clear()
    proposal = await propose(company_id)
    pause = _Pause(monkeypatch, BackgroundCheckService, "_resolve")

    approval = asyncio.create_task(_approve(company_id, proposal.id))
    await pause.wait_reached()  # the decision is written, not committed
    handover = asyncio.create_task(_hand_over(deal_id))
    try:
        assert await _blocked(handover), "the guard read the company under an uncommitted approval"
    finally:
        pause.release()
    await asyncio.wait_for(approval, timeout=15)
    assert (await asyncio.wait_for(handover, timeout=15)).stage is DealStage.HANDED_OVER


async def test_a_flag_committed_first_refuses_the_handover():
    company_id, deal_id = await _customer_ready_to_clear()
    await flag(company_id, reason="adverse media confirmed")
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).get_deal(deal_id)
    assert "FLAGGED" in (view.handover_blocked_reason or "")
    assert DealStage.HANDED_OVER not in {stage_move.to for stage_move in view.allowed_stage_moves}


# ── Scenario B: an approval vs a new compliance input ────────────────────────


async def test_an_input_in_flight_makes_the_approval_wait_and_then_refuse(monkeypatch):
    """The input writer holds FOR SHARE; the approval's FOR UPDATE waits for it, then
    finds the inputs changed and refuses — an approval never rests on inputs the maker
    did not see."""
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    pause = _Pause(monkeypatch, VerificationService, "_stamp_cycle")

    new_input = asyncio.create_task(
        record_required_checks(company_id, types=("SANCTIONS",), status="FAILED")
    )
    await pause.wait_reached()
    approval = asyncio.create_task(_approve(company_id, proposal.id))
    try:
        assert await _blocked(approval), "the approval did not wait for the input writer"
    finally:
        pause.release()
    await asyncio.wait_for(new_input, timeout=15)
    with pytest.raises(BackgroundCheckProposalStaleError):
        await asyncio.wait_for(approval, timeout=15)
    assert await gauge(company_id) is State.IN_REVIEW


async def test_an_approval_in_flight_makes_the_input_wait_and_rest_outside_the_decision(
    monkeypatch,
):
    """The other order: the approval holds FOR UPDATE; the input waits, lands after the
    commit, and is not among what the decision rested on (a later input never rewrites
    a decision; new adverse information is acted on by a reopen)."""
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    pause = _Pause(monkeypatch, BackgroundCheckService, "_resolve")

    approval = asyncio.create_task(_approve(company_id, proposal.id))
    await pause.wait_reached()
    new_input = asyncio.create_task(record_required_checks(company_id, types=("AML",)))
    try:
        assert await _blocked(new_input), "an input landed under an uncommitted approval"
    finally:
        pause.release()
    decision = (await asyncio.wait_for(approval, timeout=15)).decision
    [result] = await asyncio.wait_for(new_input, timeout=15)
    async with db_services.AsyncSessionLocal() as db:
        pinned = set(
            (
                await db.execute(
                    select(BackgroundCheckEvidence.verification_result_id).where(
                        BackgroundCheckEvidence.decision_id == decision.id
                    )
                )
            ).scalars()
        )
    assert result.id not in pinned
    assert result.cycle_id == decision.cycle_id and await gauge(company_id) is State.CLEAR


# ── Scenario C: a new cycle vs a decision ────────────────────────────────────


async def test_a_move_waits_for_a_cycle_start_and_lands_in_the_new_cycle(monkeypatch):
    company_id = await ready_to_clear(await make_company())
    pause = _Pause(monkeypatch, CheckCycleRepository, "add_next", after=True)

    started = asyncio.create_task(start_cycle(company_id))
    await pause.wait_reached()  # cycle 2 inserted, not committed
    more_info = asyncio.create_task(move(company_id, State.MORE_INFO, reason="need accounts"))
    try:
        assert await _blocked(more_info), "a decision ran inside an uncommitted cycle start"
    finally:
        pause.release()
    cycle = (await asyncio.wait_for(started, timeout=15)).cycle
    decision = await asyncio.wait_for(more_info, timeout=15)
    assert cycle.number == 2 and decision.cycle_id == cycle.id
    _assert_one_chain(await _decisions(company_id))


async def test_a_cycle_start_waits_for_an_approval_and_then_reopens_it(monkeypatch):
    company_id = await ready_to_clear(await make_company())
    proposal = await propose(company_id)
    pause = _Pause(monkeypatch, BackgroundCheckService, "_resolve")

    approval = asyncio.create_task(_approve(company_id, proposal.id))
    await pause.wait_reached()
    started = asyncio.create_task(start_cycle(company_id))
    try:
        assert await _blocked(started), "a cycle started inside an uncommitted approval"
    finally:
        pause.release()
    cleared = (await asyncio.wait_for(approval, timeout=15)).decision
    new_cycle = await asyncio.wait_for(started, timeout=15)
    # Serial: the CLEAR in cycle 1, then the Re-KYC reopened it in cycle 2.
    assert new_cycle.cycle.number == 2 and new_cycle.reopen is not None
    assert new_cycle.reopen.cycle_id == new_cycle.cycle.id != cleared.cycle_id
    assert new_cycle.reopen.supersedes_decision_id == cleared.id
    async with db_services.AsyncSessionLocal() as db:
        cycles = await CheckCycleRepository(db).list_for_company(company_id)
    assert [c.number for c in cycles] == [1, 2]
    _assert_one_chain(await _decisions(company_id))
    assert await gauge(company_id) is State.IN_REVIEW

