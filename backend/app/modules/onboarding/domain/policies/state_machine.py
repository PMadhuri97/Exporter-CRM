"""
The KYC case state machine.

This module is the **legal-transition table and its guard**, and nothing else. It
imports no model, no repository and no session: it is a pure function of
`(previous_state, next_state)`. That is deliberate — `models/case.py` imports
`state_write_permitted()` from here to enforce the single-writer rule, and a model
importing a service would be a cycle.

Three rules live here, and they are the whole of what the backlog asks for:

1. **The twelve states, and only the moves between them that the table names.**
   Anything else raises `IllegalTransitionError`, which the error handler renders
   as `409 Conflict` — the case is not mutated.

2. **The state machine is the only writer of case state** (design decision 8 in
   `docs/project-memory.md` §5.7). `CaseRepository.update()` already refuses the
   `state` column. That closes the repository door but leaves the ORM attribute
   itself open: any service holding a `Case` could write `case.state = APPROVED`.
   `permit_state_write()` closes that door too. A `set` listener on `Case.state`
   (registered in `models/case.py`) rejects every assignment to a case that already
   exists in the database unless it happens inside this context manager, which only
   `CaseService.transition()` enters.

3. **Transition *sources* are recorded, not gated.** The backlog names four sources
   and requires every transition to record which one applied. It does not say that a
   given move is legal from one source and illegal from another, and inventing that
   rule would silently forbid moves the document permits — so `source` is data on the
   transition row, not a second dimension of the table.
"""
from __future__ import annotations

import contextlib
import contextvars
import uuid
from collections.abc import Iterator

import structlog.contextvars

from app.modules.onboarding.domain.entities.enums import CaseState
from app.shared.exceptions import AnerBaseException

# ── The legal-transition table ────────────────────────────────────────────────
#
# Read a row as "from this state, the case may move to any of these". Every state
# is a key, including the terminal ones, so a missing key is a programming error
# rather than a silently empty transition set.
#
# The shape follows the lifecycle the backlog describes:
#
#   DRAFT → SUBMITTED → PROVIDER_PENDING → PROVIDER_COMPLETED
#                                       ↘ PROVIDER_FAILED ⟲ (retry)
#   …then a *human or platform* decision reaches APPROVED / REJECTED. A provider
#   never lands the case in a decided state on its own — that is the baseline
#   principle (§1.3) expressed as a transition table: PROVIDER_COMPLETED does not
#   equal APPROVED, it merely permits the move.
#
# CLOSED is reachable from every non-terminal state: a case can always be abandoned.
# REOPENED_BY_EXCEPTION is the one way back out of a decided or closed case, and it
# lands in review rather than in a decision.
LEGAL_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.DRAFT: frozenset(
        {CaseState.SUBMITTED, CaseState.CLOSED}
    ),
    CaseState.SUBMITTED: frozenset(
        {
            CaseState.PROVIDER_PENDING,
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.CLOSED,
        }
    ),
    CaseState.PROVIDER_PENDING: frozenset(
        {
            CaseState.PROVIDER_COMPLETED,
            CaseState.PROVIDER_FAILED,
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.CLOSED,
        }
    ),
    # A completed provider run is evidence, not a verdict. It may be decided
    # directly, sent to a reviewer, or bounced back to the subject for more info.
    CaseState.PROVIDER_COMPLETED: frozenset(
        {
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.MORE_INFO_REQUESTED,
            CaseState.APPROVED,
            CaseState.REJECTED,
            CaseState.CLOSED,
        }
    ),
    # A provider failure must never decide a case (§6.2). It can only be retried,
    # escalated to a human, or closed.
    CaseState.PROVIDER_FAILED: frozenset(
        {
            CaseState.PROVIDER_PENDING,
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.CLOSED,
        }
    ),
    CaseState.MANUAL_REVIEW_REQUIRED: frozenset(
        {
            CaseState.MORE_INFO_REQUESTED,
            CaseState.APPROVED,
            CaseState.REJECTED,
            CaseState.CLOSED,
        }
    ),
    CaseState.MORE_INFO_REQUESTED: frozenset(
        {
            CaseState.SUBMITTED,
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.REJECTED,
            CaseState.CLOSED,
        }
    ),
    # Periodic re-review of a live customer, and the exception path back in.
    CaseState.APPROVED: frozenset(
        {CaseState.REVIEW_DUE, CaseState.CLOSED, CaseState.REOPENED_BY_EXCEPTION}
    ),
    CaseState.REJECTED: frozenset(
        {CaseState.CLOSED, CaseState.REOPENED_BY_EXCEPTION}
    ),
    CaseState.REVIEW_DUE: frozenset(
        {
            CaseState.SUBMITTED,
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.CLOSED,
        }
    ),
    CaseState.CLOSED: frozenset({CaseState.REOPENED_BY_EXCEPTION}),
    CaseState.REOPENED_BY_EXCEPTION: frozenset(
        {
            CaseState.SUBMITTED,
            CaseState.MANUAL_REVIEW_REQUIRED,
            CaseState.CLOSED,
        }
    ),
}


