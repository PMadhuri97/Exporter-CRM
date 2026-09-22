"""Purpose-code registry acceptance criteria against a real database.

Covers the seed loader and the SQLAlchemy repository end to end: YAML on disk →
tables → ``validate_purpose_code``. The decision logic itself is covered branch
by branch in ``tests/unit/test_purpose_code_validation.py`` against an in-memory
repository; what only a database can prove is here — that the loader writes rows
the repository can actually read back, and that effectivity survives the round
trip through Postgres date columns.

## Why this suite restores the seed data

``load_purpose_codes`` truncates both tables and re-inserts. There is no
per-test transaction rollback in this codebase (see backend/conftest.py) — tests
commit against a shared Postgres. Pointing the loader at a tmp_path fixture
therefore *replaces the real GitOps reference data* for the rest of the run, and
every later test or manual query would see RETIRED_CODE and FUTURE_CODE instead
of the real corridors.

The module-scoped fixture below reloads the real GitOps directory on teardown and
asserts the restore worked. Teardown runs even when a test fails, so a broken
assertion cannot strand the fake data either.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.compliance.application.validation import (
    AmbiguousPurposeCodeMappingError,
    PurposeCodeInputError,
    PurposeCodeNotEffectiveError,
    PurposeCodeNotFoundError,
    PurposeCodeNotValidForCorridorError,
    validate_purpose_code,
)
from app.modules.compliance.domain.entities.registry import (
    PurposeCodeCanonical,
    PurposeCodeCorridorMapping,
)
from app.modules.compliance.infrastructure.purpose_code_repository import (
    SQLAlchemyPurposeCodeRepository,
)
from app.modules.compliance.infrastructure.purpose_code_seed_loader import (
    SEED_DATA_DIR,
    load_purpose_codes,
)

# Imported as a module, not `from ... import AsyncSessionLocal`: the session-scoped
# autouse fixture in backend/conftest.py rebinds that attribute to a NullPool
# sessionmaker, and a name bound at import time would keep the pooled original —
# whose connections belong to whichever event loop first opened them.
from app.platform.database import services as database

CANONICAL_YAML = """
- canonical_code: TRADE_GOODS_IMPORT
  description: "Import payment for physical goods"
  category: trade
  effective_from: 2020-01-01
- canonical_code: RETIRED_CODE
  description: "Retired Code"
  category: other
  effective_from: 2023-01-01
  effective_to: 2024-01-01
- canonical_code: FUTURE_CODE
  description: "Future Code"
  category: other
  effective_from: 2025-01-01
- canonical_code: OPEN_ENDED_CODE
  description: "Open Ended Code"
  category: other
  effective_from: 2020-01-01
- canonical_code: AMBIGUOUS_CODE
  description: "Ambiguous Code"
  category: other
  effective_from: 2024-01-01
- canonical_code: ORPHAN_CODE
  description: "Code with no mappings"
  category: other
  effective_from: 2020-01-01
- canonical_code: EXPIRED_MAPPING_CODE
  description: "Valid Canonical, Expired Mapping"
  category: other
  effective_from: 2020-01-01
- canonical_code: REINSTATED_CODE
  description: "Retired in 2022, reinstated in 2024"
  category: other
  effective_from: 2020-01-01
  effective_to: 2022-01-01
- canonical_code: REINSTATED_CODE
  description: "Retired in 2022, reinstated in 2024"
  category: other
  effective_from: 2024-01-01
"""

V2020 = "RBI Purpose Code Master Circular 2020"
V2024 = "RBI Purpose Code Master Circular 2024"

# P0102_OLD -> P0102 is a standard revision, not just a date change: the two rows
# cite different circulars, so resolving a backdated payment must return the
# citation that was current then, not merely the code.
#
# A1/A2 deliberately cite *different* circulars covering the same window. Under
# one circular the exclusion constraint would reject the second row; across two
# it is accepted, which is exactly the ambiguity the application still has to
# catch.
MAPPINGS_YAML = f"""
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2020}
  external_code: P0102_OLD
  canonical_code: TRADE_GOODS_IMPORT
  effective_from: 2020-01-01
  effective_to: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2024}
  external_code: P0102
  canonical_code: TRADE_GOODS_IMPORT
  effective_from: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2020}
  external_code: E100
  canonical_code: EXPIRED_MAPPING_CODE
  effective_from: 2020-01-01
  effective_to: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2020}
  external_code: P9999
  canonical_code: RETIRED_CODE
  effective_from: 2023-01-01
  effective_to: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2024}
  external_code: F100
  canonical_code: FUTURE_CODE
  effective_from: 2025-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2020}
  external_code: O100
  canonical_code: OPEN_ENDED_CODE
  effective_from: 2020-01-01
