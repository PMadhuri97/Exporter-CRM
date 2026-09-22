"""The read-only investigation interface over the idempotency registry.

Composes the audit repository with the resolvers each owning module supplies,
and exposes the operations the operations and compliance teams actually ask for:

  get_record                      key + scope -> the record, response cache and all.
  list_settlement_records         settlement -> everything it registered, hot and
                                  archived, optionally date-bounded.
  list_duplicate_detections       operation type + window -> the duplicates
                                  caught for it. Detections, never violations.
  list_violations                 recorded idempotency failures, newest first.
                                  Violations, never detections.
  list_ledger_transaction_records transaction -> the records that guarded it.

Every list is paginated (BUILD.md #10). Registry queries span both storage tiers;
detections and violations each live in a single table of their own.

DETECTIONS ARE NOT VIOLATIONS
The two are inverse events and are kept apart all the way down. A detection is a
re-presented key that was short-circuited — the control working. A violation is a
key that failed to deduplicate, so the operation ran more than once. They come from
different tables through different collaborators, and no method here returns both.

READ-ONLY
This service holds repositories and adapters. It has no session of its own,
opens no transaction, and calls nothing that writes — the sessions its
collaborators carry come from the read-only dependencies, whose role cannot
write even if this code tried. ``tests/test_audit_service.py`` asserts the
absence structurally, so a write collaborator added later fails a test rather
than review.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog

from app.platform.idempotency.audit_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AuditRecord,
    AuditRecordPage,
    IdempotencyAuditRepository,
)
from app.platform.idempotency.detection_repository import (
    DetectionPage,
    DuplicateDetectionRepository,
)
from app.platform.idempotency.exceptions import IdempotencyKeyNotFoundError
from app.platform.idempotency.ports import (
    ReferenceKeyResolver,
    ScopedReferenceResolver,
    ViolationSource,
)
from app.shared.contracts.idempotency import ViolationPage

logger = structlog.get_logger(__name__)


class IdempotencyAuditQueryService:
    """Read-only queries over the registry, for investigation tooling.

    Instantiate with sessions from the read-only dependencies. The service never
    creates one, so no credential appears in this module.
    """

    def __init__(
        self,
        records: IdempotencyAuditRepository,
        *,
        settlements: ScopedReferenceResolver,
        ledger_transactions: ReferenceKeyResolver,
        detections: DuplicateDetectionRepository,
        violations: ViolationSource,
    ) -> None:
        self._records = records
        self._settlements = settlements
        self._ledger_transactions = ledger_transactions
        self._detections = detections
        self._violations = violations

    async def get_record(self, key_value: str, scope_id: str) -> AuditRecord:
        """The record registered under this key and scope, archived or not.

        Raises rather than returning None: the caller asked about a specific
        key, and "no such key" is a different outcome from "a key whose record
        happens to be empty". The endpoint turns it into a 404.
        """
        record = await self._records.get_by_key(key_value, scope_id)
        if record is None:
            raise IdempotencyKeyNotFoundError(key_value, scope_id)
        return record

    async def list_settlement_records(
        self,
        settlement_id: uuid.UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> AuditRecordPage:
        """Everything this settlement registered, oldest first.

        Answers two of the epic's questions with one method, because they are
        the same question: reconstructing what happened during a settlement, and
        cross-referencing a settlement id back to its keys. The only difference
        was the date bound, which is optional here.

        Both halves of the settlement's reachability are resolved before the
        query, not after: scopes derivable from the settlement and its legs, and
        the key its customer-key record was registered under, which carries no
        settlement linkage at all. They go into a single statement — resolving
        them into two queries and merging the pages would page each side
        independently and silently drop records from the second page on.
        """
        scope_ids = await self._settlements.scope_ids_for(settlement_id)
        key_values = await self._settlements.idempotency_keys_for(settlement_id)
        return await self._records.list_for_reference(
            scope_ids=scope_ids,
            key_values=key_values,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    async def list_duplicate_detections(
        self,
        operation_type: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> DetectionPage:
        """Duplicates of this operation type caught in this window, most recent first.

        These are detections, not violations. Each row is a request that reused a
        key and was correctly prevented from executing again — the idempotency
        control working, recorded so that an operation type generating many of
        them can be traced back to the caller responsible.

        Read from the persisted ``duplicate_detection`` log rather than from the
        Prometheus counter beside it. The counter is labelled by operation type
        and key type and carries no key value, deliberately — an unbounded label
        would be a cardinality incident — so it can say how many duplicates an
        operation saw and never which.

        Violations are a different event with a different source, returned by a
        different method. Nothing here reads them, and nothing here should ever
        present a detection as one.
        """
        return await self._detections.list_by_operation(
            operation_type, since=since, until=until, limit=limit, offset=offset
        )

    async def list_violations(
        self,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> ViolationPage:
        """Recorded idempotency violations, most recent first.

        Each is an actual failure — duplicate execution that happened despite the
        idempotency controls — as written to the audit log by the violation
        detector. Read independently of duplicate detections, which are the
        opposite event: a detection proves an operation did *not* run twice.

        Every record is returned, not one per incident. The scheduled check
        re-records a violation on each run that still finds it, so an unresolved
        incident recurs under the same ``violation_hash``; grouping by that hash
        is the caller's choice to make.

        Paging is clamped here rather than trusted to the adapter, which lives in
        another module and has no reason to know this interface's page ceiling.
        """
        return await self._violations.list_violations(
            limit=max(1, min(limit, MAX_PAGE_SIZE)),
            offset=max(0, offset),
        )

    async def list_ledger_transaction_records(
        self,
        transaction_id: uuid.UUID,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> AuditRecordPage:
        """The registry records that guarded this ledger transaction.

        A page rather than a record. The link is the key value, which says
        nothing about scope, so one transaction's key can legitimately match
        records in several scopes — and that shape is exactly what a suspected
        duplicate looks like. Collapsing it would hide the answer.

        A transaction with no registry record yields an empty page. That is a
        real and unremarkable state: not every posting registers a key.
        """
        key_values = await self._ledger_transactions.idempotency_keys_for(transaction_id)
        return await self._records.list_by_key_values(
            key_values, limit=limit, offset=offset
        )
