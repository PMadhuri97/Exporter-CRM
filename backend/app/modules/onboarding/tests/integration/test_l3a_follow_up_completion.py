"""Follow-up completion, the due/overdue list, and the Follow-ups routes (L3-04b).

**Phase 2 adds no migration and no constraint**, so what it owes the database instead
is the proof that the lock 0016 put on ``follow_up_completion`` actually holds against
*this* code, and that an attempt to break it is a clean error rather than a 500
(prompt §3). That is ``test_the_repository_exposes_no_way_to_change_a_completion`` and
the two around it. Phase 1's direct-SQL tests already prove the trigger itself.

The rest goes through the service and the API as a person would. Real Postgres, each
test minting its own company.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.onboarding.application.conversation_service import ConversationService
from app.modules.onboarding.application.exporter_contact_activity_service import (
    ExporterContactActivityService,
)
from app.modules.onboarding.application.follow_up_service import FollowUpService
from app.modules.onboarding.domain.entities.engagement_enums import (
    ExporterActivityType,
    ExporterConversation,
)
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.follow_up_completion import (
    FollowUpCompletion,
    FollowUpOutcome,
)
from app.modules.onboarding.domain.follow_up_views import FollowUpState
from app.modules.onboarding.exceptions import (
    ActivityIsNotAFollowUpError,
    FollowUpAlreadyCompletedError,
    FollowUpCompletionIsImmutableError,
    FollowUpNextDueNotAllowedError,
    FollowUpNotFoundError,
    FollowUpRescheduleInPastError,
    FollowUpRescheduleNeedsDateError,
)
from app.modules.onboarding.infrastructure.repositories import FollowUpCompletionRepository
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _at(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


async def _company(journey: ExporterJourney = ExporterJourney.PROSPECT) -> uuid.UUID:
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.journey = journey
        await db.commit()
    return company_id


async def _follow_up(
    company_id: uuid.UUID,
    *,
    due_in_days: int = 7,
    subject: str | None = None,
    actor_id: str = "user-1",
    activity_type: ExporterActivityType = ExporterActivityType.FOLLOW_UP,
) -> uuid.UUID:
    """An activity with a due date — which is what makes it a follow-up."""
    async with db_services.AsyncSessionLocal() as db:
        activity = await ExporterContactActivityService(db).log_activity(
            company_id,
            activity_type=activity_type,
            subject=subject or f"Follow up {uuid.uuid4().hex[:8]}",
            due_at=_at(due_in_days),
            actor_id=actor_id,
        )
    return activity.id


async def _plain_activity(company_id: uuid.UUID) -> uuid.UUID:
    """An activity with **no** due date — a record of something that happened."""
    async with db_services.AsyncSessionLocal() as db:
        activity = await ExporterContactActivityService(db).log_activity(
            company_id,
            activity_type=ExporterActivityType.CALL,
            subject="Intro call, nothing promised",
            actor_id="user-1",
        )
    return activity.id


async def _complete(activity_id: uuid.UUID, outcome: FollowUpOutcome, **kwargs):
    async with db_services.AsyncSessionLocal() as db:
        return await FollowUpService(db).complete_follow_up(
            activity_id, outcome, actor_id=kwargs.pop("actor_id", "user-1"), **kwargs
        )


async def _list(**kwargs):
    async with db_services.AsyncSessionLocal() as db:
        return await FollowUpService(db).list_follow_ups(**kwargs)


# ── Completing a follow-up ───────────────────────────────────────────────────


async def test_completing_a_follow_up_inserts_a_record_and_never_touches_the_activity():
    """Architecture §9.3's first "Watch out for". The activity is append-only, so the
    proof is that every one of its columns is byte-identical afterwards — not merely
    that no exception was raised."""
    company_id = await _company()
    activity_id = await _follow_up(company_id, due_in_days=-2)

    async with db_services.AsyncSessionLocal() as db:
        before = await db.scalar(
            select(ExporterActivity).where(ExporterActivity.id == activity_id)
        )
        snapshot = {
            c.name: getattr(before, c.name) for c in ExporterActivity.__table__.columns
        }

    completion = await _complete(activity_id, FollowUpOutcome.DONE, note="Spoke to the CFO")

    assert completion.activity_id == activity_id
    assert completion.customer_id == company_id
    assert completion.outcome is FollowUpOutcome.DONE
    assert completion.note == "Spoke to the CFO"
    assert completion.completed_by == "user-1"
    assert completion.next_due_at is None

    async with db_services.AsyncSessionLocal() as db:
        after = await db.scalar(
            select(ExporterActivity).where(ExporterActivity.id == activity_id)
        )
        assert {
            c.name: getattr(after, c.name) for c in ExporterActivity.__table__.columns
        } == snapshot


async def test_the_company_comes_from_the_activity_not_the_caller():
    """`customer_id` is denormalised (contract §5.2), and the only honest source is the
    activity: a caller-supplied company could disagree with it, and the row would then
    put a completion on the wrong company's list."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    completion = await _complete(activity_id, FollowUpOutcome.DONE)
    assert completion.customer_id == company_id


