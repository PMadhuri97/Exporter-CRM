"""The audit repository reads hot and archived records as one collection.

The property under test throughout is that a caller cannot tell which table
answered except by reading ``source``. Every case therefore seeds both tables
and asserts on the merged result — a test that only ever seeds the hot table
would pass against a repository that ignored the archive entirely.

Ordering and pagination get their own cases because they are where a two-table
union goes wrong quietly: merging per-table pages gives the right answer for the
first page and a different wrong answer for every page after it.

Cleanup drops seeded rows from both tables, briefly disabling the archive's
DELETE-blocking trigger the way ``test_archival_service`` does. Keys and scopes
are unique per test regardless, so a crashed run leaves nothing another test can
collide with.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency.archive_models import IdempotencyArchive
from app.platform.idempotency.audit_repository import (
    MAX_PAGE_SIZE,
    IdempotencyAuditRepository,
    RecordSource,
)
from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)

NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    session = sessionmaker(bind=sync_engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def seeded(db_session):
    """Seeds rows and removes them afterwards, whichever table they landed in."""
    ids: list[uuid.UUID] = []

    def _seed(
        *,
        archived: bool,
        scope_id: str,
        key_value: str | None = None,
        first_seen_at: datetime | None = None,
        operation_type: str = "test_audit_repository",
        status: IdempotencyStatus = IdempotencyStatus.COMPLETED,
        key_type: IdempotencyKeyType = IdempotencyKeyType.CUSTOMER_KEY,
        response_cache: dict | None = None,
    ):
        record_id = uuid.uuid4()
        common = {
            "id": record_id,
            "key_value": key_value or str(uuid.uuid4()),
            "scope_id": scope_id,
            "key_type": key_type,
            "operation_type": operation_type,
            "status": status,
            "response_cache": response_cache,
            "first_seen_at": first_seen_at or NOW,
            "completed_at": first_seen_at or NOW,
        }
        row = (
            IdempotencyArchive(**common, archived_at=NOW)
            if archived
            else IdempotencyRecord(**common)
        )
        db_session.add(row)
        db_session.flush()
        ids.append(record_id)
        return row

    yield _seed

    db_session.rollback()
    db_session.execute(
        text(
            "ALTER TABLE ledger.idempotency_archive "
            "DISABLE TRIGGER trigger_idempotency_archive_no_delete"
        )
    )
    for record_id in ids:
        db_session.execute(
            text("DELETE FROM ledger.idempotency_archive WHERE id = :id"), {"id": str(record_id)}
        )
        db_session.execute(
            text("DELETE FROM ledger.idempotency_record WHERE id = :id"), {"id": str(record_id)}
        )
    db_session.execute(
        text(
            "ALTER TABLE ledger.idempotency_archive "
            "ENABLE TRIGGER trigger_idempotency_archive_no_delete"
        )
    )
    db_session.commit()


# ── get_by_key ────────────────────────────────────────────────────────────────


async def test_get_by_key_returns_a_hot_record_with_its_response_cache(
    db_session, seeded
) -> None:
    """The cached response is the whole point of the lookup, so it must survive the union."""
    scope = str(uuid.uuid4())
    key = str(uuid.uuid4())
    payload = {"status": 201, "body": {"settlement_id": "abc"}}
    seeded(archived=False, scope_id=scope, key_value=key, response_cache=payload)
    db_session.commit()

    found = await IdempotencyAuditRepository(db_session).get_by_key(key, scope)

    assert found is not None
    assert found.response_cache == payload
    assert found.source is RecordSource.HOT
    assert found.archived_at is None


async def test_get_by_key_returns_an_archived_record_when_the_hot_table_has_none(
    db_session, seeded
) -> None:
    """An aged scope has been swept out of the hot table; the query must still answer."""
    scope = str(uuid.uuid4())
    key = str(uuid.uuid4())
    seeded(archived=True, scope_id=scope, key_value=key, response_cache={"status": 200})
    db_session.commit()

    found = await IdempotencyAuditRepository(db_session).get_by_key(key, scope)

    assert found is not None
    assert found.source is RecordSource.ARCHIVE
    assert found.archived_at is not None
    assert found.response_cache == {"status": 200}


async def test_get_by_key_prefers_the_most_recent_generation(
    db_session, seeded
) -> None:
    """A reclaimed key has an archived past and a live present. The present wins."""
    scope = str(uuid.uuid4())
    key = str(uuid.uuid4())
    seeded(
        archived=True,
        scope_id=scope,
        key_value=key,
        first_seen_at=NOW - timedelta(days=200),
        operation_type="old_generation",
    )
    seeded(
        archived=False,
        scope_id=scope,
        key_value=key,
        first_seen_at=NOW,
        operation_type="current_generation",
    )
    db_session.commit()

    found = await IdempotencyAuditRepository(db_session).get_by_key(key, scope)

    assert found is not None
    assert found.operation_type == "current_generation"


async def test_get_by_key_returns_none_for_a_key_that_was_never_registered(
    db_session,
) -> None:
    found = await IdempotencyAuditRepository(db_session).get_by_key(
        str(uuid.uuid4()), str(uuid.uuid4())
    )
    assert found is None


async def test_get_by_key_does_not_match_the_same_key_in_another_scope(
    db_session, seeded
) -> None:
    """Uniqueness is (key_value, scope_id). A key alone identifies nothing."""
    key = str(uuid.uuid4())
    seeded(archived=False, scope_id=str(uuid.uuid4()), key_value=key)
    db_session.commit()

    found = await IdempotencyAuditRepository(db_session).get_by_key(key, str(uuid.uuid4()))
    assert found is None


async def test_list_key_generations_returns_every_generation_oldest_first(
    db_session, seeded
) -> None:
    scope = str(uuid.uuid4())
    key = str(uuid.uuid4())
    seeded(archived=True, scope_id=scope, key_value=key, first_seen_at=NOW - timedelta(days=200))
    seeded(archived=False, scope_id=scope, key_value=key, first_seen_at=NOW)
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_key_generations(key, scope)

    assert page.total == 2
    assert [r.source for r in page.records] == [RecordSource.ARCHIVE, RecordSource.HOT]


# ── list_by_scope ─────────────────────────────────────────────────────────────


async def test_list_by_scope_interleaves_hot_and_archived_records_chronologically(
    db_session, seeded
) -> None:
    """The union must sort as one sequence, not archive-then-hot.

    Seeded so the correct order alternates between the tables — a repository
    that concatenated the two would still return four records, in the wrong
    order, and a laxer assertion would not notice.
    """
    scope = str(uuid.uuid4())
    for offset_days, archived in ((4, True), (3, False), (2, True), (1, False)):
        seeded(
            archived=archived,
            scope_id=scope,
            first_seen_at=NOW - timedelta(days=offset_days),
            operation_type=f"step_{offset_days}",
        )
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_scope([scope])

    assert page.total == 4
    assert [r.operation_type for r in page.records] == [
        "step_4",
        "step_3",
        "step_2",
        "step_1",
    ]
    assert [r.source for r in page.records] == [
        RecordSource.ARCHIVE,
        RecordSource.HOT,
        RecordSource.ARCHIVE,
        RecordSource.HOT,
    ]


async def test_list_by_scope_spans_several_scopes_in_one_query(
    db_session, seeded
) -> None:
    """A settlement's records are spread over a family of scopes, not one."""
    settlement_scope = str(uuid.uuid4())
    leg_scope = str(uuid.uuid4())
    seeded(archived=False, scope_id=settlement_scope, first_seen_at=NOW - timedelta(days=2))
    seeded(archived=True, scope_id=leg_scope, first_seen_at=NOW - timedelta(days=1))
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_scope(
        [settlement_scope, leg_scope]
    )

    assert page.total == 2
    assert {r.scope_id for r in page.records} == {settlement_scope, leg_scope}