- corridor_id: EUR_IN
  external_standard: RBI
  external_standard_version: {V2024}
  external_code: P0102
  canonical_code: TRADE_GOODS_IMPORT
  effective_from: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2020}
  external_code: A1
  canonical_code: AMBIGUOUS_CODE
  effective_from: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2024}
  external_code: A2
  canonical_code: AMBIGUOUS_CODE
  effective_from: 2024-01-01
- corridor_id: US_IN
  external_standard: RBI
  external_standard_version: {V2020}
  external_code: R100
  canonical_code: REINSTATED_CODE
  effective_from: 2020-01-01
"""


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory):
    """The fixture registry on disk, in the layout the loader expects."""
    path = tmp_path_factory.mktemp("purpose-codes")
    (path / "canonical.yaml").write_text(CANONICAL_YAML)
    (path / "corridor-mappings.yaml").write_text(MAPPINGS_YAML)
    return path


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_registry(seed_dir):
    """Install the fixture registry for this module, then restore the real one.

    Module-scoped because the load is a full table rewrite and the tests only
    read. Each session is opened and closed inside this fixture rather than held
    across the ``yield``: fixtures and tests run on different event loops here,
    and an asyncpg connection cannot be used from a loop other than the one that
    created it.
    """
    async with database.AsyncSessionLocal() as session:
        await load_purpose_codes(session, seed_dir)

    try:
        yield seed_dir
    finally:
        # Put the shared database back the way the app left it. Without this, the
        # fictional codes above outlive the run and every later consumer of the
        # registry — other suites, a developer's local API — sees them instead of
        # the real corridors.
        async with database.AsyncSessionLocal() as session:
            await load_purpose_codes(session, SEED_DATA_DIR)

            restored = await session.execute(
                select(PurposeCodeCanonical.canonical_code).where(
                    PurposeCodeCanonical.canonical_code == "TRADE_GOODS_IMPORT"
                )
            )
            assert restored.scalar_one_or_none() == "TRADE_GOODS_IMPORT", (
                "GitOps seed data was not restored; the shared test database is "
                "still holding this suite's fixture codes"
            )

            leaked = await session.execute(
                select(PurposeCodeCanonical.canonical_code).where(
                    PurposeCodeCanonical.canonical_code.in_(
                        [
                            "RETIRED_CODE",
                            "FUTURE_CODE",
                            "AMBIGUOUS_CODE",
                            "ORPHAN_CODE",
                            "REINSTATED_CODE",
                        ]
                    )
                )
            )
            assert leaked.scalars().all() == [], "fixture codes survived the restore"


@pytest_asyncio.fixture(loop_scope="function")
async def repo(seeded_registry):
    """A repository on a session belonging to the running test's own event loop."""
    async with database.AsyncSessionLocal() as session:
        yield SQLAlchemyPurposeCodeRepository(session)


# ── TC-16 / TC-17: seed loading ───────────────────────────────────────────────

async def test_seed_data_loads_into_both_tables(repo):
    """TC-16. The loader is the only writer these tables have, so "the YAML
    parsed" and "the rows are queryable" are worth asserting separately."""
    canonicals = await repo.session.execute(select(PurposeCodeCanonical))
    mappings = await repo.session.execute(select(PurposeCodeCorridorMapping))

    assert len(canonicals.scalars().all()) == 9
    assert len(mappings.scalars().all()) == 10