async def test_a_second_completion_is_refused_and_names_the_first():
    """A refusal, never an upsert (contract §5.4). The error carries the existing
    completion's id and outcome so a screen can say what is already recorded rather
    than only that the write failed."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    first = await _complete(activity_id, FollowUpOutcome.DONE)

    with pytest.raises(FollowUpAlreadyCompletedError) as caught:
        await _complete(activity_id, FollowUpOutcome.CANCELLED)
    assert caught.value.error_code == "FOLLOW_UP_ALREADY_COMPLETED"
    assert caught.value.status_code == 409
    assert caught.value.extensions["completion_id"] == str(first.id)
    assert caught.value.extensions["outcome"] == "DONE"

    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(FollowUpCompletion).where(FollowUpCompletion.activity_id == activity_id)
            )
        ).scalars().all()
    assert len(rows) == 1


async def test_an_activity_with_no_due_date_is_not_a_follow_up():
    """A due date is the append-only log's stand-in for "somebody promised to do
    this". A logged call with no due date has nothing outstanding to complete, and a
    completion against it would put a row on the Follow-ups list that was never on
    it."""
    company_id = await _company()
    activity_id = await _plain_activity(company_id)
    with pytest.raises(ActivityIsNotAFollowUpError) as caught:
        await _complete(activity_id, FollowUpOutcome.DONE)
    assert caught.value.error_code == "ACTIVITY_IS_NOT_A_FOLLOW_UP"


async def test_completing_an_activity_that_does_not_exist_is_a_404():
    """Distinct from the refusal above on purpose: "no such activity" and "that is not
    a follow-up" send a person looking in different places."""
    with pytest.raises(FollowUpNotFoundError) as caught:
        await _complete(uuid.uuid4(), FollowUpOutcome.DONE)
    assert caught.value.status_code == 404


# ── Rescheduling ─────────────────────────────────────────────────────────────


async def test_rescheduling_logs_a_new_follow_up_and_leaves_the_original_alone():
    """A reschedule is a new activity, not a moved date. Nothing may change an
    activity's `due_at`, and nothing should: the old row is the record of what was
    promised, and the promise did get broken."""
    company_id = await _company()
    activity_id = await _follow_up(company_id, due_in_days=-1, subject="Review the forecast")
    new_due = _at(21)

    completion = await _complete(
        activity_id, FollowUpOutcome.RESCHEDULED, next_due_at=new_due, note="Asked for 3 weeks"
    )
    assert completion.next_due_at is not None

    async with db_services.AsyncSessionLocal() as db:
        activities = (
            await db.execute(
                select(ExporterActivity)
                .where(ExporterActivity.customer_id == company_id)
                .order_by(ExporterActivity.due_at.asc())
            )
        ).scalars().all()

    assert len(activities) == 2
    original, replacement = activities
    assert original.id == activity_id
    assert original.due_at < datetime.now(UTC)  # untouched
    # The replacement keeps the subject, so the list reads as one continuing promise.
    assert replacement.subject == "Review the forecast"
    assert replacement.due_at is not None
    assert replacement.due_at > datetime.now(UTC)
    assert replacement.activity_type is ExporterActivityType.FOLLOW_UP
    assert "Rescheduled from" in (replacement.notes or "")


