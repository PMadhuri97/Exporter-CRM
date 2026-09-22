import asyncio

import pytest

from app.platform.configuration.config import settings
from app.platform.scheduler import services


@pytest.fixture(autouse=True)
async def clean_scheduler_globals(monkeypatch):
    # Reset scheduler globals before and after each test to ensure isolation
    monkeypatch.setattr(services, "_scheduler", None)
    monkeypatch.setattr(services, "_scheduled_tasks", [])
    yield
    if services._scheduler is not None:
        try:
            if services._scheduler.running and not services._scheduler._eventloop.is_closed():
                await services.stop_integrity_scheduler()
        except Exception:
            pass
    services._scheduler = None
    services._scheduled_tasks.clear()


@pytest.mark.asyncio
async def test_register_scheduled_task():
    async def dummy_task():
        pass

    services.register_scheduled_task(dummy_task)
    assert dummy_task in services._scheduled_tasks
    assert len(services._scheduled_tasks) == 1


@pytest.mark.asyncio
async def test_start_scheduler_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", False)

    async def dummy_task():
        pass

    services.register_scheduled_task(dummy_task)
    services.start_integrity_scheduler()

    assert services._scheduler is None


@pytest.mark.asyncio
async def test_start_scheduler_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 10)

    async def dummy_task():
        pass

    services.register_scheduled_task(dummy_task)
    services.start_integrity_scheduler()

    assert services._scheduler is not None
    assert services._scheduler.running

    jobs = services._scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "dummy_task"

    # Yield control to event loop so the scheduled coroutine job starts
    await asyncio.sleep(0.1)
    await services.stop_integrity_scheduler()


@pytest.mark.asyncio
async def test_start_scheduler_is_idempotent_while_running(monkeypatch):
    """A second start() on an already-running scheduler is a no-op.

    Guards against a duplicate lifespan/startup path scheduling every task twice,
    which would run the integrity check at double the configured frequency.
    """
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 10)

    async def dummy_task():
        pass

    services.register_scheduled_task(dummy_task)
    services.start_integrity_scheduler()

    first_scheduler = services._scheduler
    assert first_scheduler is not None
    assert len(first_scheduler.get_jobs()) == 1

    # Second call must not replace the scheduler or add another job.
    services.start_integrity_scheduler()

    assert services._scheduler is first_scheduler
    assert len(services._scheduler.get_jobs()) == 1

    await asyncio.sleep(0.1)
    await services.stop_integrity_scheduler()


@pytest.mark.asyncio
async def test_stop_scheduler_when_never_started_is_a_noop():
    """stop() before any start() returns cleanly rather than raising.

    Shutdown runs on every app exit, including one that failed before the
    scheduler was ever created.
    """
    assert services._scheduler is None

    await services.stop_integrity_scheduler()

    assert services._scheduler is None


@pytest.mark.asyncio
async def test_stop_scheduler(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRITY_CHECK_INTERVAL_SECONDS", 10)

    async def dummy_task():
        pass

    services.register_scheduled_task(dummy_task)
    services.start_integrity_scheduler()

    assert services._scheduler is not None
    assert services._scheduler.running
    assert len(services._scheduled_tasks) == 1

    # Yield control to event loop so the scheduled coroutine job starts
    await asyncio.sleep(0.1)
    await services.stop_integrity_scheduler()

    assert services._scheduler is None
    assert len(services._scheduled_tasks) == 0