class IllegalTransitionError(AnerBaseException):
    """
    An attempt to move a case between two states the table does not connect.

    Rendered as `409 Conflict` with `error_code = ILLEGAL_CASE_STATE_TRANSITION`,
    per §5.5 and the state-machine acceptance criteria. The case is never mutated:
    the guard runs before the assignment.
    """

    def __init__(self, previous_state: CaseState, next_state: CaseState) -> None:
        allowed = sorted(s.value for s in LEGAL_TRANSITIONS[previous_state])
        super().__init__(
            detail=(
                f"Illegal case state transition {previous_state.value} → {next_state.value}. "
                f"Allowed from {previous_state.value}: {', '.join(allowed) or 'none'}."
            ),
            error_code="ILLEGAL_CASE_STATE_TRANSITION",
            status_code=409,
        )
        self.previous_state = previous_state
        self.next_state = next_state


def allowed_next_states(previous_state: CaseState) -> frozenset[CaseState]:
    """Every state legally reachable from `previous_state` in one move."""
    return LEGAL_TRANSITIONS[previous_state]


def is_legal(previous_state: CaseState, next_state: CaseState) -> bool:
    return next_state in LEGAL_TRANSITIONS[previous_state]


def assert_legal(previous_state: CaseState, next_state: CaseState) -> None:
    """Raise `IllegalTransitionError` (409) unless the table connects the two states."""
    if not is_legal(previous_state, next_state):
        raise IllegalTransitionError(previous_state, next_state)


# ── The single-writer guard ───────────────────────────────────────────────────

_STATE_WRITE_PERMITTED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "onboarding_case_state_write_permitted", default=False
)


class DirectStateAssignmentError(RuntimeError):
    """
    Raised when code assigns `Case.state` on a persisted case outside the machine.

    Deliberately **not** an `AnerBaseException`: like `DirectStateMutationError`, this
    is a programming error and must never be rendered as an HTTP response. No request
    can provoke it — only a developer writing `case.state = …` can.
    """


@contextlib.contextmanager
def permit_state_write() -> Iterator[None]:
    """
    The only window in which `Case.state` may be assigned on an existing case.

    Scoped to the calling coroutine by `contextvars`, so a concurrent request that
    is not transitioning cannot ride on this one's permission.
    """
    token = _STATE_WRITE_PERMITTED.set(True)
    try:
        yield
    finally:
        _STATE_WRITE_PERMITTED.reset(token)


def state_write_permitted() -> bool:
    return _STATE_WRITE_PERMITTED.get()


# ── Correlation ───────────────────────────────────────────────────────────────


def resolve_correlation_id(explicit: uuid.UUID | None = None) -> uuid.UUID | None:
    """
    The request's correlation id, for the transition row's first-class column.

    Mirrors `AuditService._resolve_correlation_id` (and the two other copies in
    `app/events/producer.py` and `onboarding/utils/events.py`): the value is bound
    into structlog contextvars by `CorrelationIdMiddleware`, and a non-UUID value is
    dropped rather than stored, keeping the column strongly typed.
    """
    if explicit is not None:
        return explicit
    raw = structlog.contextvars.get_contextvars().get("correlation_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None