async def test_a_reschedule_leaves_the_original_done_and_the_replacement_outstanding():
    """The pair, as the screen sees it. A reschedule that left nothing behind would be
    a follow-up quietly dropped, which is what this list exists to prevent."""
    company_id = await _company()
    activity_id = await _follow_up(company_id, due_in_days=-1)
    await _complete(activity_id, FollowUpOutcome.RESCHEDULED, next_due_at=_at(14))

    view = await _list(customer_id=company_id)
    by_state = {row.state for row in view.follow_ups}
    assert by_state == {FollowUpState.DONE, FollowUpState.OUTSTANDING}
    assert view.follow_ups_total == 2


async def test_rescheduling_without_a_new_date_is_refused():
    """Rescheduling to nowhere is how a follow-up gets dropped.
    `ck_follow_up_completion_next_due` would refuse the row too; this refuses it with a
    code a screen can act on."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    with pytest.raises(FollowUpRescheduleNeedsDateError) as caught:
        await _complete(activity_id, FollowUpOutcome.RESCHEDULED)
    assert caught.value.error_code == "FOLLOW_UP_RESCHEDULE_NEEDS_DATE"
    assert await _completion_count(activity_id) == 0


async def test_rescheduling_into_the_past_is_refused():
    """A follow-up rescheduled backwards arrives already overdue, which is never what
    the person meant and makes the overdue count untrustworthy."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    with pytest.raises(FollowUpRescheduleInPastError) as caught:
        await _complete(activity_id, FollowUpOutcome.RESCHEDULED, next_due_at=_at(-1))
    assert caught.value.error_code == "FOLLOW_UP_RESCHEDULE_IN_PAST"
    assert await _completion_count(activity_id) == 0


@pytest.mark.parametrize(
    "outcome", [FollowUpOutcome.DONE, FollowUpOutcome.NO_ANSWER, FollowUpOutcome.CANCELLED]
)
async def test_a_next_due_date_on_any_other_outcome_is_refused_not_ignored(outcome):
    """Silently dropping it would leave the operator believing the follow-up had been
    moved rather than closed — the same reasoning as the conversation gauge's
    check-back date."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    with pytest.raises(FollowUpNextDueNotAllowedError) as caught:
        await _complete(activity_id, outcome, next_due_at=_at(7))
    assert caught.value.error_code == "FOLLOW_UP_NEXT_DUE_NOT_ALLOWED"
    assert await _completion_count(activity_id) == 0


async def test_a_refused_reschedule_leaves_no_replacement_activity_behind():
    """One transaction: the completion and its replacement commit together or not at
    all, so a refusal cannot leave an orphan follow-up on the list."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    with pytest.raises(FollowUpRescheduleNeedsDateError):
        await _complete(activity_id, FollowUpOutcome.RESCHEDULED)

    async with db_services.AsyncSessionLocal() as db:
        count = len(
            (
                await db.execute(
                    select(ExporterActivity).where(ExporterActivity.customer_id == company_id)
                )
            ).scalars().all()
        )
    assert count == 1


async def _completion_count(activity_id: uuid.UUID) -> int:
    async with db_services.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(FollowUpCompletion).where(FollowUpCompletion.activity_id == activity_id)
            )
        ).scalars().all()
    return len(rows)


# ── The lock, at the layers Phase 2 owns ─────────────────────────────────────


