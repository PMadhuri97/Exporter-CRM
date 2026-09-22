"""S3T1 acceptance: the full key-expiry lifecycle, end to end.

The phase suites each pin one mechanism — configuration, registration, the partial index,
the sweep. This one walks the whole chain in a single test so the seams between them are
exercised rather than assumed:

    register CK → first_seen_at → configured expires_at → window closes
    → scheduled sweep → EXPIRED → same key + scope registered again
    → NEW record → old record preserved

Also here: the concurrency properties that only mean something with real, separate database
connections, and one assertion per numbered acceptance criterion so the ticket can be
checked off against something executable.
"""

import asyncio
import concurrent.futures
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.platform.configuration.config import settings
from app.platform.idempotency import (
    IdempotencyExpiryService,
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
    RegistrationResultType,
    complete_key_sync,
    derive_internal_key,
    expiry_window_for,
    generate_rail_reference,
    get_sweep_interval,
    register_key_sync,
    reset_key_expiry_windows_cache,
)
from app.platform.idempotency.config import CONFIG_DIR, KEY_EXPIRY_FILENAME

OPERATION = "s3t1_acceptance"


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    factory = sessionmaker(bind=sync_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(
            IdempotencyRecord.__table__.delete().where(
                IdempotencyRecord.operation_type == OPERATION
            )
        )
        session.commit()
        session.close()


@pytest.fixture(autouse=True)
def _clear_config_cache():
    reset_key_expiry_windows_cache()
    yield
    reset_key_expiry_windows_cache()


def _register(session, key_value, scope_id, key_type="customer_key"):
    result = register_key_sync(
        session=session,
        key_value=key_value,
        key_type=key_type,
        scope_id=scope_id,
        operation_type=OPERATION,
    )
    session.commit()
    return result


def _rows(session, key_value, scope_id):
    session.expire_all()
    return list(
        session.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.key_value == key_value,
                IdempotencyRecord.scope_id == scope_id,
            )
            .order_by(IdempotencyRecord.first_seen_at)
        ).scalars()
    )


def _force_window_closed(session, record_id):
    """Move a record's window into the past.

    The alternative is waiting 24 hours. What is under test is the sweep's reaction to a
    closed window, not the clock, so the window is closed directly and expires_at keeps the
    shape registration gave it — derived from first_seen_at, just further back.

    The new value is computed by Postgres, not by Python. The sweep's eligibility
    predicate evaluates `expires_at <= now()` server-side by design, so a host-derived
    timestamp stops matching it the moment the client and the database disagree about
    the time -- which a containerised database on a developer machine does routinely,
    and silently.
    """
    session.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.id == record_id)
        .values(expires_at=func.now() - timedelta(seconds=1))
    )
    session.commit()


async def _sweep(session):
    return await IdempotencyExpiryService(session).run_expiry_sweep()


# ── The full lifecycle ────────────────────────────────────────────────────────────────


