"""Scheduler capability service — periodic background work on the application event loop.

One AsyncIOScheduler per process, started from the FastAPI lifespan. Tasks register
themselves before start; each may declare its own interval and its own enable flag.

A task registered without options keeps the original behaviour — it runs at
INTEGRITY_CHECK_INTERVAL_SECONDS and is gated by INTEGRITY_CHECK_ENABLED. That is what the
ledger integrity check does, and why those two settings still appear here despite the
scheduler no longer being integrity-specific: they are the legacy defaults, not a statement
that this module only schedules integrity checks.

The scheduler is a *trigger*, not a guarantee of single execution. It runs in-process, so N
replicas mean N firings of every job. Jobs that must not run concurrently take a Postgres
advisory lock themselves — see IdempotencyExpiryService.run_expiry_sweep.
"""
from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.platform.configuration.config import settings

logger = structlog.get_logger(__name__)

TaskFn = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class _TaskOptions:
    """Per-task overrides. None on a field means "use the legacy INTEGRITY_CHECK_* setting"."""

    interval_seconds: int | None = None
    enabled: bool | None = None


_scheduler: AsyncIOScheduler | None = None

#: Registered callables, in registration order. Deliberately a plain list of functions
#: rather than of option records: callers and tests identify a task by the function itself,
#: and per-task options are a detail of how it is scheduled, not part of its identity.
_scheduled_tasks: list[TaskFn] = []

#: Options by task name, populated only for tasks that passed any. A task absent from here
#: is a legacy registration and resolves entirely from settings.
_task_options: dict[str, _TaskOptions] = {}


def register_scheduled_task(
    task_fn: TaskFn,
    *,
    interval_seconds: int | None = None,
    enabled: bool | None = None,
) -> None:
    """Register an async callback to run periodically once the scheduler starts.

    interval_seconds and enabled default to the INTEGRITY_CHECK_* settings when omitted, so
    an existing call site keeps its behaviour unchanged. Pass them to schedule a task on its
    own cadence — two jobs at different intervals is the point of the options.

    Both are resolved at start time rather than here, so a caller may register first and
    configure afterwards, which is how the tests drive this.
    """
    _scheduled_tasks.append(task_fn)
    if interval_seconds is not None or enabled is not None:
        _task_options[task_fn.__name__] = _TaskOptions(
            interval_seconds=interval_seconds, enabled=enabled
        )


def _resolve_options(task_fn: TaskFn) -> tuple[int, bool]:
    """(interval_seconds, enabled) for a task, filling gaps from the legacy settings."""
    options = _task_options.get(task_fn.__name__, _TaskOptions())

    interval = (
        options.interval_seconds
        if options.interval_seconds is not None
        else settings.INTEGRITY_CHECK_INTERVAL_SECONDS
    )
    enabled = (
        options.enabled if options.enabled is not None else settings.INTEGRITY_CHECK_ENABLED
    )
    return interval, enabled


def start_scheduler() -> None:
    """Start the scheduler, adding one job per enabled task.

    Does nothing when no registered task is enabled — a scheduler with no jobs is a thread
    and a log line for no reason, and the original behaviour of "integrity check disabled
    means no scheduler" falls out of this naturally.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("scheduler_already_running")
        return

    runnable = [(task, *_resolve_options(task)) for task in _scheduled_tasks]
    enabled = [(task, interval) for task, interval, is_on in runnable if is_on]

    if not enabled:
        logger.info("scheduler_not_started_no_enabled_tasks", registered=len(_scheduled_tasks))
        return

    _scheduler = AsyncIOScheduler()

    for task, interval_seconds in enabled:
        _scheduler.add_job(
            task,
            trigger="interval",
            seconds=interval_seconds,
            next_run_time=datetime.datetime.now(datetime.UTC),
            id=task.__name__,
            replace_existing=True,
        )
        logger.info(
            "scheduled_task_registered",
            task=task.__name__,
            interval_seconds=interval_seconds,
        )

    _scheduler.start()
    logger.info("scheduler_started", job_count=len(enabled))


async def stop_scheduler() -> None:
    """Stop the scheduler and clear the registry."""
    global _scheduler

    if _scheduler is None:
        _scheduled_tasks.clear()
        _task_options.clear()
        return

    if _scheduler.running:
        logger.info("stopping_scheduler")
        _scheduler.shutdown(wait=False)

    _scheduler = None
    _scheduled_tasks.clear()
    _task_options.clear()
    logger.info("scheduler_stopped")


#: Original names, kept because call sites and tests use them. The scheduler was
#: integrity-specific when it was written and is not any more; these are aliases rather
#: than a second implementation so the two can never drift.
start_integrity_scheduler = start_scheduler
stop_integrity_scheduler = stop_scheduler