async def test_the_repository_exposes_no_way_to_change_a_completion():
    """What Phase 2 owes in place of a new direct-SQL constraint test (prompt §3).

    `FollowUpCompletionRepository` extends `AppendOnlyRepository`, which defines no
    `update` and no `delete`. Asserted rather than trusted, because the failure mode is
    somebody adding one later and nothing noticing.
    """
    async with db_services.AsyncSessionLocal() as db:
        repo = FollowUpCompletionRepository(db)
        assert not hasattr(repo, "update")
        assert not hasattr(repo, "delete")


async def test_the_service_refuses_an_attempt_to_edit_a_completion_with_a_clean_error():
    """A 409 naming the rule, not a 500 carrying a Postgres message. There is no route
    that reaches this and there never will be one; the refusal is a named, tested
    behaviour so that an absence nobody guards does not become a route later."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    completion = await _complete(activity_id, FollowUpOutcome.DONE)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(FollowUpCompletionIsImmutableError) as caught:
            await FollowUpService(db).refuse_completion_edit(completion.id)
    assert caught.value.error_code == "FOLLOW_UP_COMPLETION_IMMUTABLE"
    assert caught.value.status_code == 409


async def test_the_database_still_refuses_an_update_through_the_orm():
    """Belt and braces at the third layer: even a session that is handed the mapped
    object and told to change it cannot, because the trigger raises. This is the one
    that would catch somebody bypassing the repository.
    """
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    completion = await _complete(activity_id, FollowUpOutcome.DONE)

    async with db_services.AsyncSessionLocal() as db:
        row = await db.scalar(
            select(FollowUpCompletion).where(FollowUpCompletion.id == completion.id)
        )
        row.note = "tampered"
        with pytest.raises(Exception) as caught:  # noqa: B017 — driver-level, see below
            await db.commit()
    # `prevent_mutation()` raises a plpgsql exception, which SQLAlchemy wraps; the
    # message is what identifies it, and Phase 1's direct-SQL test asserts the
    # `RaiseException` class itself.
    assert "immutable" in str(caught.value).lower()


# ── The due/overdue read model ───────────────────────────────────────────────


async def test_outstanding_overdue_and_done_are_each_what_the_contract_says():
    """Contract §5.6 and prompt §7.1, in one place: outstanding is the *absence* of a
    completion row, overdue narrows it, and done is the presence of one."""
    company_id = await _company()
    overdue_id = await _follow_up(company_id, due_in_days=-5)
    upcoming_id = await _follow_up(company_id, due_in_days=5)
    done_id = await _follow_up(company_id, due_in_days=-9)
    await _complete(done_id, FollowUpOutcome.DONE)

    view = await _list(customer_id=company_id)
    by_id = {row.activity_id: row for row in view.follow_ups}

    assert by_id[overdue_id].state is FollowUpState.OVERDUE
    assert by_id[overdue_id].is_overdue is True
    assert by_id[overdue_id].completion is None

    assert by_id[upcoming_id].state is FollowUpState.OUTSTANDING
    assert by_id[upcoming_id].is_overdue is False

    assert by_id[done_id].state is FollowUpState.DONE
    # Done late, and therefore not overdue.
    assert by_id[done_id].is_overdue is False
    assert by_id[done_id].completion is not None
    assert by_id[done_id].completion.completed_by == "user-1"


async def test_an_activity_with_no_due_date_is_not_on_the_list_at_all():
    company_id = await _company()
    await _plain_activity(company_id)
    view = await _list(customer_id=company_id)
    assert view.follow_ups == ()
    assert view.follow_ups_total == 0


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (FollowUpState.OVERDUE, {"overdue"}),
        (FollowUpState.OUTSTANDING, {"overdue", "upcoming"}),
        (FollowUpState.DONE, {"done"}),
        (None, {"overdue", "upcoming", "done"}),
    ],
)
async def test_the_state_filter_selects_what_its_name_says(state, expected):
    """`OUTSTANDING` includes the overdue one, because overdue narrows outstanding
    rather than sitting beside it — the distinction a reader is most likely to get
    wrong."""
    company_id = await _company()
    ids = {
        "overdue": await _follow_up(company_id, due_in_days=-4, subject="overdue"),
        "upcoming": await _follow_up(company_id, due_in_days=4, subject="upcoming"),
        "done": await _follow_up(company_id, due_in_days=-8, subject="done"),
    }
    await _complete(ids["done"], FollowUpOutcome.DONE)

    view = await _list(customer_id=company_id, state=state)
    assert {row.subject for row in view.follow_ups} == expected
    assert view.follow_ups_total == len(expected)


async def test_the_list_is_soonest_due_first_so_overdue_sorts_to_the_front():
    company_id = await _company()
    await _follow_up(company_id, due_in_days=6, subject="later")
    await _follow_up(company_id, due_in_days=-9, subject="long overdue")
    await _follow_up(company_id, due_in_days=1, subject="soon")

    view = await _list(customer_id=company_id)
    assert [row.subject for row in view.follow_ups] == ["long overdue", "soon", "later"]


async def test_the_list_carries_the_company_name_without_a_second_query():
    """One join, never an N+1 — the same acceptance criterion `list_pending` has."""
    company_id = await _company()
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile.name = "Coastal Seafood Exports Pvt Ltd"
        await db.commit()
    await _follow_up(company_id)

    view = await _list(customer_id=company_id)
    assert view.follow_ups[0].exporter_display_name == "Coastal Seafood Exports Pvt Ltd"


async def test_the_total_counts_the_filter_not_the_page():
    """So a caller can tell whether there is more without asking for it."""
    company_id = await _company()
    for i in range(4):
        await _follow_up(company_id, due_in_days=i + 1, subject=f"f{i}")

    view = await _list(customer_id=company_id, limit=2)
    assert len(view.follow_ups) == 2
    assert view.follow_ups_total == 4


async def test_filtering_by_actor_narrows_the_list_and_does_not_gate_it():
    """Decision D2: follow-ups are the whole team's. `actor_id` is a query parameter,
    not a permission — so the unfiltered list shows everyone's."""
    company_id = await _company()
    await _follow_up(company_id, subject="mine", actor_id="user-1")
    await _follow_up(company_id, subject="theirs", actor_id="user-2")

    everyone = await _list(customer_id=company_id)
    assert {row.subject for row in everyone.follow_ups} == {"mine", "theirs"}

    mine = await _list(customer_id=company_id, actor_id="user-1")
    assert {row.subject for row in mine.follow_ups} == {"mine"}


