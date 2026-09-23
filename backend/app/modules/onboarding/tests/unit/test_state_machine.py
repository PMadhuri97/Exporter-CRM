"""
KYC case state machine — the pure half.

The 12 tests here assert the transition table, the exhaustive 12x12 legal/illegal
matrix, and the two doors that stop a caller writing ``state`` directly (the
repository and the ORM attribute). None of them touches a database, a router or a
network socket, which is what earns them a place under ``unit/``.

The 21 API-level tests that used to live here — they mint a token over HTTP, drive
the router, and read three tables over psycopg2 — moved to
``tests/integration/test_state_machine_api.py``. They need Postgres; these do not.

Acceptance criteria covered here:

  • Direct status mutation is blocked by a service-boundary / repository rule.
  • All 12 states and all 4 sources are represented in the table.
  • An illegal transition raises a 409-shaped error with a stable error code.
"""
import uuid

import pytest

from app.modules.onboarding.domain.entities.case import Case
from app.modules.onboarding.domain.entities.enums import CaseState, TransitionSource
from app.modules.onboarding.domain.policies.state_machine import (
    LEGAL_TRANSITIONS,
    DirectStateAssignmentError,
    IllegalTransitionError,
    allowed_next_states,
    assert_legal,
    is_legal,
    permit_state_write,
)

# ── Unit: the transition table itself ────────────────────────────────────────

def test_table_covers_all_twelve_states():
    """Every state is a key. A missing key would be a KeyError at runtime, not a 409."""
    assert set(LEGAL_TRANSITIONS) == set(CaseState)
    assert len(CaseState) == 12


def test_table_targets_are_all_real_states():
    for previous, targets in LEGAL_TRANSITIONS.items():
        for target in targets:
            assert isinstance(target, CaseState)
            assert target is not previous, "a state may not transition to itself"


def test_every_state_is_reachable_except_the_origin():
    """DRAFT is the only entry point; every other state must be arrivable."""
    reachable = {t for targets in LEGAL_TRANSITIONS.values() for t in targets}
    assert reachable == set(CaseState) - {CaseState.DRAFT}


def test_all_four_transition_sources_are_supported():
    from app.modules.onboarding.application.case_service import CaseService

    for source in TransitionSource:
        assert CaseService._actor_type_for(source) is not None
    assert len(TransitionSource) == 4


def test_a_provider_state_never_reaches_a_decision_by_itself():
    """
    The baseline principle as a table assertion: PROVIDER_FAILED cannot decide a case.

    PROVIDER_COMPLETED *may* move to APPROVED/REJECTED, but only because a decision
    drives that move — never the provider.
    """
    assert CaseState.APPROVED not in allowed_next_states(CaseState.PROVIDER_FAILED)
    assert CaseState.REJECTED not in allowed_next_states(CaseState.PROVIDER_FAILED)


def test_is_legal_and_assert_legal_agree():
    assert is_legal(CaseState.DRAFT, CaseState.SUBMITTED)
    assert not is_legal(CaseState.DRAFT, CaseState.APPROVED)
    assert_legal(CaseState.DRAFT, CaseState.SUBMITTED)
    with pytest.raises(IllegalTransitionError):
        assert_legal(CaseState.DRAFT, CaseState.APPROVED)


def test_illegal_transition_error_is_a_409_with_a_stable_error_code():
    error = IllegalTransitionError(CaseState.DRAFT, CaseState.APPROVED)
    assert error.status_code == 409
    assert error.error_code == "ILLEGAL_CASE_STATE_TRANSITION"
    assert error.previous_state is CaseState.DRAFT
    assert error.next_state is CaseState.APPROVED


# ── Unit: the parametrized legal / illegal matrix ────────────────────────────
#
# 12 × 12 = 144 pairs. Every pair the table names is legal; every pair it does not
# name raises. This is the whole contract of the guard, exhaustively.

@pytest.mark.parametrize("previous", list(CaseState))
@pytest.mark.parametrize("next_state", list(CaseState))
def test_transition_matrix(previous: CaseState, next_state: CaseState):
    if next_state in LEGAL_TRANSITIONS[previous]:
        assert_legal(previous, next_state)  # must not raise
    else:
        with pytest.raises(IllegalTransitionError):
            assert_legal(previous, next_state)


# ── Unit: direct state mutation is impossible ────────────────────────────────

@pytest.mark.asyncio
async def test_repository_refuses_direct_state_mutation():
    """The repository door (already closed earlier; re-asserted here as the state machine's own AC)."""
    from app.modules.onboarding.infrastructure.repositories import (
        CaseRepository,
        DirectStateMutationError,
    )

    repo = CaseRepository(session=None)  # never reaches the session
    with pytest.raises(DirectStateMutationError):
        await repo.update(Case(), state=CaseState.APPROVED)


def test_orm_attribute_refuses_direct_state_assignment():
    """
    The ORM door: `case.state = …` on a persisted case raises, so no service can
    bypass the machine by holding the model instance directly.

    A case with a database identity is simulated by giving it a primary key and
    telling the instance state it is persistent — exactly what SQLAlchemy does after
    a flush.
    """
    from sqlalchemy import inspect

    case = Case(state=CaseState.DRAFT)  # transient: initialisation is permitted
    assert case.state is CaseState.DRAFT

    case.id = uuid.uuid4()
    inspect(case).key = (Case, (case.id,), None)  # now it "exists" in the database

    with pytest.raises(DirectStateAssignmentError):
        case.state = CaseState.APPROVED

    assert case.state is CaseState.DRAFT, "a rejected assignment must not mutate state"


def test_the_state_machine_may_assign_state():
    """The same assignment inside `permit_state_write()` is the machine's own path."""
    from sqlalchemy import inspect

    case = Case(state=CaseState.DRAFT)
    case.id = uuid.uuid4()
    inspect(case).key = (Case, (case.id,), None)

    with permit_state_write():
        case.state = CaseState.SUBMITTED

    assert case.state is CaseState.SUBMITTED


def test_permission_does_not_leak_out_of_its_context():
    from sqlalchemy import inspect

    case = Case(state=CaseState.DRAFT)
    case.id = uuid.uuid4()
    inspect(case).key = (Case, (case.id,), None)

    with permit_state_write():
        case.state = CaseState.SUBMITTED

    with pytest.raises(DirectStateAssignmentError):
        case.state = CaseState.PROVIDER_PENDING

