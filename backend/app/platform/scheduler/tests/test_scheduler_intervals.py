"""Per-task scheduling options, added so the S3T1 expiry sweep can run at its own cadence.

The scheduler previously gave every registered task the same interval and gated all of them
behind one flag, which meant a 5-minute job could not coexist with the 1-hour integrity
check. These tests pin the generalisation and, just as importantly, pin that a task
registered the old way still behaves the old way.
"""

import asyncio
import pathlib

import pytest

from app.platform.configuration.config import settings
from app.platform.scheduler import services

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[4]

FIVE_MINUTES_IN_SECONDS = 300


@pytest.fixture(autouse=True)
async def clean_scheduler_globals(monkeypatch):
    monkeypatch.setattr(services, "_scheduler", None)
    monkeypatch.setattr(services, "_scheduled_tasks", [])
    monkeypatch.setattr(services, "_task_options", {})
    yield
    if services._scheduler is not None:
        try:
            if services._scheduler.running and not services._scheduler._eventloop.is_closed():
                await services.stop_scheduler()
        except Exception:
            pass
    services._scheduler = None
    services._scheduled_tasks.clear()
    services._task_options.clear()


async def integrity_like_task() -> None:
    """Stands in for the ledger integrity check: registered with no options."""


async def expiry_like_task() -> None:
    """Stands in for the S3T1 expiry sweep: registered with its own interval."""


def _jobs() -> list:
    """Scheduled jobs, asserting the scheduler actually started.

    The assert is what keeps mypy honest about _scheduler being Optional, and it turns
    "started but with no jobs" into a clear failure rather than a StopIteration.
    """
    assert services._scheduler is not None, "scheduler did not start"
    return services._scheduler.get_jobs()


def _job(interval_seconds: int):
    return next(
        job
        for job in _jobs()
        if job.trigger.interval.total_seconds() == interval_seconds
    )


# ── Two cadences at once ──────────────────────────────────────────────────────────────


async def test_two_tasks_can_run_at_different_intervals(monkeypatch):
    """The whole point of the generalisation."""
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 3600)

    services.register_scheduled_task(integrity_like_task)
    services.register_scheduled_task(
        expiry_like_task, interval_seconds=FIVE_MINUTES_IN_SECONDS, enabled=True
    )
    services.start_scheduler()

    jobs = {job.id: job.trigger.interval.total_seconds() for job in _jobs()}

    assert jobs == {
        "integrity_like_task": 3600.0,
        "expiry_like_task": float(FIVE_MINUTES_IN_SECONDS),
    }

    await asyncio.sleep(0.1)
    await services.stop_scheduler()


async def test_expiry_sweep_registers_on_a_five_minute_interval(monkeypatch):
    """Case 10, using the cadence the deployed configuration actually declares."""
    from app.platform.idempotency import get_sweep_interval

    interval = get_sweep_interval()
    assert interval.total_seconds() == FIVE_MINUTES_IN_SECONDS

    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", False)
    services.register_scheduled_task(
        expiry_like_task, interval_seconds=int(interval.total_seconds()), enabled=True
    )
    services.start_scheduler()

    job = _job(FIVE_MINUTES_IN_SECONDS)
    assert job.id == "expiry_like_task"

    await asyncio.sleep(0.1)
    await services.stop_scheduler()


async def test_expiry_task_runs_even_when_the_integrity_check_is_disabled(monkeypatch):
    """The two jobs are independent; one being off must not silence the other."""
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", False)

    services.register_scheduled_task(integrity_like_task)
    services.register_scheduled_task(
        expiry_like_task, interval_seconds=FIVE_MINUTES_IN_SECONDS, enabled=True
    )
    services.start_scheduler()

    job_ids = [job.id for job in _jobs()]
    assert job_ids == ["expiry_like_task"]

    await asyncio.sleep(0.1)
    await services.stop_scheduler()


# ── Enable flags ──────────────────────────────────────────────────────────────────────


async def test_a_task_disabled_by_its_own_flag_is_not_scheduled(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 3600)

    services.register_scheduled_task(integrity_like_task)
    services.register_scheduled_task(
        expiry_like_task, interval_seconds=FIVE_MINUTES_IN_SECONDS, enabled=False
    )
    services.start_scheduler()

    job_ids = [job.id for job in _jobs()]
    assert job_ids == ["integrity_like_task"]

    await asyncio.sleep(0.1)
    await services.stop_scheduler()


async def test_scheduler_does_not_start_when_every_task_is_disabled(monkeypatch):
    """A scheduler with no jobs is a thread and a log line for no reason."""
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", False)

    services.register_scheduled_task(integrity_like_task)
    services.register_scheduled_task(
        expiry_like_task, interval_seconds=FIVE_MINUTES_IN_SECONDS, enabled=False
    )
    services.start_scheduler()

    assert services._scheduler is None


# ── The legacy registration path is unchanged ─────────────────────────────────────────


async def test_options_free_registration_still_follows_the_integrity_settings(monkeypatch):
    """A call site that passes no options keeps the behaviour it has always had."""
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 42)

    services.register_scheduled_task(integrity_like_task)
    services.start_scheduler()

    assert _job(42).id == "integrity_like_task"

    await asyncio.sleep(0.1)
    await services.stop_scheduler()


async def test_options_are_resolved_at_start_not_at_registration(monkeypatch):
    """Registration happens in the lifespan before settings are necessarily final."""
    services.register_scheduled_task(integrity_like_task)

    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 77)
    services.start_scheduler()

    assert _job(77).id == "integrity_like_task"

    await asyncio.sleep(0.1)
    await services.stop_scheduler()


async def test_stop_clears_registered_tasks_and_their_options(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 10)

    services.register_scheduled_task(
        expiry_like_task, interval_seconds=FIVE_MINUTES_IN_SECONDS, enabled=True
    )
    services.start_scheduler()

    await asyncio.sleep(0.1)
    await services.stop_scheduler()

    assert services._scheduled_tasks == []
    assert services._task_options == {}


def test_legacy_function_names_remain_available():
    """main.py is not the only caller; the original names must keep resolving."""
    assert services.start_integrity_scheduler is services.start_scheduler
    assert services.stop_integrity_scheduler is services.stop_scheduler


# ── The application actually wires the sweep ──────────────────────────────────────────


def test_lifespan_registers_the_expiry_sweep_with_the_configured_interval():
    """Guards the wiring itself: a job nobody registers never runs."""
    main_source = (BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    tasks_source = (BACKEND_ROOT / "app" / "platform" / "idempotency" / "tasks.py").read_text(encoding="utf-8")

    assert "IdempotencyExpiryService" in tasks_source
    assert "from app.platform.idempotency.tasks import" in main_source

    assert "run_idempotency_expiry_sweep_task" in main_source
    assert "get_sweep_interval()" in main_source
    assert "IDEMPOTENCY_EXPIRY_SWEEP_ENABLED" in main_source
    assert "start_scheduler()" in main_source