# ── Check-backs: read-only, from the conversation gauge ──────────────────────


async def test_a_company_parked_at_not_now_appears_as_a_check_back():
    """Phase 1's check-back date is what puts a company on this list
    (`engagement.md` §4). It is not a follow-up: there is no activity and no
    completion, and it is dealt with by moving the gauge."""
    company_id = await _company()
    check_back = (datetime.now(UTC) + timedelta(days=30)).date()
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id,
            ExporterConversation.NOT_NOW,
            reason="Budget frozen until April",
            check_back_on=check_back,
            actor_id="user-1",
        )

    view = await _list(customer_id=company_id)
    [row] = view.check_backs
    assert row.customer_id == company_id
    assert row.check_back_on == check_back
    assert row.conversation is ExporterConversation.NOT_NOW
    assert row.is_overdue is False
    assert view.check_backs_total == 1
    # And it is not a follow-up.
    assert view.follow_ups == ()


async def test_moving_the_gauge_off_not_now_takes_the_check_back_off_the_list():
    """The reason the check-back date has a CHECK tying it to `NOT_NOW`: a stale date
    would keep a company on this list for a conversation that has moved on. Phase 2
    never writes the date — the gauge clears it."""
    company_id = await _company()
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id,
            ExporterConversation.NOT_NOW,
            reason="Not now",
            check_back_on=(datetime.now(UTC) + timedelta(days=30)).date(),
            actor_id="user-1",
        )
    assert (await _list(customer_id=company_id)).check_backs_total == 1

    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id, ExporterConversation.READY_NOW, actor_id="user-1"
        )

    view = await _list(customer_id=company_id)
    assert view.check_backs == ()
    assert view.check_backs_total == 0