async def test_full_customer_key_lifecycle(db_session):
    """Registration through expiry to reuse, in one pass, asserting every hand-off."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    window = expiry_window_for(IdempotencyKeyType.CUSTOMER_KEY)

    # 1. Register. The window opens at first_seen_at.
    first = _register(db_session, key, scope)
    assert first.result == RegistrationResultType.NEW

    original = _rows(db_session, key, scope)[0]
    assert original.status == IdempotencyStatus.ACTIVE
    assert original.expires_at == original.first_seen_at + window

    # 2. While live, the key is claimed — whatever its terminal status.
    assert _register(db_session, key, scope).result == RegistrationResultType.DUPLICATE

    complete_key_sync(
        session=db_session, key_value=key, scope_id=scope, terminal_status="completed"
    )
    db_session.commit()
    assert _register(db_session, key, scope).result == RegistrationResultType.DUPLICATE

    # 3. The window closes. Nothing happens until the sweep notices.
    _force_window_closed(db_session, original.id)
    assert _rows(db_session, key, scope)[0].status == IdempotencyStatus.COMPLETED

    # 4. The sweep expires it.
    result = await _sweep(db_session)
    db_session.commit()
    assert result.ran
    assert _rows(db_session, key, scope)[0].status == IdempotencyStatus.EXPIRED

    snapshot = _rows(db_session, key, scope)[0]
    preserved = {
        "id": snapshot.id,
        "key_value": snapshot.key_value,
        "scope_id": snapshot.scope_id,
        "first_seen_at": snapshot.first_seen_at,
        "expires_at": snapshot.expires_at,
        "completed_at": snapshot.completed_at,
    }

    # 5. The same key and scope registers again — as a NEW record.
    second = _register(db_session, key, scope)
    assert second.result == RegistrationResultType.NEW
    assert second.record.id != original.id

    # 6. Old record untouched; new one carries its own fresh window.
    rows = _rows(db_session, key, scope)
    assert len(rows) == 2

    old = next(r for r in rows if r.id == original.id)
    new = next(r for r in rows if r.id == second.record.id)

    assert {k: getattr(old, k) for k in preserved} == preserved
    assert old.status == IdempotencyStatus.EXPIRED
    assert new.status == IdempotencyStatus.ACTIVE
    assert new.expires_at == new.first_seen_at + window
    assert new.first_seen_at > old.first_seen_at

    # 7. The new record now claims the key, exactly as the first one did.
    assert _register(db_session, key, scope).result == RegistrationResultType.DUPLICATE
    assert len(_rows(db_session, key, scope)) == 2


async def test_multiple_expiry_and_reuse_generations_accumulate(db_session):
    """The lifecycle repeats: history grows, exactly one record is live at a time."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    generations = []

    for _ in range(3):
        result = _register(db_session, key, scope)
        assert result.result == RegistrationResultType.NEW
        generations.append(result.record.id)

        complete_key_sync(
            session=db_session, key_value=key, scope_id=scope, terminal_status="completed"
        )
        db_session.commit()
        _force_window_closed(db_session, result.record.id)
        await _sweep(db_session)
        db_session.commit()

    live = _register(db_session, key, scope)
    rows = _rows(db_session, key, scope)

    assert len(rows) == 4
    assert sum(r.status == IdempotencyStatus.EXPIRED for r in rows) == 3
    assert {r.id for r in rows if r.status == IdempotencyStatus.EXPIRED} == set(generations)
    assert [r.id for r in rows if r.status == IdempotencyStatus.ACTIVE] == [live.record.id]


async def test_idk_and_rr_survive_the_lifecycle_untouched(db_session):
    """The same flow that expires a CK must leave IDK and RR alone throughout."""
    idk = derive_internal_key(str(uuid.uuid4()), "settle_leg")
    rr = generate_rail_reference(str(uuid.uuid4()), 1, "SWIFT")
    ck = str(uuid.uuid4())
    scope = str(uuid.uuid4())

    idk_result = _register(db_session, idk, scope, key_type="internal_derived_key")
    rr_result = _register(db_session, rr, scope, key_type="rail_reference")
    ck_result = _register(db_session, ck, scope)

    for result in (idk_result, rr_result, ck_result):
        complete_key_sync(
            session=db_session,
            key_value=result.record.key_value,
            scope_id=scope,
            terminal_status="completed",
        )
    db_session.commit()

    # Force a past window onto ALL THREE — including the two that should never have one.
    for result in (idk_result, rr_result, ck_result):
        _force_window_closed(db_session, result.record.id)

    await _sweep(db_session)
    db_session.commit()

    db_session.expire_all()
    statuses = {
        result.record.id: db_session.execute(
            select(IdempotencyRecord.status).where(
                IdempotencyRecord.id == result.record.id
            )
        ).scalar_one()
        for result in (idk_result, rr_result, ck_result)
    }

    assert statuses[ck_result.record.id] == IdempotencyStatus.EXPIRED
    assert statuses[idk_result.record.id] == IdempotencyStatus.COMPLETED
    assert statuses[rr_result.record.id] == IdempotencyStatus.COMPLETED


# ── Concurrency, with real separate connections ───────────────────────────────────────


def _sweep_in_thread(url: str) -> int:
    """One sweep on its own connection and transaction. Returns rows it expired."""
    engine = create_engine(url, poolclass=None)
    try:
        with Session(engine) as session:
            result = asyncio.run(IdempotencyExpiryService(session).run_expiry_sweep())
            session.commit()
            return result.expired_count
    finally:
        engine.dispose()


