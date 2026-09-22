"""IdempotencyAuditQueryService composes the registry with each module's resolver.

Two kinds of case here. The structural ones need no database and assert what the
service is *not* — no session, no write collaborator, no import of anything that
writes — because BUILD.md #10 makes that a property to prove rather than to
intend. The behavioural ones run against PostgreSQL with real resolvers, since
the thing worth testing is that the halves fit: a settlement's records are
reachable partly by scope and partly by key, and a service that resolved only
one would look correct while under-reporting.

The resolvers are fakes only where the case is about the service's own logic
(what it does with an empty resolution, how it paginates). Where the case is
about the composition being right, the real adapters are used — a fake that
returns the scopes the service expects would prove nothing about whether the
settlement module produces them.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency.archive_models import IdempotencyArchive
from app.platform.idempotency.audit_repository import (
    IdempotencyAuditRepository,
    RecordSource,
)
from app.platform.idempotency.audit_service import IdempotencyAuditQueryService
from app.platform.idempotency.detection_repository import DuplicateDetectionRepository
from app.platform.idempotency.exceptions import IdempotencyKeyNotFoundError
from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)
from app.shared.contracts.idempotency import ViolationPage

NOW = datetime.now(UTC)


class _StubResolver:
    """Returns whatever it was constructed with, and records what it was asked."""

    def __init__(self, *, keys: list[str] | None = None, scopes: list[str] | None = None):
        self._keys = keys or []
        self._scopes = scopes or []
        self.asked: list[uuid.UUID] = []

    async def idempotency_keys_for(self, reference_id: uuid.UUID) -> list[str]:
        self.asked.append(reference_id)
        return self._keys

    async def scope_ids_for(self, reference_id: uuid.UUID) -> list[str]:
        self.asked.append(reference_id)
        return self._scopes


class _StubViolations:
    """Records the paging it was asked for; returns an empty page."""

    def __init__(self) -> None:
        self.asked: list[tuple[int, int]] = []

    async def list_violations(self, *, limit: int, offset: int) -> ViolationPage:
        self.asked.append((limit, offset))
        return ViolationPage(total=0, limit=limit, offset=offset, violations=[])


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
    ids: list[uuid.UUID] = []

    def _seed(
        *,
        key_value: str,
        scope_id: str,
        archived: bool = False,
        first_seen_at: datetime | None = None,
        response_cache: dict | None = None,
    ):
        record_id = uuid.uuid4()
        common = {
            "id": record_id,
            "key_value": key_value,
            "scope_id": scope_id,
            "key_type": IdempotencyKeyType.CUSTOMER_KEY,
            "operation_type": "test_audit_service",
            "status": IdempotencyStatus.COMPLETED,
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


def _service(db_session, *, settlements=None, ledger_transactions=None, violations=None):
    return IdempotencyAuditQueryService(
        IdempotencyAuditRepository(db_session),
        settlements=settlements or _StubResolver(),
        ledger_transactions=ledger_transactions or _StubResolver(),
        detections=DuplicateDetectionRepository(db_session),
        violations=violations or _StubViolations(),
    )


# ── Structural: the service cannot write ──────────────────────────────────────


def test_service_holds_no_session_of_its_own() -> None:
    """Sessions arrive inside collaborators, from the read-only dependencies.

    A service that opened its own would choose its own credentials, and the
    guarantee BUILD.md #10 asks for would depend on it choosing correctly every
    time rather than on it having no choice.
    """
    source = inspect.getsource(IdempotencyAuditQueryService)
    for forbidden in ("AsyncSessionLocal", "create_async_engine", "get_db("):
        assert forbidden not in source, (
            f"IdempotencyAuditQueryService references {forbidden}, so it can reach a "
            f"writable session"
        )


def test_service_calls_nothing_that_writes() -> None:
    """No commit, flush, add or delete anywhere in the class body."""
    source = inspect.getsource(IdempotencyAuditQueryService)
    for verb in (".commit(", ".flush(", ".add(", ".delete(", ".merge("):
        assert verb not in source, f"IdempotencyAuditQueryService calls {verb}"


def test_every_public_operation_is_a_query() -> None:
    """A write method added later should fail a test, not pass review.

    Names are the check because they are the contract: BUILD.md's convention is
    get_* for one and list_* for many, and neither can be mistaken for a verb
    that changes something.
    """
    public = [
        name
        for name, _ in inspect.getmembers(IdempotencyAuditQueryService, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert public, "the service exposes no operations at all"
    assert all(name.startswith(("get_", "list_")) for name in public), (
        f"non-query operation on a read-only service: {public}"
    )


def test_paginated_operations_return_a_page() -> None:
    """BUILD.md #10: every list operation is paginated."""
    for name in (
        "list_settlement_records",
        "list_ledger_transaction_records",
        "list_duplicate_detections",
        "list_violations",
    ):
        signature = inspect.signature(getattr(IdempotencyAuditQueryService, name))
        assert "limit" in signature.parameters, f"{name} has no limit"
        assert "offset" in signature.parameters, f"{name} has no offset"


