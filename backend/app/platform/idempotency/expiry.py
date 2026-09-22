"""The S3T1 time-based expiry sweep.

Customer keys stop being claimed once their window closes and their operation has finished.
This is what notices: it moves completed and failed customer-key records to `expired`, which
releases the (key_value, scope_id) pair for reuse while leaving the record itself in place
as history.

What it deliberately does not touch:

  * `active` records, whatever their expires_at says. An in-flight operation is never
    expired out from under its caller; the record becomes eligible only once it reaches a
    terminal state, and then the already-past window makes it eligible immediately.
  * internal derived keys and rail references, at all. Their lifecycle ends when the parent
    settlement reaches a terminal state, which S3T2 owns. Expiring a rail reference on a
    clock would free a key the payment network still honours — a double-payment hazard, not
    a tidiness bug — so the key_type predicate here is a safety boundary rather than a
    filter, and it is backed by three further protections described in guard_rails below.
  * records that already reached `expired`. The status predicate excludes them, which is
    what makes re-running the sweep a no-op rather than a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)

logger = structlog.get_logger(__name__)

#: Postgres advisory lock key for the idempotency expiry sweep (AL-104 / S3T1).
#:
#: Advisory lock keys are global to the database, so every key the platform takes is
#: declared next to the work it guards and must stay unique across modules. Taken:
#: 4420001 purpose-code reload, 4430001 sector-registry reload, 4440001 compliance-rule
#: reload AND the ledger integrity check — those two collide, which is the reason this one
#: was checked against all of them rather than assigned by pattern.
IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY = 1040001

#: Rows expired per statement. The sweep loops until a batch comes back short, so this
#: bounds how long any single UPDATE holds row locks rather than how much work gets done.
#: At Crawl-phase volumes the first batch is the only one.
EXPIRY_BATCH_SIZE = 500

#: Hard stop on the batch loop. Reaching it means the table is producing eligible rows
#: faster than one sweep can clear them, which is a capacity problem that should surface as
#: a warning rather than as a transaction that never ends.
MAX_BATCHES_PER_SWEEP = 100

#: Terminal statuses whose window may be closed. `active` is absent by design.
EXPIRABLE_STATUSES = (IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED)


@dataclass(frozen=True)
class ExpirySweepResult:
    """Outcome of one sweep."""

    expired_count: int
    skipped: bool = False
    truncated: bool = False

    @property
    def ran(self) -> bool:
        """False when another replica held the lock and this sweep did nothing."""
        return not self.skipped


def _eligible_ids_stmt(batch_size: int):
    """Ids of records whose window has closed, newest expiry last.

    All four predicates matter, and one of them is redundant on purpose:

      key_type   — the IDK/RR safety boundary.
      status     — terminal only, and it makes the sweep self-idempotent: a row already
                   moved to `expired` cannot match a second time.
      IS NOT NULL— redundant against `<= now()` under SQL's three-valued logic, but it
                   states the intent to the next reader and survives a rewrite that flips
                   the comparison.
      <= now()   — evaluated by Postgres, not Python, so replicas with skewed clocks agree
                   on what has expired.

    Ordering by expires_at makes the batches deterministic and clears the oldest first.
    """
    return (
        select(IdempotencyRecord.id)
        .where(
            IdempotencyRecord.key_type == IdempotencyKeyType.CUSTOMER_KEY,
            IdempotencyRecord.status.in_(EXPIRABLE_STATUSES),
            IdempotencyRecord.expires_at.is_not(None),
            IdempotencyRecord.expires_at <= func.now(),
        )
        .order_by(IdempotencyRecord.expires_at)
        .limit(batch_size)
    )


def _expire_batch_stmt(batch_size: int):
    """UPDATE ... WHERE id IN (eligible batch) RETURNING id.

    Going through a bounded id subquery rather than updating by predicate directly is what
    makes the statement batchable; the RETURNING clause is how the loop knows whether the
    batch was short and it can stop.
    """
    return (
        update(IdempotencyRecord)
        .where(IdempotencyRecord.id.in_(_eligible_ids_stmt(batch_size).scalar_subquery()))
        .values(status=IdempotencyStatus.EXPIRED)
        .returning(IdempotencyRecord.id)
    )


def guard_rails() -> dict[str, str]:
    """The layered protections keeping IDK and RR out of time-based expiry.

    Returned as data so a test can assert on the set rather than restating it, and so the
    reasoning stays attached to the code it describes.
    """
    return {
        "query_predicate": "the sweep filters key_type = customer_key",
        "configuration": "IDK and RR have a null window, so registration never sets expires_at",
        "null_guard": "the sweep additionally requires expires_at IS NOT NULL",
        "index_predicate": (
            "ix_idempotency_record_ck_expiry names customer_key, so a query that drops the "
            "filter also loses its index and reads as a sequential scan in review"
        ),
    }


class IdempotencyExpiryService:
    """Runs the expiry sweep. One instance per invocation, holding one session."""

    def __init__(self, session: AsyncSession | Session) -> None:
        self._session = session

    async def run_expiry_sweep(
        self, *, batch_size: int = EXPIRY_BATCH_SIZE
    ) -> ExpirySweepResult:
        """Expire every customer key whose window has closed. Safe to run concurrently.

        Takes a transaction-scoped advisory lock first, so when several replicas fire the
        job at the same moment only one does the work and the rest return immediately. The
        lock is an efficiency measure rather than a correctness one: the status predicate
        already means a second sweep would match nothing the first had finished with.
        """
        acquired = await self._try_acquire_lock()
        if not acquired:
            logger.info("idempotency_expiry_sweep_skipped_already_running")
            return ExpirySweepResult(expired_count=0, skipped=True)

        total = 0
        truncated = True

        for _ in range(MAX_BATCHES_PER_SWEEP):
            batch = await self._expire_batch(batch_size)
            total += batch
            if batch < batch_size:
                truncated = False
                break

        if truncated:
            logger.warning(
                "idempotency_expiry_sweep_truncated",
                expired_count=total,
                max_batches=MAX_BATCHES_PER_SWEEP,
                batch_size=batch_size,
            )

        logger.info("idempotency_expiry_sweep_completed", expired_count=total)
        return ExpirySweepResult(expired_count=total, truncated=truncated)

    async def _try_acquire_lock(self) -> bool:
        result = await self._execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": IDEMPOTENCY_EXPIRY_SWEEP_LOCK_KEY},
        )
        return bool(result.scalar_one())

    async def _expire_batch(self, batch_size: int) -> int:
        result = await self._execute(_expire_batch_stmt(batch_size))
        return len(result.fetchall())

    async def _execute(self, statement, params: dict | None = None):
        """Run a statement on either session flavour, matching the rest of the capability."""
        if isinstance(self._session, AsyncSession):
            return await self._session.execute(statement, params)
        return self._session.execute(statement, params)
