"""Integration tests for E9's `ScreeningReviewService`, and for the lifecycle
event `ExporterProfileService.transition_lifecycle_status` now writes.

There were no tests for `ScreeningReviewService` at all. The three behaviours
covered here are the three that were silently wrong:

  • a repeat decision on a checklist item preserved the earlier one (it did not —
    it overwrote status, comment, reviewer and timestamp in place);
  • an unrecognised `item_key` was rejected (it was not — the router took the
    path segment as a free string and the column is `String(100)`, so a typo
    persisted, rendered nowhere, and never counted toward "X/8 reviewed");
  • a lifecycle transition recorded who made it (it did not — `actor_id` reached
    a log line and no table).

Follows `test_exp1_exporter_profile_service.py`'s conventions: real Postgres, no
per-test rollback, each test opens its own `AsyncSessionLocal()` session(s)
directly, and isolation comes from every test minting a fresh `customer_id`
rather than from a shared wipe fixture.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.modules.onboarding.application.exporter_profile_service import (
    ExporterProfileService,
)
from app.modules.onboarding.application.screening_review_service import (
    VALID_ITEM_KEYS,
    ScreeningReviewService,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    LIFECYCLE_INITIAL_EVENT,
    LIFECYCLE_TRANSITION_EVENT,
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

ITEM = "website-reviewed"


# ── Repeat writes preserve history ───────────────────────────────────────────

async def test_a_repeat_decision_does_not_overwrite_the_first_one():
    """The whole point of onboarding_0011_e9_audit.

    FAILED by one reviewer, then PASSED by another. Before this change the second
    write mutated the first row, and the fact that the item had ever failed —
    and who failed it — was gone.
    """
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ScreeningReviewService(db)
        first = await service.upsert_review_item(
            customer_id,
            item_key=ITEM,
            status="FAILED",
            comment="site is parked",
            actor_id="reviewer-a",
        )
        first_id = first.id

        second = await service.upsert_review_item(
            customer_id,
            item_key=ITEM,
            status="PASSED",
            comment="resolved with the exporter",
            actor_id="reviewer-b",
        )

    assert second.id != first_id, "a repeat decision must be a new row, not an edit"

    async with db_services.AsyncSessionLocal() as db:
        history = await ScreeningReviewService(db).list_item_history(customer_id, ITEM)

    assert [(h.status, h.reviewed_by) for h in history] == [
        ("PASSED", "reviewer-b"),
        ("FAILED", "reviewer-a"),
    ]
    assert history[-1].comment == "site is parked", (
        "the superseded decision's comment was rewritten"
    )


async def test_the_checklist_still_reads_as_current_state_only():
    """The response contract: one row per item_key, the latest.

    `GET /screening-review` returns `list_review_items` verbatim. Appending
    decisions must not turn a checklist of 8 into a list of every decision ever
    taken — that would change what the endpoint returns without changing its
    schema, which is the failure mode worth guarding.
    """
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ScreeningReviewService(db)
        for status in ("NEEDS_REVIEW", "FAILED", "PASSED"):
            await service.upsert_review_item(
                customer_id,
                item_key=ITEM,
                status=status,
                comment=None,
                actor_id="reviewer-a",
            )
        await service.upsert_review_item(
            customer_id,
            item_key="address-physical",
            status="PASSED",
            comment=None,
            actor_id="reviewer-a",
        )

        items = await service.list_review_items(customer_id)

    assert len(items) == 2, "one row per item_key, not one row per decision"
    by_key = {item.item_key: item for item in items}
    assert by_key[ITEM].status == "PASSED", "the newest decision must win"
    assert by_key["address-physical"].status == "PASSED"


async def test_every_decision_is_still_on_the_table_underneath():
    """`list_review_items` hides the superseded rows; it does not delete them."""
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ScreeningReviewService(db)
        for status in ("NEEDS_REVIEW", "FAILED", "PASSED"):
            await service.upsert_review_item(
                customer_id,
                item_key=ITEM,
                status=status,
                comment=None,
                actor_id="reviewer-a",
            )

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ScreeningReviewItem).where(
                    ScreeningReviewItem.customer_id == customer_id
                )
            )
        ).scalars().all()

    assert len(rows) == 3


async def test_the_database_refuses_to_update_a_recorded_decision():
    """The guard is the trigger, not this service.

    A future writer that bypasses `upsert_review_item` — a data fix, another
    service, a console session — must still be unable to rewrite a decision.
    `public.prevent_mutation()` raises a PL/pgSQL exception, which asyncpg
    reports as `RaiseError` and SQLAlchemy wraps as `DBAPIError` — not one of
    the mapped `IntegrityError`/`ProgrammingError` subclasses, since it is a
    user-raised condition rather than a constraint violation.
    """
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        item = await ScreeningReviewService(db).upsert_review_item(
            customer_id,
            item_key=ITEM,
            status="FAILED",
            comment=None,
            actor_id="reviewer-a",
        )
        item_id = item.id

    async with db_services.AsyncSessionLocal() as db:
        loaded = await db.get(ScreeningReviewItem, item_id)
        loaded.status = "PASSED"
        with pytest.raises(DBAPIError, match="immutable"):
            await db.commit()
        await db.rollback()

    async with db_services.AsyncSessionLocal() as db:
        unchanged = await db.get(ScreeningReviewItem, item_id)

    assert unchanged.status == "FAILED"


# ── Unknown item_key is rejected ─────────────────────────────────────────────

async def test_an_unknown_item_key_is_rejected():
    """A typo used to persist and then render nowhere. Now it raises.

    `ValidationError` is a 422 through `aner_exception_handler`, which
    `app/main.py` already registers for every `AnerBaseException` — so the
    router needs no change to return the right status.
    """
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError) as excinfo:
            await ScreeningReviewService(db).upsert_review_item(
                customer_id,
                item_key="website-review",  # the real key is "website-reviewed"
                status="PASSED",
                comment=None,
                actor_id="reviewer-a",
            )

    assert excinfo.value.status_code == 422
    assert "website-review" in excinfo.value.detail


async def test_a_rejected_item_key_writes_nothing():
    """The validation has to happen before the insert, not alongside it."""
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await ScreeningReviewService(db).upsert_review_item(
                customer_id,
                item_key="not-a-real-item",
                status="PASSED",
                comment=None,
                actor_id="reviewer-a",
            )

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ScreeningReviewItem).where(
                    ScreeningReviewItem.customer_id == customer_id
                )
            )
        ).scalars().all()

    assert rows == []


@pytest.mark.parametrize("item_key", sorted(VALID_ITEM_KEYS))
async def test_every_key_the_frontend_renders_is_accepted(item_key: str):
    """The eight keys in `VerificationSection.tsx`'s `CHECKLIST_ITEMS`.

    Parametrized so that adding a key to `VALID_ITEM_KEYS` without it actually
    being writable fails here, rather than in a reviewer's browser.
    """
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        item = await ScreeningReviewService(db).upsert_review_item(
            customer_id,
            item_key=item_key,
            status="PASSED",
            comment=None,
            actor_id="reviewer-a",
        )

    assert item.item_key == item_key


async def test_the_valid_key_set_is_exactly_the_eight_the_ui_declares():
    """A guard against the two lists drifting apart silently.

    `VALID_ITEM_KEYS` and `CHECKLIST_ITEMS` in
    `frontend/src/modules/onboarding/components/VerificationSection.tsx` are the
    same list. Nothing mechanical keeps them in step, so the count and contents
    are asserted here where a change has to be deliberate.
    """
    assert VALID_ITEM_KEYS == {
        "website-reviewed",
        "address-physical",
        "business-consistency",
        "payment-purpose",
        "bank-statements-reviewed",
        "suspicious-bank-indicators",
        "exception-approval",
        "exception-evidence",
    }
    assert len(VALID_ITEM_KEYS) == 8


# ── A lifecycle transition writes an event ───────────────────────────────────

async def _profile_at(customer_id: uuid.UUID, target: ExporterLifecycleStatus) -> None:
    """Walk a fresh profile from LEAD up to `target` along legal edges."""
    path = [
        ExporterLifecycleStatus.CONTACTED,
        ExporterLifecycleStatus.DATA_COLLECTION,
        ExporterLifecycleStatus.VERIFICATION_IN_PROGRESS,
        ExporterLifecycleStatus.COMPLIANCE_REVIEW,
        ExporterLifecycleStatus.ONBOARDED,
    ]
    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        await service.create_or_get_profile(customer_id, source=ExporterSource.SALES)
        for status in path:
            await service.transition_lifecycle_status(
                customer_id, status, actor_id="walker", compliance_authorized=True
            )
            if status is target:
                return


async def test_a_lifecycle_transition_writes_an_event():
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        await service.create_or_get_profile(customer_id, source=ExporterSource.SALES)
        await service.transition_lifecycle_status(
            customer_id, ExporterLifecycleStatus.CONTACTED, actor_id="rm-jordan"
        )

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ExporterLifecycleHistory).where(
                    ExporterLifecycleHistory.customer_id == customer_id,
                    ExporterLifecycleHistory.event_type == LIFECYCLE_TRANSITION_EVENT,
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.from_status == ExporterLifecycleStatus.LEAD.value
    assert row.to_status == ExporterLifecycleStatus.CONTACTED.value
    assert row.actor_id == "rm-jordan", "actor_id used to reach a log line and nothing else"
    assert row.event_type == LIFECYCLE_TRANSITION_EVENT


async def test_a_rejected_transition_writes_no_event():
    """An attempted illegal move must not leave a record suggesting it happened."""
    from app.modules.onboarding.exceptions import InvalidExporterLifecycleTransitionError

    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        await service.create_or_get_profile(customer_id, source=ExporterSource.SALES)
        with pytest.raises(InvalidExporterLifecycleTransitionError):
            await service.transition_lifecycle_status(
                customer_id, ExporterLifecycleStatus.ACTIVE, actor_id="rm-jordan"
            )
        await db.rollback()

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ExporterLifecycleHistory).where(
                    ExporterLifecycleHistory.customer_id == customer_id
                )
            )
        ).scalars().all()

    # Only the creation row: nothing suggests the illegal move happened.
    assert [r.event_type for r in rows] == [LIFECYCLE_INITIAL_EVENT]


async def test_the_onboarded_edge_is_marked_for_the_completion_hook():
    """ANER-4.2-S1T2 needs to find COMPLIANCE_REVIEW -> ONBOARDED.

    `terminal` is what a downstream consumer filters on, and it is derived from
    the target status rather than hardcoded at the call site, so a new lifecycle
    status cannot quietly change what "onboarding completed" means.
    """
    customer_id = uuid.uuid4()
    await _profile_at(customer_id, ExporterLifecycleStatus.ONBOARDED)

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ExporterLifecycleHistory)
                .where(ExporterLifecycleHistory.customer_id == customer_id)
                .order_by(ExporterLifecycleHistory.created_at.asc())
            )
        ).scalars().all()

    terminal = [r for r in rows if (r.event_metadata or {}).get("terminal")]
    assert len(terminal) == 1, "exactly one edge is the completion edge"
    assert terminal[0].from_status == ExporterLifecycleStatus.COMPLIANCE_REVIEW.value
    assert terminal[0].to_status == ExporterLifecycleStatus.ONBOARDED.value
    assert terminal[0].actor_id == "walker"


async def test_the_full_walk_is_recorded_in_order():
    """Creation plus five transitions, six rows — the history a re-KYC reviewer
    reads back, starting from the status the profile was born at."""
    customer_id = uuid.uuid4()
    await _profile_at(customer_id, ExporterLifecycleStatus.ONBOARDED)

    async with db_services.AsyncSessionLocal() as db:
        rows = await ExporterProfileService(db)._lifecycle_history.list_by_customer(customer_id)

    assert [r.to_status for r in reversed(rows)] == [
        ExporterLifecycleStatus.LEAD.value,
        ExporterLifecycleStatus.CONTACTED.value,
        ExporterLifecycleStatus.DATA_COLLECTION.value,
        ExporterLifecycleStatus.VERIFICATION_IN_PROGRESS.value,
        ExporterLifecycleStatus.COMPLIANCE_REVIEW.value,
        ExporterLifecycleStatus.ONBOARDED.value,
    ]


async def test_the_database_refuses_to_update_a_lifecycle_event():
    """Same guard as the checklist: the trigger, not the service."""
    customer_id = uuid.uuid4()

    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        await service.create_or_get_profile(customer_id, source=ExporterSource.SALES)
        await service.transition_lifecycle_status(
            customer_id, ExporterLifecycleStatus.CONTACTED, actor_id="rm-jordan"
        )

    async with db_services.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(ExporterLifecycleHistory).where(
                    ExporterLifecycleHistory.customer_id == customer_id,
                    ExporterLifecycleHistory.event_type == LIFECYCLE_TRANSITION_EVENT,
                )
            )
        ).scalars().one()
        row.actor_id = "somebody-else"
        with pytest.raises(DBAPIError, match="immutable"):
            await db.commit()
        await db.rollback()


# ── Creation records the initial status ──────────────────────────────────────


async def _history(customer_id: uuid.UUID) -> list[ExporterLifecycleHistory]:
    async with db_services.AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(ExporterLifecycleHistory).where(
                        ExporterLifecycleHistory.customer_id == customer_id
                    )
                )
            ).scalars().all()
        )


async def test_creating_a_profile_records_its_initial_status():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, actor_id="rm-jordan"
        )

    [row] = await _history(customer_id)
    assert row.event_type == LIFECYCLE_INITIAL_EVENT
    assert row.from_status is None
    assert row.to_status == ExporterLifecycleStatus.LEAD.value
    assert row.actor_id == "rm-jordan"
    assert row.event_metadata["terminal"] is False


async def test_a_profile_created_onboarded_is_visible_to_the_completion_hook():
    """POST /exporters accepts a lifecycle_status. A profile born ONBOARDED
    used to leave no row at all — no actor, and nothing for ANER-4.2-S1T2."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id,
            source=ExporterSource.SALES,
            lifecycle_status=ExporterLifecycleStatus.ONBOARDED,
            actor_id="importer",
            compliance_authorized=True,
        )

    [row] = await _history(customer_id)
    assert row.to_status == ExporterLifecycleStatus.ONBOARDED.value
    assert row.actor_id == "importer"
    assert row.event_metadata["terminal"] is True


async def test_getting_an_existing_profile_writes_no_second_row():
    customer_id = uuid.uuid4()
    for _ in range(2):
        async with db_services.AsyncSessionLocal() as db:
            await ExporterProfileService(db).create_or_get_profile(
                customer_id, source=ExporterSource.SALES, actor_id="rm-jordan"
            )

    assert len(await _history(customer_id)) == 1


async def test_creating_a_lead_records_its_initial_status():
    async with db_services.AsyncSessionLocal() as db:
        _request, profile, created = await ExporterProfileService(db).create_lead(
            tenant_id=uuid.uuid4(),
            legal_name=f"Lead {uuid.uuid4().hex[:8]}",
            incorporation_country="IN",
            initial_user_email=f"{uuid.uuid4().hex[:8]}@example.com",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
            actor_id="rm-jordan",
        )
    assert created

    [row] = await _history(profile.customer_id)
    assert row.event_type == LIFECYCLE_INITIAL_EVENT
    assert row.from_status is None
    assert row.to_status == ExporterLifecycleStatus.LEAD.value
    assert row.actor_id == "rm-jordan"
