"""Deterministic activity failure injection for compensation resilience tests.

The failure modes here all reduce to "make an activity fail on a chosen attempt so
Temporal retries it, then prove the retry produces exactly one business effect".
This module builds a wrapper activity that does that deterministically — keyed on
``activity.info().attempt``, never on wall-clock timing — and delegates to the real
activity implementation.

The wrapper is registered under the SAME activity name as the production activity,
so a workflow that calls the real activity by reference dispatches to the wrapper
(Temporal resolves activities by name). Production code is never modified to make a
test fail: the fault lives entirely in the wrapper the test worker registers.
"""
from __future__ import annotations

import enum
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

from temporalio import activity
from temporalio.exceptions import ApplicationError


class FaultMode(str, enum.Enum):
    #: No fault — the wrapper is a transparent pass-through (and still records).
    NORMAL = "normal"
    #: First attempt raises BEFORE the real body runs, so nothing downstream is
    #: committed on attempt 1; Temporal retries and attempt 2 runs for real.
    FAIL_FIRST = "fail_first"
    #: First attempt runs the real body to completion (downstream commits), THEN
    #: raises — modelling a lost response / uncertain timeout after the commit.
    #: Temporal retries; attempt 2 runs the real body again, which must discover
    #: the already-posted transaction and return without a second effect.
    COMMIT_THEN_TIMEOUT = "commit_then_timeout"


#: Type name Temporal sees on the injected failure. Retryable by default so the
#: workflow's own RetryPolicy governs the retry, exactly like a real transient
#: fault; callers can make it non-retryable to prove the opposite.
INJECTED_FAILURE_TYPE = "InjectedResilienceFault"


@dataclass
class FaultController:
    """Records every wrapped invocation so a test can assert on attempts made.

    Deterministic and side-effect free beyond its own log — it decides nothing;
    the wrapper decides from ``activity.info().attempt`` and the configured mode.
    """

    #: name -> list of attempt numbers observed, in call order.
    attempts: dict[str, list[int]] = field(default_factory=dict)
    #: name -> attempt numbers on which the injected fault fired.
    faults_fired: dict[str, list[int]] = field(default_factory=dict)

    def _record(self, name: str, attempt: int) -> None:
        self.attempts.setdefault(name, []).append(attempt)

    def _record_fault(self, name: str, attempt: int) -> None:
        self.faults_fired.setdefault(name, []).append(attempt)

    def call_count(self, name: str) -> int:
        return len(self.attempts.get(name, []))

    def max_attempt(self, name: str) -> int:
        return max(self.attempts.get(name, [0]), default=0)

    def fault_count(self, name: str) -> int:
        return len(self.faults_fired.get(name, []))


def faulty_activity(
    real: Callable[[Any], Awaitable[Any]],
    *,
    name: str,
    mode: FaultMode = FaultMode.NORMAL,
    controller: FaultController | None = None,
    retryable: bool = True,
    fail_attempts: int = 1,
) -> Callable[[Any], Awaitable[Any]]:
    """Wrap ``real`` in a fault-injecting activity registered as ``name``.

    Args:
        real: the real activity implementation (or any async callable) to delegate to.
        name: the activity name to register under — use the production activity's
            name to intercept it on the worker.
        mode: which fault to inject (see :class:`FaultMode`).
        controller: optional :class:`FaultController` to record attempts into.
        retryable: whether the injected failure is retryable (default True).
        fail_attempts: how many leading attempts the fault applies to (default 1).
    """
    ctrl = controller or FaultController()

    def _raise(attempt: int) -> None:
        ctrl._record_fault(name, attempt)
        raise ApplicationError(
            f"injected {mode.value} fault on attempt {attempt}",
            type=INJECTED_FAILURE_TYPE,
            non_retryable=not retryable,
        )

    async def _wrapper(inp: Any) -> Any:
        attempt = activity.info().attempt
        ctrl._record(name, attempt)

        if mode is FaultMode.FAIL_FIRST and attempt <= fail_attempts:
            _raise(attempt)

        result = await real(inp)

        if mode is FaultMode.COMMIT_THEN_TIMEOUT and attempt <= fail_attempts:
            # The real body already committed; simulate the response being lost.
            _raise(attempt)

        return result

    # Copy the real activity's *resolved* argument/return types onto the wrapper
    # before it is registered, so Temporal's data converter reconstructs the real
    # dataclass argument (a bare ``Any`` would hand the activity a raw dict). The
    # types must be resolved here because the real activity's module uses
    # ``from __future__ import annotations`` — its raw annotations are strings that
    # would not resolve against this module's globals.
    try:
        real_hints = get_type_hints(real)
        real_params = list(inspect.signature(real).parameters)
        if real_params and real_params[0] in real_hints:
            _wrapper.__annotations__["inp"] = real_hints[real_params[0]]
        if "return" in real_hints:
            _wrapper.__annotations__["return"] = real_hints["return"]
    except Exception:  # noqa: BLE001 — best-effort; falls back to Any
        pass

    return activity.defn(name=name)(_wrapper)