# ── get_record ────────────────────────────────────────────────────────────────


async def test_get_record_returns_the_record_with_its_response_cache(
    db_session, seeded
) -> None:
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    payload = {"status": 201, "body": {"settlement_id": "abc"}}
    seeded(key_value=key, scope_id=scope, response_cache=payload)
    db_session.commit()

    record = await _service(db_session).get_record(key, scope)

    assert record.response_cache == payload


async def test_get_record_reaches_the_archive(db_session, seeded) -> None:
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    seeded(key_value=key, scope_id=scope, archived=True)
    db_session.commit()

    record = await _service(db_session).get_record(key, scope)

    assert record.source is RecordSource.ARCHIVE


async def test_get_record_raises_for_an_unknown_key(db_session) -> None:
    """"No such key" and "a key with an empty record" are different outcomes."""
    with pytest.raises(IdempotencyKeyNotFoundError):
        await _service(db_session).get_record(str(uuid.uuid4()), str(uuid.uuid4()))


# ── list_settlement_records ───────────────────────────────────────────────────


async def test_settlement_records_combine_scope_reachable_and_key_reachable(
    db_session, seeded
) -> None:
    """The case the whole two-resolver design exists for.

    One record is findable only by scope, the other only by key. Resolving
    either half alone returns one record and looks entirely plausible.
    """
    settlement_id = uuid.uuid4()
    scope = str(settlement_id)
    customer_key = str(uuid.uuid4())
    by_scope = seeded(key_value=str(uuid.uuid4()), scope_id=scope)
    by_key = seeded(key_value=customer_key, scope_id="POST /api/v1/settlements")
    db_session.commit()

    service = _service(
        db_session,
        settlements=_StubResolver(keys=[customer_key], scopes=[scope]),
    )
    page = await service.list_settlement_records(settlement_id)

    assert page.total == 2
    assert {r.id for r in page.records} == {by_scope.id, by_key.id}


async def test_settlement_records_are_chronological_across_both_tables(
    db_session, seeded
) -> None:
    settlement_id = uuid.uuid4()
    scope = str(settlement_id)
    older = seeded(
        key_value=str(uuid.uuid4()),
        scope_id=scope,
        archived=True,
        first_seen_at=NOW - timedelta(days=3),
    )
    newer = seeded(
        key_value=str(uuid.uuid4()), scope_id=scope, first_seen_at=NOW - timedelta(days=1)
    )
    db_session.commit()

    service = _service(db_session, settlements=_StubResolver(scopes=[scope]))
    page = await service.list_settlement_records(settlement_id)

    assert [r.id for r in page.records] == [older.id, newer.id]