async def test_list_by_scope_applies_the_date_range_to_both_tables(
    db_session, seeded
) -> None:
    """A bound honoured on one side only would silently return archived outliers."""
    scope = str(uuid.uuid4())
    seeded(archived=True, scope_id=scope, first_seen_at=NOW - timedelta(days=100))
    seeded(archived=False, scope_id=scope, first_seen_at=NOW - timedelta(days=100))
    inside_archive = seeded(archived=True, scope_id=scope, first_seen_at=NOW - timedelta(days=2))
    inside_hot = seeded(archived=False, scope_id=scope, first_seen_at=NOW - timedelta(days=1))
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_scope(
        [scope], since=NOW - timedelta(days=5), until=NOW
    )

    assert page.total == 2
    assert {r.id for r in page.records} == {inside_archive.id, inside_hot.id}


async def test_list_by_scope_returns_an_empty_page_for_no_scopes(db_session) -> None:
    """An unguarded IN () would eventually mean "every record in the registry"."""
    page = await IdempotencyAuditRepository(db_session).list_by_scope([])
    assert page.total == 0
    assert page.records == []


async def test_list_by_scope_returns_an_empty_page_for_an_unknown_scope(
    db_session,
) -> None:
    page = await IdempotencyAuditRepository(db_session).list_by_scope([str(uuid.uuid4())])
    assert page.total == 0
    assert page.records == []