async def test_reloading_the_same_seed_is_idempotent(repo, seeded_registry):
    """The loader runs on every boot, so a second load of the same directory must
    leave one copy of the data rather than two. Reloads the *fixture* directory,
    not the GitOps one, so the registry the rest of the module reads is unchanged.

    Row count, not per-code uniqueness: REINSTATED_CODE legitimately appears
    twice (retired 2020-2022, reinstated 2024-), so "every canonical_code is
    unique" is no longer a valid check on its own — a row-count comparison
    catches append-instead-of-replace regardless.
    """
    async with database.AsyncSessionLocal() as other:
        await load_purpose_codes(other, seeded_registry)

    repo.session.expire_all()
    rows = (await repo.session.execute(select(PurposeCodeCanonical))).scalars().all()

    assert len(rows) == 9, "a second load duplicated rows instead of replacing them"


async def test_concurrent_reloads_do_not_collide(repo, seeded_registry):
    """Two replicas booting at once must not corrupt the registry (BUILD.md #6).

    Without the advisory lock in the loader this is a real failure, not a
    theoretical one: under READ COMMITTED the second transaction's DELETE cannot
    see the first's uncommitted rows, so it deletes nothing, both insert, and the
    later commit dies on ex_purpose_code_canonical_validity — taking a replica's
    startup with it. With the lock the second loader waits and then rewrites the
    same rows.

    Two sessions, two connections, genuinely overlapping — a single session would
    serialise on its own connection and prove nothing.
    """
    async def reload():
        async with database.AsyncSessionLocal() as session:
            await load_purpose_codes(session, seeded_registry)

    await asyncio.gather(reload(), reload())

    repo.session.expire_all()
    rows = (await repo.session.execute(select(PurposeCodeCanonical))).scalars().all()
    assert len(rows) == 9, "concurrent reloads duplicated canonical rows"

    mappings = (await repo.session.execute(select(PurposeCodeCorridorMapping))).scalars().all()
    assert len(mappings) == 10


# ── TC-01 .. TC-15: resolution through the SQLAlchemy repository ──────────────

async def test_resolves_a_us_in_purpose_code(repo):
    """TC-01."""
    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )
    assert result.external_code == "P0102"
    assert result.external_standard == "RBI"
    assert result.external_standard_version == V2024


async def test_backdated_transaction_resolves_the_revision_in_force_then(repo):
    """The citation travels with the code. A payment dated under the 2020
    circular resolves to that circular's code *and* names it, so the filing stays
    explicable after the regulator has moved on."""
    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2022, 6, 1),
        repository=repo,
    )
    assert result.external_code == "P0102_OLD"
    assert result.external_standard_version == V2020


async def test_unknown_canonical_code_is_rejected(repo):
    """TC-02."""
    with pytest.raises(PurposeCodeNotFoundError):
        await validate_purpose_code(
            canonical_code="UNKNOWN_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_canonical_code_before_its_effective_from_is_rejected(repo):
    """TC-03."""
    with pytest.raises(PurposeCodeNotEffectiveError):
        await validate_purpose_code(
            canonical_code="FUTURE_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 12, 31),
            repository=repo,
        )


async def test_retired_canonical_code_is_rejected(repo):
    """TC-04."""
    with pytest.raises(PurposeCodeNotEffectiveError):
        await validate_purpose_code(
            canonical_code="RETIRED_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_canonical_code_with_no_mapping_for_the_corridor_is_rejected(repo):
    """TC-05. ORPHAN_CODE is a live code that no corridor maps."""
    with pytest.raises(PurposeCodeNotValidForCorridorError):
        await validate_purpose_code(
            canonical_code="ORPHAN_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_mapping_before_its_effective_from_is_rejected(repo):
    """TC-06. TRADE_GOODS_IMPORT is live from 2020, but its EUR_IN mapping only
    starts in 2024 — so this exercises the mapping window, not the canonical one."""
    with pytest.raises(PurposeCodeNotValidForCorridorError):
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="EUR_IN",
            transaction_date=date(2023, 12, 31),
            repository=repo,
        )


async def test_mapping_after_its_effective_to_is_rejected(repo):
    """TC-07. The canonical code is still live; only the mapping has expired."""
    with pytest.raises(PurposeCodeNotValidForCorridorError):
        await validate_purpose_code(
            canonical_code="EXPIRED_MAPPING_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_a_new_corridor_needs_no_change_to_canonical_codes(repo):
    """TC-08 / TC-17. EUR_IN resolves the same canonical code the US_IN corridor
    uses — adding a corridor is a mappings-only change."""
    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="EUR_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )
    assert result.external_code == "P0102"


async def test_backdated_transaction_resolves_the_historical_mapping(repo):
    """TC-09."""
    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2023, 6, 1),
        repository=repo,
    )
    assert result.external_code == "P0102_OLD"


async def test_current_transaction_resolves_the_current_mapping(repo):
    """TC-10."""
    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )
    assert result.external_code == "P0102"