async def test_settlement_records_honour_the_date_bound(db_session, seeded) -> None:
    settlement_id = uuid.uuid4()
    scope = str(settlement_id)
    seeded(key_value=str(uuid.uuid4()), scope_id=scope, first_seen_at=NOW - timedelta(days=90))
    inside = seeded(
        key_value=str(uuid.uuid4()), scope_id=scope, first_seen_at=NOW - timedelta(days=1)
    )
    db_session.commit()

    service = _service(db_session, settlements=_StubResolver(scopes=[scope]))
    page = await service.list_settlement_records(
        settlement_id, since=NOW - timedelta(days=7), until=NOW
    )

    assert [r.id for r in page.records] == [inside.id]


async def test_a_settlement_that_resolves_to_nothing_returns_an_empty_page(
    db_session, seeded
) -> None:
    """An unresolvable reference must not fall through to matching everything."""
    seeded(key_value=str(uuid.uuid4()), scope_id=str(uuid.uuid4()))
    db_session.commit()

    service = _service(db_session, settlements=_StubResolver(keys=[], scopes=[]))
    page = await service.list_settlement_records(uuid.uuid4())

    assert page.total == 0
    assert page.records == []


async def test_settlement_records_are_paginated(db_session, seeded) -> None:
    settlement_id = uuid.uuid4()
    scope = str(settlement_id)
    for day in range(4):
        seeded(
            key_value=str(uuid.uuid4()),
            scope_id=scope,
            archived=day % 2 == 0,
            first_seen_at=NOW - timedelta(days=10 - day),
        )
    db_session.commit()

    service = _service(db_session, settlements=_StubResolver(scopes=[scope]))
    first = await service.list_settlement_records(settlement_id, limit=2, offset=0)
    second = await service.list_settlement_records(settlement_id, limit=2, offset=2)

    assert first.total == second.total == 4
    assert {r.id for r in first.records}.isdisjoint({r.id for r in second.records})


# ── list_ledger_transaction_records ───────────────────────────────────────────


async def test_ledger_transaction_records_are_found_by_the_resolved_key(
    db_session, seeded
) -> None:
    key = str(uuid.uuid4())
    expected = seeded(key_value=key, scope_id=str(uuid.uuid4()))
    db_session.commit()

    service = _service(db_session, ledger_transactions=_StubResolver(keys=[key]))
    page = await service.list_ledger_transaction_records(uuid.uuid4())

    assert [r.id for r in page.records] == [expected.id]


async def test_a_transaction_with_no_records_returns_an_empty_page(
    db_session, seeded
) -> None:
    """Not every posting registers a key; that is not an error."""
    seeded(key_value=str(uuid.uuid4()), scope_id=str(uuid.uuid4()))
    db_session.commit()

    service = _service(
        db_session, ledger_transactions=_StubResolver(keys=[str(uuid.uuid4())])
    )
    page = await service.list_ledger_transaction_records(uuid.uuid4())

    assert page.total == 0


async def test_the_transaction_id_is_what_reaches_the_resolver(db_session) -> None:
    """Guards against the service resolving something other than what it was asked."""
    resolver = _StubResolver(keys=[])
    transaction_id = uuid.uuid4()

    await _service(db_session, ledger_transactions=resolver).list_ledger_transaction_records(
        transaction_id
    )

    assert resolver.asked == [transaction_id]


# ── list_violations ───────────────────────────────────────────────────────────


async def test_violations_are_read_from_the_violation_source(db_session) -> None:
    """Not from the detection repository — the two are inverse events."""
    violations = _StubViolations()

    page = await _service(db_session, violations=violations).list_violations(
        limit=25, offset=50
    )

    assert violations.asked == [(25, 50)]
    assert page.violations == []


@pytest.mark.parametrize(
    ("limit", "offset", "expected"),
    ((10_000, 0, (500, 0)), (0, -3, (1, 0))),
    ids=("oversized", "nonsense"),
)
async def test_violation_paging_is_clamped_before_the_adapter(
    db_session, limit: int, offset: int, expected: tuple[int, int]
) -> None:
    """The adapter lives in another module and should not have to know the ceiling."""
    violations = _StubViolations()

    await _service(db_session, violations=violations).list_violations(
        limit=limit, offset=offset
    )

    assert violations.asked == [expected]
