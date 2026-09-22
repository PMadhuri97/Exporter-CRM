"""Concurrency safety of `case_reference` generation (ANER-4.3-S1T1).

`cases_0001_case_management`'s module docstring argues that `case_reference`
values are gap-free and duplicate-free under *concurrent* creation because the
per-year counter (`cases.case_reference_sequence`) is advanced with
`INSERT ... ON CONFLICT (calendar_year) DO UPDATE ... RETURNING next_value`
inside the same transaction as the case row: the `UPDATE` takes a row lock on
that year's counter row, serialising concurrent conflicting upserts in
Postgres — the same anti-duplicate property a native `SEQUENCE` has, but
transactional, so a rolled-back insert rolls the counter back with it too.

`test_two_generated_references_in_the_same_year_are_distinct_and_sequential`
in test_s1t1_case_management_schema.py only proves the two-values-are-distinct
half of that claim, and does it with two *sequential* inserts over one
connection — real concurrency is never exercised, so the docstring's actual
claim ("gap-free and duplicate-free under concurrent creation") stays
unproven. This suite proves it, following the same genuinely-concurrent
pattern the ledger module uses in
`app/modules/ledger/tests/integration/test_ledger_concurrency.py` (and
compliance's `test_concurrent_reloads_do_not_collide`): each insert opens its
own `AsyncSession` (NullPool gives each its own connection) and all of them
run under `asyncio.gather`, so they genuinely contend on the counter row's
lock rather than serialising trivially on a single shared connection.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from app.modules.cases.tests.fixtures.case_sql import case_params, fetchall
from app.platform.database import services as database

_CASE_REFERENCE_RE = re.compile(r"^CASE-(\d{4})-(\d+)$")

_INSERT_CASE_ASYNC = text(
    """
    INSERT INTO cases.compliance_case (
        id, case_reference, case_type, case_status, severity, priority,
        title, description, customer_id, settlement_id, onboarding_id,
        originating_epic, originating_event_type, originating_event_id,
        assigned_to, assigned_at, sla_deadline, sla_breached,
        resolution_action, resolution_note, resolution_approval_request_id,
        resolved_at, resolved_by
    ) VALUES (
        :id, :case_reference, :case_type, :case_status, :severity,
        :priority, :title, :description, :customer_id,
        :settlement_id, :onboarding_id, :originating_epic,
        :originating_event_type, :originating_event_id, :assigned_to,
        :assigned_at, :sla_deadline, :sla_breached,
        :resolution_action, :resolution_note,
        :resolution_approval_request_id, :resolved_at, :resolved_by
    )
    """
)


async def _insert_case_with_generated_reference(case_id: str) -> None:
    """Insert one case in its own session/connection, leaving case_reference
    NULL so the database trigger generates it, then commit.

    A separate `AsyncSessionLocal()` per call is the whole point: sharing one
    session/connection across the batch would serialise the inserts on the
    client side and prove nothing about the database's own locking.
    """
    params = case_params(id=case_id)
    params["case_reference"] = None
    # asyncpg (unlike psycopg2, which the rest of this module's fixtures use)
    # does not coerce an ISO string into a timestamptz parameter, so it needs
    # a real datetime here.
    params["sla_deadline"] = datetime.fromisoformat(params["sla_deadline"])
    async with database.AsyncSessionLocal() as session:
        await session.execute(_INSERT_CASE_ASYNC, params)
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_case_creations_generate_a_gapless_distinct_sequence():
    """Twenty genuinely concurrent inserts (separate sessions/connections, run
    via asyncio.gather) must each get a distinct case_reference, and the
    sequence numbers assigned within this run must be contiguous — proving
    the locked-counter-table design neither drops nor duplicates a value
    under real concurrent contention, matching the ledger suite's standard
    for what "proves concurrency safety" means in this codebase.
    """
    n = 20
    case_ids = [str(uuid.uuid4()) for _ in range(n)]

    await asyncio.gather(*(_insert_case_with_generated_reference(cid) for cid in case_ids))

    placeholders = ", ".join("%s" for _ in case_ids)
    rows = fetchall(
        f"SELECT case_reference FROM cases.compliance_case WHERE id::text IN ({placeholders})",
        tuple(case_ids),
    )

    assert len(rows) == n, "every concurrent insert must have produced exactly one case row"

    references = [row[0] for row in rows]

    # No two concurrent inserts may have been handed the same reference.
    assert len(set(references)) == n, (
        f"concurrent inserts produced duplicate case_reference values: {references}"
    )

    parsed = []
    for reference in references:
        match = _CASE_REFERENCE_RE.match(reference)
        assert match is not None, f"unexpected case_reference format: {reference!r}"
        parsed.append((int(match.group(1)), int(match.group(2))))

    # All twenty landed in the same calendar year (the trigger uses now()'s
    # year), so gap-freedom can be checked as a single contiguous run of
    # sequence numbers, independent of whatever value the shared, never-reset
    # counter had already reached before this test ran.
    years = {year for year, _seq in parsed}
    assert len(years) == 1, f"expected all references to share one calendar year, got {years}"

    seqs = sorted(seq for _year, seq in parsed)
    assert len(set(seqs)) == n, "sequence numbers must be unique — a duplicate is a lost lock"
    assert seqs[-1] - seqs[0] + 1 == n, (
        f"expected a gap-free run of {n} sequence numbers, got {seqs} — the counter "
        f"either skipped a value or a concurrent insert overwrote another's slot"
    )
    assert seqs == list(range(seqs[0], seqs[0] + n)), "sequence numbers must be contiguous"
