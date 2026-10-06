"""The deal stage graph, as rules.

Contract: ``docs/contracts/deal-and-buyer.md`` §1.1. Architecture §3.3.

Pure: ``allowed_stage_moves`` is a ``staticmethod`` over a table, so the graph is
tested without a database. The guard that needs a company row is
integration-tested instead — keeping the table pure is what makes this file
possible.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.application.deal_service import (
    PERMITTED_STAGE_MOVES,
    DealService,
)
from app.modules.onboarding.domain.entities.deal_enums import DealStage


def _targets(stage: DealStage) -> set[DealStage]:
    return {move.to for move in DealService.allowed_stage_moves(stage)}


def test_a_new_deal_may_gather_paperwork_or_be_withdrawn():
    assert _targets(DealStage.OPEN) == {
        DealStage.GATHERING_PAPERWORK,
        DealStage.WITHDRAWN,
    }


def test_paperwork_may_be_handed_over_or_withdrawn():
    assert _targets(DealStage.GATHERING_PAPERWORK) == {
        DealStage.HANDED_OVER,
        DealStage.WITHDRAWN,
    }


@pytest.mark.parametrize("stage", [DealStage.HANDED_OVER, DealStage.WITHDRAWN])
def test_terminal_stages_offer_nothing(stage: DealStage):
    """A deal withdrawn in error is a new deal, not a reopened one: a record of
    what was decided must not be editable into a different decision."""
    assert stage.is_terminal is True
    assert _targets(stage) == set()


@pytest.mark.parametrize("stage", [DealStage.OPEN, DealStage.GATHERING_PAPERWORK])
def test_live_stages_are_not_terminal(stage: DealStage):
    assert stage.is_terminal is False


def test_the_graph_only_moves_forward():
    """No move returns to a stage the deal has already left. `OPEN` is never a
    target, and `GATHERING_PAPERWORK` is reachable only from `OPEN` — so a deal
    cannot be walked backwards to collect a different history."""
    assert all(DealStage.OPEN not in targets for targets in PERMITTED_STAGE_MOVES.values())
    sources = [
        stage
        for stage, targets in PERMITTED_STAGE_MOVES.items()
        if DealStage.GATHERING_PAPERWORK in targets
    ]
    assert sources == [DealStage.OPEN]


def test_every_stage_appears_in_the_table():
    """A stage missing from the table would raise `KeyError` inside
    `allowed_stage_moves` the first time a deal reached it."""
    assert set(PERMITTED_STAGE_MOVES) == set(DealStage)


def test_only_withdrawal_asks_for_a_reason():
    """A withdrawal carries its reason, expressed where the screen reads it: the form asks for the
    reason before submitting rather than showing a 422 afterwards."""
    needs_reason = {
        move.to
        for stage in DealStage
        for move in DealService.allowed_stage_moves(stage)
        if move.reason_required
    }
    assert needs_reason == {DealStage.WITHDRAWN}


def test_a_stage_is_never_a_move_to_itself():
    """Recording a move to the stage already held would write a history row saying
    nothing happened."""
    for stage in DealStage:
        assert stage not in _targets(stage)