# ── Pagination ────────────────────────────────────────────────────────────────


async def test_pagination_walks_the_union_without_repeating_or_skipping(
    db_session, seeded
) -> None:
    """Every page together must equal the whole set, exactly once each.

    The failure this guards against is per-table paging: page one would look
    right, and later pages would skip a different number of rows on each side.
    """
    scope = str(uuid.uuid4())
    for day in range(6):
        seeded(
            archived=day % 2 == 0,
            scope_id=scope,
            first_seen_at=NOW - timedelta(days=10 - day),
            operation_type=f"step_{day}",
        )
    db_session.commit()

    repo = IdempotencyAuditRepository(db_session)
    seen: list[str] = []
    for offset in (0, 2, 4):
        page = await repo.list_by_scope([scope], limit=2, offset=offset)
        assert page.total == 6, "total must count every match, not just the page"
        assert page.limit == 2
        assert page.offset == offset
        seen.extend(r.operation_type for r in page.records)

    assert seen == [f"step_{d}" for d in range(6)]


async def test_total_is_independent_of_the_page_size(
    db_session, seeded
) -> None:
    scope = str(uuid.uuid4())
    for day in range(3):
        seeded(archived=day == 0, scope_id=scope, first_seen_at=NOW - timedelta(days=day))
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_scope([scope], limit=1)

    assert page.total == 3
    assert len(page.records) == 1


async def test_page_size_is_capped(db_session, seeded) -> None:
    """An unbounded limit is a caller's way of asking for the whole table."""
    scope = str(uuid.uuid4())
    seeded(archived=False, scope_id=scope)
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_scope(
        [scope], limit=MAX_PAGE_SIZE * 10
    )
    assert page.limit == MAX_PAGE_SIZE


@pytest.mark.parametrize(("limit", "offset"), ((0, 0), (-5, 0), (10, -1)))
async def test_out_of_range_paging_is_clamped_not_rejected(
    db_session, seeded, limit: int, offset: int
) -> None:
    """A nonsense offset should return the first page, never a database error."""
    scope = str(uuid.uuid4())
    seeded(archived=False, scope_id=scope)
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_scope(
        [scope], limit=limit, offset=offset
    )
    assert page.limit >= 1
    assert page.offset >= 0
    assert page.total == 1


# ── list_by_key_values ────────────────────────────────────────────────────────


async def test_list_by_key_values_spans_every_scope_the_key_appears_in(
    db_session, seeded
) -> None:
    """Scope-free by design: the caller has a transaction id, not a scope."""
    key = str(uuid.uuid4())
    seeded(archived=False, scope_id=str(uuid.uuid4()), key_value=key)
    seeded(archived=True, scope_id=str(uuid.uuid4()), key_value=key)
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_key_values([key])

    assert page.total == 2
    assert {r.source for r in page.records} == {RecordSource.HOT, RecordSource.ARCHIVE}


async def test_list_by_key_values_accepts_several_keys(db_session, seeded) -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    seeded(archived=False, scope_id=str(uuid.uuid4()), key_value=first)
    seeded(archived=False, scope_id=str(uuid.uuid4()), key_value=second)
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_key_values([first, second])

    assert {r.key_value for r in page.records} == {first, second}


async def test_list_by_key_values_does_not_match_a_different_key(
    db_session, seeded
) -> None:
    seeded(archived=False, scope_id=str(uuid.uuid4()), key_value=str(uuid.uuid4()))
    db_session.commit()

    page = await IdempotencyAuditRepository(db_session).list_by_key_values([str(uuid.uuid4())])

    assert page.total == 0


async def test_list_by_key_values_returns_an_empty_page_for_no_keys(db_session) -> None:
    """An unresolved reference yields no keys, which must not mean "every record"."""
    page = await IdempotencyAuditRepository(db_session).list_by_key_values([])
    assert page.total == 0
    assert page.records == []
