"""Scheduled tasks for the idempotency platform module."""

from __future__ import annotations

import time

from app.platform.database.services import AsyncSessionLocal
from app.platform.idempotency.expiry import IdempotencyExpiryService
from app.platform.idempotency.liveness import check_detector_liveness
from app.platform.idempotency.violation_detector import ScheduledViolationDetector
from app.platform.observability.metrics import IDEMPOTENCY_EXPIRY_JOB_LAST_RUN


async def run_idempotency_expiry_sweep_task() -> None:
    """Run the idempotency key expiry sweep and stamp the Prometheus gauge on success.

    Designed to be called from a scheduler.  Owns its own DB session so it is safe
    to run outside of request scope.
    """
    async with AsyncSessionLocal() as db:
        service = IdempotencyExpiryService(db)
        await service.run_expiry_sweep()
        # The advisory lock is transaction-scoped, so the commit both persists the
        # transitions and releases the lock for the next replica to take.
        await db.commit()
        IDEMPOTENCY_EXPIRY_JOB_LAST_RUN.set(time.time())


async def run_scheduled_violation_check_task() -> None:
    """Run the 15-minute scheduled violation check across ledger, settlement, and rail records.

    Owns its own DB session and commits audit log records upon completion.
    """
    async with AsyncSessionLocal() as db:
        detector = ScheduledViolationDetector(db)
        await detector.run_scheduled_check()
        await db.commit()


async def run_violation_detector_liveness_task() -> None:
    """Run the detector liveness meta-monitoring check."""
    check_detector_liveness()