async def test_check_backs_can_be_left_out_entirely():
    company_id = await _company()
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id,
            ExporterConversation.NOT_NOW,
            reason="Not now",
            check_back_on=(datetime.now(UTC) + timedelta(days=5)).date(),
            actor_id="user-1",
        )
    view = await _list(customer_id=company_id, include_check_backs=False)
    assert view.check_backs == ()
    assert view.check_backs_total == 0


# ── The routes ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {
        role: await token_with_role(client, role)
        for role in (UserRole.OPERATIONS, UserRole.DEVELOPER)
    }


async def test_the_list_route_serves_both_lists(client: AsyncClient, tokens):
    company_id = await _company()
    activity_id = await _follow_up(company_id, due_in_days=-3, subject="Chase the accounts")
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id,
            ExporterConversation.NOT_NOW,
            reason="Not now",
            check_back_on=(datetime.now(UTC) + timedelta(days=10)).date(),
            actor_id="user-1",
        )

    resp = await client.get(
        f"{BASE}/follow-ups?customer_id={company_id}",
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [row] = body["follow_ups"]
    assert row["activity_id"] == str(activity_id)
    assert row["state"] == "OVERDUE"
    assert row["is_overdue"] is True
    assert row["completion"] is None
    assert body["follow_ups_total"] == 1
    assert len(body["check_backs"]) == 1
    assert body["check_backs"][0]["conversation"] == "NOT_NOW"


async def test_the_completion_route_records_and_returns_the_record(client: AsyncClient, tokens):
    company_id = await _company()
    activity_id = await _follow_up(company_id)

    resp = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "DONE", "note": "Spoke to the CFO"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["activity_id"] == str(activity_id)
    assert body["customer_id"] == str(company_id)
    assert body["outcome"] == "DONE"
    assert body["note"] == "Spoke to the CFO"
    assert body["next_due_at"] is None
    # From the session, never the body: a real user id, not the string "user-1".
    assert body["completed_by"]
    assert body["completed_by"] != "user-1"


async def test_the_completed_follow_up_then_reads_as_done(client: AsyncClient, tokens):
    company_id = await _company()
    activity_id = await _follow_up(company_id, due_in_days=-2)
    headers = auth_header(tokens[UserRole.OPERATIONS])
    await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "NO_ANSWER"},
        headers=headers,
    )
    resp = await client.get(f"{BASE}/follow-ups?customer_id={company_id}", headers=headers)
    [row] = resp.json()["follow_ups"]
    assert row["state"] == "DONE"
    assert row["is_overdue"] is False
    assert row["completion"]["outcome"] == "NO_ANSWER"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"outcome": "RESCHEDULED"}, 422, "FOLLOW_UP_RESCHEDULE_NEEDS_DATE"),
        (
            {"outcome": "RESCHEDULED", "next_due_at": "2020-01-01T00:00:00Z"},
            422,
            "FOLLOW_UP_RESCHEDULE_IN_PAST",
        ),
        (
            {"outcome": "DONE", "next_due_at": "2099-01-01T00:00:00Z"},
            422,
            "FOLLOW_UP_NEXT_DUE_NOT_ALLOWED",
        ),
    ],
)
async def test_the_route_refuses_with_the_documented_error_code(
    client: AsyncClient, tokens, body, status, code
):
    """§7.7: at least one test for each refusal, and each reaching the caller as the
    code the contract names rather than a bare 422."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    resp = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json=body,
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == status, resp.text
    assert resp.json()["error_code"] == code


async def test_the_route_refuses_a_second_completion(client: AsyncClient, tokens):
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    headers = auth_header(tokens[UserRole.OPERATIONS])
    first = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "DONE"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "CANCELLED"},
        headers=headers,
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "FOLLOW_UP_ALREADY_COMPLETED"


async def test_the_route_refuses_an_activity_that_is_not_a_follow_up(client: AsyncClient, tokens):
    company_id = await _company()
    activity_id = await _plain_activity(company_id)
    resp = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "DONE"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "ACTIVITY_IS_NOT_A_FOLLOW_UP"


async def test_the_route_404s_for_an_activity_that_does_not_exist(client: AsyncClient, tokens):
    resp = await client.post(
        f"{BASE}/follow-ups/{uuid.uuid4()}/completion",
        json={"outcome": "DONE"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "FOLLOW_UP_NOT_FOUND"


async def test_the_actor_cannot_be_supplied_in_the_body(client: AsyncClient, tokens):
    """Architecture §7.5. `extra="forbid"` makes an attempt a 422 rather than silently
    ignored, so a completion can never name somebody the caller chose."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    resp = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "DONE", "completed_by": "somebody-else"},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 422, resp.text
    assert await _completion_count(activity_id) == 0


