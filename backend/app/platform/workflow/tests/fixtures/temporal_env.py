from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

import app.platform.workflow.adapters.client as _client_module

# Escape hatch for environments that cannot write to the default location.
_CACHE_DIR_ENV_VAR = "TEMPORAL_TEST_SERVER_CACHE_DIR"

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "temporal-test-server"


def server_cache_dir() -> str:
    configured = os.environ.get(_CACHE_DIR_ENV_VAR)
    cache_dir = Path(configured) if configured else _DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


async def start_time_skipping_env() -> WorkflowEnvironment:
    return await WorkflowEnvironment.start_time_skipping(
        download_dest_dir=server_cache_dir(),
    )


# ── Persistent local Temporal server (restart-resilience testing) ─────────────
# start_time_skipping runs an in-memory server that cannot be stopped and
# restarted with its state intact, so it cannot prove a workflow survives a
# server restart. start_local runs the real dev server, which persists to a
# SQLite file (``dev_server_database_filename``). Pointing a fresh server at the
# same file after a stop restores every running workflow's history, so the
# original execution resumes under its own run_id rather than being restarted.


def free_tcp_port() -> int:
    """Ask the OS for an unused TCP port and release it immediately.

    A fresh port is taken on every server start so a restart never races the
    previous listener through TIME_WAIT. Server identity is carried by the
    persistent DB file, not the port — the client reconnects to whatever port
    the restarted server binds.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class PersistentTemporalServer:
    """A local Temporal dev server backed by a fixed on-disk DB file.

    ``start()``/``stop()`` may be called repeatedly; every ``start()`` reuses the
    same ``db_filename`` so workflow history survives a stop. Use it directly for
    the server-restart scenario::

        server = PersistentTemporalServer()
        await server.start()
        ... start workflow, drive into compensation ...
        await server.stop()          # kill the server mid-flight
        await server.start()         # same DB file — history is restored
        ... reconnect worker, workflow resumes ...
        await server.stop()
    """

    def __init__(self, db_filename: str | None = None) -> None:
        if db_filename is None:
            fd, path = tempfile.mkstemp(prefix="temporal-persistent-", suffix=".sqlite")
            os.close(fd)
            # start_local creates the DB itself; an empty pre-existing file makes
            # the very first start treat it as a corrupt store on some versions.
            os.unlink(path)
            db_filename = path
        self.db_filename = db_filename
        self._env: WorkflowEnvironment | None = None

    @property
    def env(self) -> WorkflowEnvironment:
        if self._env is None:
            raise RuntimeError("PersistentTemporalServer is not running; call start()")
        return self._env

    @property
    def client(self) -> Any:
        return self.env.client

    @property
    def is_running(self) -> bool:
        return self._env is not None

    async def start(self) -> WorkflowEnvironment:
        if self._env is not None:
            raise RuntimeError("server already running; call stop() first")
        self._env = await WorkflowEnvironment.start_local(
            ip="127.0.0.1",
            port=free_tcp_port(),
            dev_server_database_filename=self.db_filename,
            download_dest_dir=server_cache_dir(),
        )
        return self._env

    async def stop(self) -> None:
        if self._env is None:
            return
        env, self._env = self._env, None
        await env.shutdown()

    async def __aenter__(self) -> PersistentTemporalServer:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()
        # Best-effort cleanup of the on-disk store once the last user is done.
        for path in (self.db_filename, f"{self.db_filename}-wal", f"{self.db_filename}-shm"):
            try:
                os.unlink(path)
            except OSError:
                pass


@asynccontextmanager
async def run_worker(
    client: Any,
    *,
    task_queue: str,
    workflows: list[Any],
    activities: list[Any],
) -> AsyncIterator[Any]:
    """Run a Temporal worker for the body of the context.

    Unsandboxed to match the production worker and the other Temporal suites in
    this repo. Stopping the context stops the worker without touching the server,
    which is exactly the worker-restart half of the resilience story.
    """
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    async with worker as running:
        yield running


# ── Deterministic synchronization (no arbitrary sleeps) ────────────────────────


async def wait_for(
    predicate: Callable[[], Awaitable[bool]],
    *,
    attempts: int = 600,
    tick_seconds: float = 0.05,
    what: str = "condition",
) -> None:
    """Await ``predicate`` until it is true, polling on workflow state.

    The synchronization is the predicate — a durable fact (a query result, an
    execution status, a persisted row). ``tick_seconds`` is only the interval
    between checks, never the thing being waited on, so this stays deterministic
    rather than racing a fixed sleep against the workflow.
    """
    for _ in range(attempts):
        if await predicate():
            return
        await asyncio.sleep(tick_seconds)
    raise TimeoutError(f"timed out waiting for {what} after {attempts * tick_seconds:.1f}s")


async def wait_for_workflow_status(
    handle: WorkflowHandle,
    statuses: set[str],
    *,
    query: str = "current_status",
    attempts: int = 600,
    tick_seconds: float = 0.05,
) -> None:
    """Wait until the workflow's ``current_status`` query reports one of ``statuses``.

    Used to time a duplicate signal deterministically against workflow progress —
    e.g. hold the second signal until compensation has actually started.
    """

    async def _reached() -> bool:
        try:
            state = await handle.query(query)
        except Exception:
            return False
        return isinstance(state, dict) and state.get("status") in statuses

    await wait_for(
        _reached,
        attempts=attempts,
        tick_seconds=tick_seconds,
        what=f"workflow status in {sorted(statuses)}",
    )


async def wait_until_running(
    handle: WorkflowHandle,
    *,
    attempts: int = 600,
    tick_seconds: float = 0.05,
) -> str:
    """Wait until the execution is durably RUNNING; return its run_id.

    The run_id is captured so a caller can assert the SAME execution resumed
    after a restart rather than a new one having been started.
    """

    async def _running() -> bool:
        desc = await handle.describe()
        return desc.status is not None and desc.status.name == "RUNNING"

    await wait_for(_running, attempts=attempts, tick_seconds=tick_seconds, what="RUNNING")
    return (await handle.describe()).run_id


# ── Duplicate signal helpers ───────────────────────────────────────────────────


async def send_signal_twice(
    handle: WorkflowHandle,
    signal: Any,
    *args: Any,
) -> None:
    """Deliver the same signal twice back-to-back (duplicate before processing).

    Models a network retry that duplicates a compensation-triggering signal
    before the workflow has acted on the first. Delivers nothing of its own to
    production dedup logic — it only sends; what the workflow does with the
    second delivery is what the acceptance test asserts. ``*args`` is the signal
    payload, if any.
    """
    await handle.signal(signal, *args)
    await handle.signal(signal, *args)


async def send_duplicate_signal_after_status(
    handle: WorkflowHandle,
    signal: Any,
    *args: Any,
    statuses: set[str],
) -> None:
    """Send the signal, wait until the workflow reaches ``statuses``, then resend.

    Models the duplicate arriving *while compensation is in progress*: the second
    delivery is held with deterministic state synchronization (a status query),
    not a sleep, so it lands after compensation has demonstrably started.
    """
    await handle.signal(signal, *args)
    await wait_for_workflow_status(handle, statuses)
    await handle.signal(signal, *args)


def new_task_queue(prefix: str = "test") -> str:
    """A unique task queue so parallel/persistent runs never cross wires."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@asynccontextmanager
async def embedded_temporal_client() -> AsyncIterator[None]:
    """Point get_temporal_client() at an embedded, ephemeral Temporal test
    server for the duration of the context — no externally-running Temporal
    service required.

    CI has no Temporal service (only Postgres — see ci.yml's `services:`
    block); it only caches the downloaded test-server binary. Code that goes
    through the real get_temporal_client()/start_settlement_workflow() path
    (rather than driving a WorkflowEnvironment's client directly, the way
    test_settlement_workflow.py's own tests do) needs this seam to run
    anywhere but a developer machine with a real Temporal reachable at
    TEMPORAL_HOST.
    """
    previous = _client_module._client
    async with await start_time_skipping_env() as env:
        _client_module._client = env.client
        try:
            yield
        finally:
            _client_module._client = previous