async def test_effective_from_is_inclusive(repo):
    """TC-11 / TC-12. 2024-01-01 both ends P0102_OLD and starts P0102, so exactly
    one mapping is live that day — if the boundary were inclusive on both sides
    this would raise AmbiguousPurposeCodeMappingError instead."""
    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 1, 1),
        repository=repo,
    )
    assert result.external_code == "P0102"


async def test_open_ended_mapping_resolves_far_in_the_future(repo):
    """TC-13. A NULL effective_to must read back from Postgres as "no end"."""
    result = await validate_purpose_code(
        canonical_code="OPEN_ENDED_CODE",
        corridor_id="US_IN",
        transaction_date=date(2099, 1, 1),
        repository=repo,
    )
    assert result.external_code == "O100"


async def test_two_mappings_live_at_once_is_rejected(repo):
    """TC-14. A1 and A2 share a corridor and window but differ in external_code,
    so the unique constraint permits both rows — the ambiguity has to be caught
    at resolution time."""
    with pytest.raises(AmbiguousPurposeCodeMappingError):
        await validate_purpose_code(
            canonical_code="AMBIGUOUS_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_missing_canonical_code_is_rejected(repo):
    """TC-15."""
    with pytest.raises(PurposeCodeInputError):
        await validate_purpose_code(
            canonical_code=None,  # type: ignore[arg-type]
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_rejections_reaching_the_api_carry_a_caller_fault_status(repo):
    """The registry's errors must render as structured 422s rather than 500s.

    Asserted against the real repository because that is the path a payment
    would take: a bare Exception raised here would reach the catch-all handler
    registered in app/main.py and be reported as a platform failure.
    """
    with pytest.raises(PurposeCodeNotFoundError) as exc:
        await validate_purpose_code(
            canonical_code="UNKNOWN_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == "PURPOSE_CODE_NOT_FOUND"
    assert exc.value.extensions["canonical_code"] == "UNKNOWN_CODE"
    assert exc.value.extensions["transaction_date"] == "2024-06-01"


# ── Canonical codes with a history (retired, then reinstated) ────────────────
#
# Proves the bug against the real SQLAlchemy repository, not just the in-memory
# fake in tests/unit/: ex_purpose_code_canonical_validity permits a second row
# once the first's window has closed, and get_canonical_history has to return
# every row so validate_purpose_code can pick the one covering transaction_date
# — a query that grabbed an arbitrary matching row (e.g. Postgres's own return
# order with no ORDER BY) could resolve a live 2024 code as retired, or the
# reverse.

async def test_reinstated_code_resolves_using_the_window_in_force_then(repo):
    result = await validate_purpose_code(
        canonical_code="REINSTATED_CODE",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )
    assert result.external_code == "R100"


async def test_reinstated_code_also_resolves_for_its_original_window(repo):
    """The mirror case: a query that always preferred the newest row would
    wrongly reject a genuinely historical transaction from the first window."""
    result = await validate_purpose_code(
        canonical_code="REINSTATED_CODE",
        corridor_id="US_IN",
        transaction_date=date(2021, 6, 1),
        repository=repo,
    )
    assert result.external_code == "R100"


async def test_reinstated_code_is_rejected_in_the_gap_between_windows(repo):
    """2022-2024 is retired: covered by neither row. Reports both historical
    windows rather than naming one that was never in force on this date."""
    with pytest.raises(PurposeCodeNotEffectiveError) as exc:
        await validate_purpose_code(
            canonical_code="REINSTATED_CODE",
            corridor_id="US_IN",
            transaction_date=date(2023, 1, 1),
            repository=repo,
        )

    assert exc.value.extensions["effective_windows"] == [
        {"effective_from": "2020-01-01", "effective_to": "2022-01-01"},
        {"effective_from": "2024-01-01", "effective_to": None},
    ]