async def test_concurrent_sweeps_expire_each_record_exactly_once(db_session, sync_engine):
    """Eight simultaneous sweeps must not double-count or miss a record.

    This is the property that matters under multiple replicas: whatever interleaving the
    advisory lock produces, the total expired across all sweeps equals the number of
    eligible records — never more (a record counted twice), never fewer (one dropped).
    """
    eligible = 12
    for _ in range(eligible):
        key, scope = str(uuid.uuid4()), str(uuid.uuid4())
        result = _register(db_session, key, scope)
        complete_key_sync(
            session=db_session,
            key_value=key,
            scope_id=scope,
            terminal_status="completed",
        )
        db_session.commit()
        _force_window_closed(db_session, result.record.id)

    url = str(sync_engine.url.render_as_string(hide_password=False))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda _: _sweep_in_thread(url), range(8)))

    assert sum(counts) == eligible, (
        f"expected each of {eligible} records expired exactly once, sweeps reported {counts}"
    )

    db_session.expire_all()
    remaining = db_session.execute(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.operation_type == OPERATION,
            IdempotencyRecord.status.in_(
                [IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED]
            ),
            IdempotencyRecord.expires_at <= func.now(),
        )
    ).scalars().all()
    assert remaining == [], "every eligible record should have been expired"


def _register_in_thread(url: str, key_value: str, scope_id: str) -> str:
    engine = create_engine(url, poolclass=None)
    try:
        with Session(engine) as session:
            result = register_key_sync(
                session=session,
                key_value=key_value,
                key_type="customer_key",
                scope_id=scope_id,
                operation_type=OPERATION,
            )
            session.commit()
            return result.registration_result
    finally:
        engine.dispose()


async def test_concurrent_reuse_after_expiry_creates_exactly_one_new_record(
    db_session, sync_engine
):
    """Ten threads racing to reuse an expired key produce one winner, not ten records.

    The partial unique index is what enforces this: it excludes the expired predecessor but
    still covers the live row the winning thread inserts.
    """
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    complete_key_sync(
        session=db_session, key_value=key, scope_id=scope, terminal_status="completed"
    )
    db_session.commit()
    _force_window_closed(db_session, first.record.id)
    await _sweep(db_session)
    db_session.commit()

    url = str(sync_engine.url.render_as_string(hide_password=False))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(lambda _: _register_in_thread(url, key, scope), range(10)))

    assert outcomes.count("new") == 1, f"expected exactly one winner, got {outcomes}"
    assert outcomes.count("duplicate") == 9

    rows = _rows(db_session, key, scope)
    assert len(rows) == 2
    assert sum(r.status == IdempotencyStatus.EXPIRED for r in rows) == 1
    assert sum(r.status == IdempotencyStatus.ACTIVE for r in rows) == 1


