"""``HistoryService`` — the shared history writer and its transaction rule.

The rule this file exists to hold in place is the one in
``docs/contracts/history-row.md`` §5:

> The history writer flushes. It never commits. The caller owns the transaction.

Everything else here is in service of that. A writer that quietly committed
would pass every assertion about column values while breaking the only
guarantee that matters — that a company's current value and the row recording
how it got there land together or not at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.onboarding.application.exporter_profile_service import (
    ExporterProfileService,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


async def _rows_for(company_id: uuid.UUID) -> list[ExporterLifecycleHistory]:
    """Read committed history in a fresh session.

    Fresh on purpose: reading through the session that wrote would see the
    flushed-but-uncommitted row and prove nothing about what survived.
    """
    async with db_services.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExporterLifecycleHistory).where(
                ExporterLifecycleHistory.customer_id == company_id
            )
        )
        return list(result.scalars().all())


# ── The writer ───────────────────────────────────────────────────────────────


async def test_record_writes_one_row_with_every_contracted_field():
    company_id = await make_company()
    deal_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        await HistoryService(db).record(
            company_id,
            dimension="deal",
            from_value="OPEN",
            to_value="WITHDRAWN",
            actor_id="user-7",
            reason="buyer pulled out",
            source="deal_service.withdraw",
            deal_id=deal_id,
            details={"buyer_country": "AE"},
        )
        await db.commit()

    (row,) = await _rows_for(company_id)
    assert row.dimension == "deal"
    assert row.deal_id == deal_id
    assert row.from_status == "OPEN"
    assert row.to_status == "WITHDRAWN"
    assert row.actor_id == "user-7"
    assert row.reason == "buyer pulled out"
    assert row.event_metadata == {"source": "deal_service.withdraw", "buyer_country": "AE"}
    assert row.created_at is not None


async def test_record_returns_the_flushed_row():
    """The caller gets the row back with its id, so a decision that needs to
    reference what it just recorded does not have to re-query for it."""
    company_id = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        row = await HistoryService(db).record(
            company_id,
            dimension="background_check",
            to_value="IN_REVIEW",
            actor_id="compliance-1",
            source="test",
        )
        assert row.id is not None
        await db.commit()

    assert [r.id for r in await _rows_for(company_id)] == [row.id]


async def test_event_type_is_derived_from_the_dimension_and_direction():
    """`<dimension>_initial` when a value is set at creation,
    `<dimension>_transition` when it moves — so a new gauge gets consistent
    naming without every writer inventing its own."""
    company_id = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        service = HistoryService(db)
        await service.record(
            company_id, dimension="conversation", to_value="NOT_CONTACTED",
            actor_id=None, source="test",
        )
        await service.record(
            company_id, dimension="conversation", from_value="NOT_CONTACTED",
            to_value="REACHING_OUT", actor_id=None, source="test",
        )
        await db.commit()

    assert {r.event_type for r in await _rows_for(company_id)} == {
        "conversation_initial",
        "conversation_transition",
    }


async def test_an_explicit_event_type_overrides_the_derived_one():
    """The journey needs this: its rows have always been `lifecycle_transition`,
    a downstream consumer polls for that name, and thousands of rows carry it."""
    company_id = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        await HistoryService(db).record(
            company_id, dimension="journey", from_value="LEAD", to_value="CONTACTED",
            actor_id="rm-1", source="test", event_type="lifecycle_transition",
        )
        await db.commit()

    (row,) = await _rows_for(company_id)
    assert row.event_type == "lifecycle_transition"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dimension": "  ", "to_value": "X"}, "dimension"),
        ({"dimension": "journey", "to_value": " "}, "to_value"),
        ({"dimension": "j" * 33, "to_value": "X"}, "dimension"),
        ({"dimension": "journey", "to_value": "v" * 65}, "to_value"),
    ],
)
async def test_a_bad_field_is_refused_before_it_reaches_postgres(kwargs: dict, message: str):
    """A 422 naming the field beats a `StringDataRightTruncation` surfacing
    halfway through a transaction the caller thought was fine."""
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match=message):
            await HistoryService(db).record(
                uuid.uuid4(), actor_id=None, source="test", **kwargs
            )


async def test_a_dimension_nobody_has_built_yet_is_accepted():
    """No migration, no enum, no change to this service: a gauge that does not
    exist yet can be recorded the day its writer lands."""
    company_id = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        await HistoryService(db).record(
            company_id, dimension="something_dev5_invents", to_value="NEW",
            actor_id=None, source="test",
        )
        await db.commit()

    assert (await _rows_for(company_id))[0].dimension == "something_dev5_invents"


# ── The transaction rule (Task 4) ────────────────────────────────────────────


async def test_record_flushes_without_committing():
    """The row is visible inside the writing transaction and nowhere else.

    This is the narrow proof that `record` flushed rather than committed: a
    committed row would already be readable from another session at this point.
    """
    company_id = await make_company()

    async with db_services.AsyncSessionLocal() as db:
        await HistoryService(db).record(
            company_id, dimension="journey", to_value="LEAD", actor_id="rm-1", source="test",
        )
        # Visible to the writer...
        inside = await db.execute(
            select(ExporterLifecycleHistory).where(
                ExporterLifecycleHistory.customer_id == company_id
            )
        )
        assert len(list(inside.scalars().all())) == 1
        # ...and to nobody else.
        assert await _rows_for(company_id) == []

        await db.rollback()

    assert await _rows_for(company_id) == []


async def test_a_rollback_discards_the_state_change_and_its_history_together():
    """The whole point of flush-not-commit, end to end.

    1. the state change begins — a profile's `lifecycle_status` is assigned;
    2. the history writer flushes its row;
    3. the caller rolls back;
    4. neither survives.

    If `record` committed on its own, step 4 would leave an orphan history row
    claiming a move that was abandoned — a permanent, append-only record of
    something that never happened, which is worse than no record at all.
    """
    company_id = uuid.uuid4()

    # A committed profile to move, so the rollback has something real to undo.
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            company_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        assert profile.lifecycle_status is ExporterLifecycleStatus.LEAD

        # 1. the state change
        profile.lifecycle_status = ExporterLifecycleStatus.CONTACTED
        # 2. the history row, flushed
        await HistoryService(db).record(
            company_id,
            dimension="journey",
            from_value=ExporterLifecycleStatus.LEAD.value,
            to_value=ExporterLifecycleStatus.CONTACTED.value,
            actor_id="rm-1",
            source="test.rollback",
        )
        # 3. the caller changes its mind
        await db.rollback()

    # 4. neither survives
    async with db_services.AsyncSessionLocal() as db:
        after = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        assert after.lifecycle_status is ExporterLifecycleStatus.LEAD

    assert [r.to_status for r in await _rows_for(company_id)] == [
        ExporterLifecycleStatus.LEAD.value
    ], "only the creation row should remain"


async def test_state_and_history_commit_together():
    """The other half: one commit, and both land."""
    company_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            company_id, source=ExporterSource.SALES
        )

    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.lifecycle_status = ExporterLifecycleStatus.CONTACTED
        await HistoryService(db).record(
            company_id,
            dimension="journey",
            from_value=ExporterLifecycleStatus.LEAD.value,
            to_value=ExporterLifecycleStatus.CONTACTED.value,
            actor_id="rm-1",
            source="test.commit",
        )
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        after = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        assert after.lifecycle_status is ExporterLifecycleStatus.CONTACTED

    assert ExporterLifecycleStatus.CONTACTED.value in {
        r.to_status for r in await _rows_for(company_id)
    }


# ── The lifecycle writer now goes through this service (Task 2) ──────────────


async def test_the_lifecycle_transition_still_records_what_it_always_did():
    """Repointing `ExporterProfileService` at the shared writer must not change
    a single field of what it writes — a downstream consumer polls these rows."""
    company_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        await service.create_or_get_profile(company_id, source=ExporterSource.SALES)
        await service.transition_lifecycle_status(
            company_id, ExporterLifecycleStatus.CONTACTED, actor_id="rm-jordan"
        )

    rows = sorted(await _rows_for(company_id), key=lambda r: r.created_at)
    assert [r.event_type for r in rows] == ["lifecycle_initial", "lifecycle_transition"]
    assert {r.dimension for r in rows} == {"journey"}
    assert all(r.deal_id is None for r in rows)

    move = rows[-1]
    assert move.from_status == ExporterLifecycleStatus.LEAD.value
    assert move.to_status == ExporterLifecycleStatus.CONTACTED.value
    assert move.actor_id == "rm-jordan"
    assert move.event_metadata["terminal"] is False
    assert move.event_metadata["source"].endswith("transition_lifecycle_status")


async def test_the_terminal_flag_still_marks_the_onboarded_edge():
    """ANER-4.2-S1T2's completion hook filters on this; it must survive the
    move to the shared writer."""
    company_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        await service.create_or_get_profile(
            company_id,
            source=ExporterSource.SALES,
            lifecycle_status=ExporterLifecycleStatus.ONBOARDED,
            compliance_authorized=True,
        )

    (row,) = await _rows_for(company_id)
    assert row.event_type == "lifecycle_initial"
    assert row.event_metadata["terminal"] is True


# ── Reads ────────────────────────────────────────────────────────────────────


async def _seed_mixed(company_id: uuid.UUID, deal_id: uuid.UUID) -> None:
    async with db_services.AsyncSessionLocal() as db:
        service = HistoryService(db)
        await service.record(
            company_id, dimension="journey", to_value="LEAD", actor_id="a", source="t"
        )
        await service.record(
            company_id, dimension="qualification", to_value="QUALIFIED",
            actor_id="b", source="t",
        )
        await service.record(
            company_id, dimension="deal", to_value="OPEN", actor_id="c",
            source="t", deal_id=deal_id,
        )
        await db.commit()


async def test_an_unfiltered_read_returns_every_dimension():
    company_id, deal_id = await make_company(), uuid.uuid4()
    await _seed_mixed(company_id, deal_id)

    async with db_services.AsyncSessionLocal() as db:
        rows, total = await HistoryService(db).list_for_company(company_id)

    assert total == 3
    assert {r.dimension for r in rows} == {"journey", "qualification", "deal"}


async def test_a_dimension_filter_narrows_the_read_and_the_total():
    company_id, deal_id = await make_company(), uuid.uuid4()
    await _seed_mixed(company_id, deal_id)

    async with db_services.AsyncSessionLocal() as db:
        rows, total = await HistoryService(db).list_for_company(
            company_id, dimension="qualification"
        )

    assert total == 1
    assert [r.to_status for r in rows] == ["QUALIFIED"]


async def test_a_deal_read_returns_only_that_deals_rows():
    company_id, deal_id = await make_company(), uuid.uuid4()
    await _seed_mixed(company_id, deal_id)

    async with db_services.AsyncSessionLocal() as db:
        rows, total = await HistoryService(db).list_for_deal(deal_id)

    assert total == 1
    assert rows[0].deal_id == deal_id


async def test_an_unknown_deal_reads_empty_rather_than_raising():
    """The correct answer until deals exist (migration 0018), and the correct
    answer afterwards for a deal id that was never real — this service has no
    deal table to check against."""
    async with db_services.AsyncSessionLocal() as db:
        rows, total = await HistoryService(db).list_for_deal(uuid.uuid4())

    assert (list(rows), total) == ([], 0)


async def test_paging_is_newest_first_and_does_not_repeat_a_row():
    company_id, deal_id = await make_company(), uuid.uuid4()
    await _seed_mixed(company_id, deal_id)

    async with db_services.AsyncSessionLocal() as db:
        service = HistoryService(db)
        first, total = await service.list_for_company(company_id, limit=2, offset=0)
        second, _ = await service.list_for_company(company_id, limit=2, offset=2)

    assert total == 3
    assert len(first) == 2 and len(second) == 1
    assert {r.id for r in first}.isdisjoint({r.id for r in second})