async def test_a_developer_may_read_the_list_and_complete_nothing(client: AsyncClient, tokens):
    """Contract §5.5. The read is the whole team's; the write is not DEVELOPER's.
    Together with the refusal rows under the `3A·2` anchor in
    `test_route_authorization.py`, this covers the role gate from both sides."""
    company_id = await _company()
    activity_id = await _follow_up(company_id)
    headers = auth_header(tokens[UserRole.DEVELOPER])

    read = await client.get(f"{BASE}/follow-ups?customer_id={company_id}", headers=headers)
    assert read.status_code == 200, read.text
    assert len(read.json()["follow_ups"]) == 1

    write = await client.post(
        f"{BASE}/follow-ups/{activity_id}/completion",
        json={"outcome": "DONE"},
        headers=headers,
    )
    assert write.status_code == 403, write.text
    assert write.json()["error_code"] == "FORBIDDEN"


async def test_there_is_no_route_that_edits_or_deletes_a_completion():
    """The absence, asserted. Both tables are append-only, and a correction is a new
    activity plus its own completion — so a PATCH or DELETE here would be a way to
    rewrite what somebody recorded.

    Read off Phase 2's own router rather than the mounted application: `importlinter`
    forbids a module from importing the delivery layer (`app.main` pulls in
    `app.api.rest.router`), and this router is the truer scope anyway — it is the only
    file such a route could be added to.
    """
    from app.modules.onboarding.api.follow_up_router import router

    declared = {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    assert declared == {
        ("GET", "/follow-ups"),
        ("POST", "/follow-ups/{activity_id}/completion"),
    }, declared


# ── Sample data ──────────────────────────────────────────────────────────────


async def test_the_sample_seeder_covers_all_three_states_and_converges():
    """A Follow-ups screen with one outstanding row demonstrates neither overdue nor
    done, which is why the seeder logs its own follow-ups rather than relying on
    Developer 2's single one. Converges like every other step in `sample_data.py`: the
    second run records nothing."""
    from app.modules.onboarding.sample_data import COMPANIES, load_sample_data
    from app.modules.onboarding.sample_data_follow_ups import load_follow_up_sample_data

    await load_sample_data()
    assert await load_follow_up_sample_data() == 0  # already done by load_sample_data

    # Scoped per sample company rather than read off the unfiltered list: this suite
    # shares a database with every other test that logs a follow-up, and the
    # unfiltered first page is soonest-due first, so a seeded row due next week sits
    # behind hundreds of others. Asking each company for its own follow-ups is both
    # precise and independent of how much else is in the database.
    seeded = [
        row
        for company in COMPANIES
        for row in (await _list(customer_id=company.customer_id)).follow_ups
        if row.notes is not None and "Sample data" in row.notes
    ]
    states = {row.state for row in seeded}
    assert states == {
        FollowUpState.OVERDUE,
        FollowUpState.OUTSTANDING,
        FollowUpState.DONE,
    }, states