def test_concurrent_first_registration_is_still_exclusive(db_session, sync_engine):
    """The S1T1 guarantee, re-checked after the uniqueness model changed under it."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())
    url = str(sync_engine.url.render_as_string(hide_password=False))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(lambda _: _register_in_thread(url, key, scope), range(10)))

    assert outcomes.count("new") == 1
    assert len(_rows(db_session, key, scope)) == 1


# ── Acceptance criteria, one assertion each ───────────────────────────────────────────


async def test_ac1_registration_sets_expires_at_from_first_seen_at(db_session):
    """AC1 — CK registered at T gets expires_at = T + configured window."""
    result = _register(db_session, str(uuid.uuid4()), str(uuid.uuid4()))
    record = _rows(db_session, result.record.key_value, result.record.scope_id)[0]

    assert record.expires_at == record.first_seen_at + expiry_window_for(
        IdempotencyKeyType.CUSTOMER_KEY
    )


def test_ac2_default_configured_window_is_24_hours():
    """AC2 — read from the deployed file, not restated in the assertion."""
    import yaml

    document = yaml.safe_load(
        (CONFIG_DIR / KEY_EXPIRY_FILENAME).read_text(encoding="utf-8")
    )
    assert document["key_expiry"]["customer_key_seconds"] == 86400
    assert expiry_window_for(IdempotencyKeyType.CUSTOMER_KEY) == timedelta(hours=24)


def test_ac3_sweep_cadence_is_five_minutes():
    """AC3 — the configured cadence the lifespan registers the job with."""
    assert get_sweep_interval() == timedelta(minutes=5)


async def test_ac4_eligible_terminal_customer_keys_become_expired(db_session):
    """AC4 — completed and failed both, past window only."""
    outcomes = {}
    for status in ("completed", "failed"):
        key, scope = str(uuid.uuid4()), str(uuid.uuid4())
        result = _register(db_session, key, scope)
        complete_key_sync(
            session=db_session, key_value=key, scope_id=scope, terminal_status=status
        )
        db_session.commit()
        _force_window_closed(db_session, result.record.id)
        outcomes[status] = (key, scope)

    await _sweep(db_session)
    db_session.commit()

    for key, scope in outcomes.values():
        assert _rows(db_session, key, scope)[0].status == IdempotencyStatus.EXPIRED


async def test_ac5_6_7_reuse_creates_new_record_and_preserves_the_old(db_session):
    """AC5, AC6 and AC7 — they are one behaviour and are asserted together."""
    key, scope = str(uuid.uuid4()), str(uuid.uuid4())

    first = _register(db_session, key, scope)
    complete_key_sync(
        session=db_session, key_value=key, scope_id=scope, terminal_status="completed"
    )
    db_session.commit()
    _force_window_closed(db_session, first.record.id)
    await _sweep(db_session)
    db_session.commit()

    before = _rows(db_session, key, scope)[0]
    frozen = (before.id, before.first_seen_at, before.expires_at, before.status)

    second = _register(db_session, key, scope)  # AC5: reuse permitted

    assert second.result == RegistrationResultType.NEW
    assert second.record.id != first.record.id  # AC6: new record

    old = next(r for r in _rows(db_session, key, scope) if r.id == first.record.id)
    assert (old.id, old.first_seen_at, old.expires_at, old.status) == frozen  # AC7


async def test_ac8_window_is_configurable(db_session, tmp_path, monkeypatch):
    """AC8 — a different file yields a different window, with no code change."""
    (tmp_path / KEY_EXPIRY_FILENAME).write_text(
        "key_expiry:\n"
        "  customer_key_seconds: 5400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n"
        "sweep_interval_seconds: 300\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "IDEMPOTENCY_CONFIG_DIR", str(tmp_path))
    reset_key_expiry_windows_cache()

    result = _register(db_session, str(uuid.uuid4()), str(uuid.uuid4()))
    record = _rows(db_session, result.record.key_value, result.record.scope_id)[0]

    assert record.expires_at - record.first_seen_at == timedelta(minutes=90)


def test_ac9_no_hardcoded_expiry_in_s3t1_code():
    """AC9 — delegates to the tokenizer-based scan, so this is a pointer not a duplicate."""
    from app.platform.idempotency.tests.test_expiry_configuration import (
        test_config_module_declares_no_default_window,
        test_no_literal_duration_in_capability_code,
        test_no_magic_second_counts_in_capability_code,
        test_registration_service_never_names_a_duration,
    )

    test_no_literal_duration_in_capability_code()
    test_no_magic_second_counts_in_capability_code()
    test_registration_service_never_names_a_duration()
    test_config_module_declares_no_default_window()


async def test_ac10_idk_and_rr_are_never_time_expired(db_session):
    """AC10 — with a past window forced on, which registration would never produce."""
    scope = str(uuid.uuid4())
    cases = {
        "internal_derived_key": derive_internal_key(str(uuid.uuid4()), "fund"),
        "rail_reference": generate_rail_reference(str(uuid.uuid4()), 3, "ACH"),
    }

    seeded = {}
    for key_type, key_value in cases.items():
        result = _register(db_session, key_value, scope, key_type=key_type)
        complete_key_sync(
            session=db_session,
            key_value=key_value,
            scope_id=scope,
            terminal_status="completed",
        )
        db_session.commit()
        _force_window_closed(db_session, result.record.id)
        seeded[key_type] = result.record.id

    await _sweep(db_session)
    db_session.commit()

    db_session.expire_all()
    for key_type, record_id in seeded.items():
        status = db_session.execute(
            select(IdempotencyRecord.status).where(IdempotencyRecord.id == record_id)
        ).scalar_one()
        assert status == IdempotencyStatus.COMPLETED, f"{key_type} was time-expired"


def test_expired_status_is_only_ever_written_by_the_sweep():
    """Nothing outside expiry.py may SET status='expired' — reuse depends on that.

    Parsed rather than grepped: services.py legitimately mentions IdempotencyStatus.EXPIRED
    in filters (`status != EXPIRED`) and in an ORDER BY, and a substring scan cannot tell a
    predicate from an assignment. What is forbidden is specifically a .values() call
    assigning that status.
    """
    import ast
    import pathlib

    capability = pathlib.Path(__file__).resolve().parents[1]
    offenders = []

    for path in capability.rglob("*.py"):
        if {"tests", "migrations", "__pycache__"} & set(path.parts):
            continue
        if path.name == "expiry.py":
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "values"):
                continue
            for keyword in node.keywords:
                if keyword.arg != "status":
                    continue
                assigned = ast.unparse(keyword.value)
                if "EXPIRED" in assigned:
                    offenders.append(f"{path.name}: values(status={assigned})")

    assert not offenders, (
        f"{offenders} assign the expired status; the sweep must be its only writer"
    )
