"""Reads the idempotency registry and its archive as one collection.

Records move from ``ledger.idempotency_record`` to ``ledger.idempotency_archive``
when the nightly archival job runs, so which table holds a given record is an
artefact of timing rather than anything a caller should have to know. Every
query here spans both, and the table a row came from travels back as data on
``source`` so a caller may report it without ever having to ask for it.

The union is built once, in ``_union``, and nothing outside this module selects
from either table directly. That single seam is what lets a colder tier — the
GCS audit sink the archival job already writes to, or a warehouse over it —
arrive as another branch without changing a caller.

Filters are applied inside each branch rather than to the union as a whole.
Predicates over a union are usually pushed down, but "usually" is not a property
worth relying on for a table that only ever grows: a filter written on the
outside is one planner decision away from a sequential scan over the archive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Select, cast, func, literal, null, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.platform.idempotency.archive_models import IdempotencyArchive
from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)

#: Ceiling on any single page. Matches the ledger query endpoints so an operator
#: moving between investigation tools meets one limit, not several.
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100


class RecordSource(str, Enum):
    """Which table answered for a record."""

    HOT = "hot"
    ARCHIVE = "archive"


#: Columns present on both tables, in the order both branches project them. A
#: UNION matches by position, so this tuple is the contract between the two
#: branches — adding a column to one model without adding it here changes
#: nothing, and adding it here without adding it to both models fails loudly.
_SHARED_COLUMNS = (
    "id",
    "key_value",
    "scope_id",
    "key_type",
    "operation_type",
    "status",
    "response_cache",
    "response_reference",
    "first_seen_at",
    "completed_at",
    "expires_at",
    "correlation_id",
    "created_by",
    "record_metadata",
)


@dataclass(frozen=True)
class AuditRecord:
    """One idempotency record, wherever it currently lives."""

    id: uuid.UUID
    key_value: str
    scope_id: str
    key_type: IdempotencyKeyType
    operation_type: str
    status: IdempotencyStatus
    response_cache: dict | None
    response_reference: str | None
    first_seen_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    correlation_id: str | None
    created_by: str | None
    record_metadata: dict | None
    source: RecordSource
    archived_at: datetime | None


@dataclass(frozen=True)
class AuditRecordPage:
    """A page of records. ``total`` counts every match, not just this page.

    Independent of limit and offset so a caller can tell whether more pages
    remain rather than inferring it from a possibly-short page.
    """

    total: int
    limit: int
    offset: int
    records: list[AuditRecord]


def _row_to_record(row: Any) -> AuditRecord:
    return AuditRecord(
        id=row.id,
        key_value=row.key_value,
        scope_id=row.scope_id,
        key_type=row.key_type,
        operation_type=row.operation_type,
        status=row.status,
        response_cache=row.response_cache,
        response_reference=row.response_reference,
        first_seen_at=row.first_seen_at,
        completed_at=row.completed_at,
        expires_at=row.expires_at,
        correlation_id=row.correlation_id,
        created_by=row.created_by,
        record_metadata=row.record_metadata,
        source=RecordSource(row.source),
        archived_at=row.archived_at,
    )


def _branch(
    model: type[IdempotencyRecord] | type[IdempotencyArchive],
    source: RecordSource,
    archived_at: Any,
    criteria: list,
) -> Select:
    """One side of the union: the shared columns, its source, and its archived_at."""
    projection = [getattr(model, name).label(name) for name in _SHARED_COLUMNS]
    projection.append(literal(source.value).label("source"))
    projection.append(archived_at)
    return select(*projection).where(*criteria)


def _union(hot_criteria: list, archive_criteria: list):
    """Both tables as one selectable, each side already filtered.

    The hot side's ``archived_at`` is a cast NULL rather than a bare one.
    PostgreSQL takes a union column's type from the first branch that supplies
    one, so a bare NULL here fails with "could not determine data type" the day
    anyone reorders the branches — a change that otherwise looks cosmetic.
    """
    return union_all(
        _branch(
            IdempotencyRecord,
            RecordSource.HOT,
            cast(null(), DateTime(timezone=True)).label("archived_at"),
            hot_criteria,
        ),
        _branch(
            IdempotencyArchive,
            RecordSource.ARCHIVE,
            IdempotencyArchive.archived_at.label("archived_at"),
            archive_criteria,
        ),
    ).subquery("idempotency_records")


class IdempotencyAuditRepository:
    """Read-only access to the registry across hot and archived storage.

    Holds a session and nothing else. Every method reads; none commits. The
    session is expected to come from one of the read-only dependencies, which
    is what makes that a property of the process rather than a convention.
    """

    def __init__(self, db: AsyncSession | Session) -> None:
        self._db = db

    async def _execute(self, stmt: Any) -> Any:
        """Run a statement on either session flavour.

        The same branch ``get_record`` and ``list_records_by_scopes`` already
        carry. Production always passes an ``AsyncSession``; accepting a plain
        one lets read-only tests avoid opening an asyncpg connection, which on
        Windows and CI is what turns a never-committed SELECT into a
        "Event loop is closed" teardown error rather than a passing test.
        """
        if isinstance(self._db, AsyncSession):
            return await self._db.execute(stmt)
        return self._db.execute(stmt)

    async def get_by_key(self, key_value: str, scope_id: str) -> AuditRecord | None:
        """The most recent record registered under this key and scope.

        A key can hold more than one record over time: an expired generation
        stays in the hot table beside its successor, and older generations may
        already have been archived. The most recent registration is the one an
        investigation is asking about, so that is what this returns — ordered by
        ``first_seen_at`` with ``id`` breaking ties, because two registrations
        can share a timestamp and an ambiguous order would make the answer
        depend on the plan.
        """
        records = _union(
            [IdempotencyRecord.key_value == key_value, IdempotencyRecord.scope_id == scope_id],
            [IdempotencyArchive.key_value == key_value, IdempotencyArchive.scope_id == scope_id],
        )
        stmt = (
            select(records)
            .order_by(records.c.first_seen_at.desc(), records.c.id.desc())
            .limit(1)
        )
        row = (await self._execute(stmt)).first()
        return _row_to_record(row) if row is not None else None

    async def list_key_generations(
        self,
        key_value: str,
        scope_id: str,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> AuditRecordPage:
        """Every generation of this key and scope, oldest first.

        ``get_by_key`` answers "what is this key now"; this answers "what has
        this key ever been", which is the question a duplicate investigation
        actually asks once the current record turns out to look innocent.
        """
        return await self._paginate(
            hot_criteria=[
                IdempotencyRecord.key_value == key_value,
                IdempotencyRecord.scope_id == scope_id,
            ],
            archive_criteria=[
                IdempotencyArchive.key_value == key_value,
                IdempotencyArchive.scope_id == scope_id,
            ],
            limit=limit,
            offset=offset,
        )

    async def list_by_key_values(
        self,
        key_values: list[str],
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> AuditRecordPage:
        """Every record registered under any of these keys, in any scope, oldest first.

        This is the registry half of the reverse lookup: a resolver turns a
        ledger transaction or a settlement into the keys that guarded it, and
        this turns those keys into records.

        Deliberately not scoped. ``get_by_key`` needs a scope because
        (key_value, scope_id) is what the registry is unique on, but a caller
        holding only a transaction id has no scope to offer — and the answer it
        wants is precisely "everywhere this key was used", since the same key
        appearing under two scopes is the shape a duplicate investigation is
        looking for. The result is therefore one-to-many by construction and is
        returned as a page rather than collapsed to a single record.
        """
        return await self.list_for_reference(
            scope_ids=[], key_values=key_values, limit=limit, offset=offset
        )

    async def list_for_reference(
        self,
        *,
        scope_ids: list[str],
        key_values: list[str],
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> AuditRecordPage:
        """Records matching any of these scopes OR any of these keys, oldest first.

        One settlement's records are not all reachable the same way — rail
        references and internal derived keys sit under derivable scopes, while
        the customer key sits under an HTTP route template that names no
        settlement and is reachable only by its value. Both halves have to be
        matched in one statement rather than in two queries whose pages are then
        merged: merging pages is correct for the first page and wrong for every
        one after it, because each side would skip a different number of rows.
        """
        if not scope_ids and not key_values:
            return AuditRecordPage(total=0, limit=limit, offset=offset, records=[])

        def criteria(model: type[IdempotencyRecord] | type[IdempotencyArchive]) -> list:
            reachable = []
            if scope_ids:
                reachable.append(model.scope_id.in_(scope_ids))
            if key_values:
                reachable.append(model.key_value.in_(key_values))
            built: list = [or_(*reachable)]
            if since is not None:
                built.append(model.first_seen_at >= since)
            if until is not None:
                built.append(model.first_seen_at <= until)
            return built

        return await self._paginate(
            hot_criteria=criteria(IdempotencyRecord),
            archive_criteria=criteria(IdempotencyArchive),
            limit=limit,
            offset=offset,
        )

    async def list_by_scope(
        self,
        scope_ids: list[str],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> AuditRecordPage:
        """Every record in these scopes, oldest first, optionally date-bounded.

        Takes a list because a settlement does not have one scope. Rail
        references are scoped per leg and customer keys per route, so
        reconstructing what happened during a settlement means asking about a
        family of scopes at once — resolving that family is the caller's job,
        and doing it in one query rather than one per scope is this method's.

        An empty ``scope_ids`` returns an empty page rather than every record in
        the registry, which is what an unguarded ``IN ()`` would eventually
        become the day a caller passes a list it did not check.
        """
        return await self.list_for_reference(
            scope_ids=scope_ids,
            key_values=[],
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    async def _paginate(
        self,
        *,
        hot_criteria: list,
        archive_criteria: list,
        limit: int,
        offset: int,
    ) -> AuditRecordPage:
        """One page of the union, oldest first, plus the unpaged total.

        Ordering and pagination are applied to the union rather than to either
        branch. Paging each table separately and merging afterwards would give
        the right rows only for the first page — every later offset would skip a
        different number of rows on each side.
        """
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        offset = max(0, offset)

        records = _union(hot_criteria, archive_criteria)
        page = (
            select(records)
            .order_by(records.c.first_seen_at.asc(), records.c.id.asc())
            .limit(limit)
            .offset(offset)
        )
        counted = select(func.count()).select_from(_union(hot_criteria, archive_criteria))

        rows = (await self._execute(page)).all()
        total = (await self._execute(counted)).scalar_one()
        return AuditRecordPage(
            total=total,
            limit=limit,
            offset=offset,
            records=[_row_to_record(r) for r in rows],
        )
