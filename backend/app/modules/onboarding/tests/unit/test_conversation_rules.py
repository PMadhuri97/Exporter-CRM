"""The conversation gauge's rules, with no database.

``ConversationService.allowed_moves`` is a ``staticmethod`` over two enums, so the
rule table can be tested for what it *is* rather than for what one company's row
happens to make it do. Everything that needs a company row is in
``tests/integration/test_conversation_gauge.py``.

What is asserted here is exactly what `docs/contracts/engagement.md` §1.1, §2.2 and
§3.1 promise, in the same order.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.application.conversation_service import (
    HISTORY_DIMENSION_CONVERSATION,
    ConversationService,
)
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney

GAUGED = (ExporterJourney.PROSPECT, ExporterJourney.CUSTOMER)


def test_the_six_architecture_values_and_no_others():
    """Architecture §3.3 fixes six values. A seventh would be a contract change,
    and the enum is what the Postgres type in 0016 was created from."""
    assert [value.value for value in ExporterConversation] == [
        "NOT_CONTACTED",
        "REACHING_OUT",
        "SPOKE_TO_THEM",
        "INTERESTED",
        "NOT_NOW",
        "READY_NOW",
    ]


def test_the_history_dimension_is_the_one_the_contract_fixes():
    """`docs/contracts/history-row.md` §2 names it. Inventing a dimension string
    is the thing that table exists to prevent, so it is asserted rather than
    trusted to a code review."""
    assert HISTORY_DIMENSION_CONVERSATION == "conversation"


@pytest.mark.parametrize("journey", GAUGED)
@pytest.mark.parametrize("current", list(ExporterConversation))
def test_any_value_may_follow_any_other_except_the_current_one(current, journey):
    """Contract §1.1: a conversation is a judgement, not a pipeline. So the moves
    from any value are every other value — no ordering, no reachability."""
    moves = ConversationService.allowed_moves(current, journey)
    assert {move.to for move in moves} == set(ExporterConversation) - {current}


@pytest.mark.parametrize("current", list(ExporterConversation))
def test_a_lead_is_offered_no_moves(current):
    """The gauge applies from PROSPECT onward. A LEAD carries
    `NOT_CONTACTED` because the column is NOT NULL, not because anyone judged it,
    and `set_conversation` refuses every move — so offering one would be offering a
    button that comes back 409."""
    assert ConversationService.allowed_moves(current, ExporterJourney.LEAD) == []


@pytest.mark.parametrize("journey", GAUGED)
def test_only_not_now_needs_a_reason_and_a_check_back_date(journey):
    """Contract §4. Asserted as a property of the whole table rather than one row,
    so adding a value without deciding its rules fails here."""
    moves = {
        move.to: move
        for move in ConversationService.allowed_moves(
            ExporterConversation.NOT_CONTACTED, journey
        )
    }
    assert moves[ExporterConversation.NOT_NOW].reason_required is True
    assert moves[ExporterConversation.NOT_NOW].check_back_required is True
    for to, move in moves.items():
        if to is ExporterConversation.NOT_NOW:
            continue
        assert move.reason_required is False, to
        assert move.check_back_required is False, to


def test_the_customer_journey_is_still_gauged():
    """"From PROSPECT onward" includes CUSTOMER: an existing customer's next
    shipment is a fresh conversation. Stated as its own test because "onward" is
    the word a reader could take either way."""
    assert ConversationService.allowed_moves(
        ExporterConversation.READY_NOW, ExporterJourney.CUSTOMER
    )


def test_the_moves_are_plain_data_and_need_no_session():
    """`allowed_moves` is a staticmethod — the same shape as
    `ExporterProfileService.allowed_marker_moves` — so a route can answer "what may
    you do" without a query, and this file needs no database."""
    moves = ConversationService.allowed_moves(
        ExporterConversation.INTERESTED, ExporterJourney.PROSPECT
    )
    assert all(isinstance(move.to, ExporterConversation) for move in moves)
    assert all(isinstance(move.reason_required, bool) for move in moves)
