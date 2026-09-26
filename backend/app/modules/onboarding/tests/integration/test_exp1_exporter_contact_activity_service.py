"""Integration tests for EXP-1's `ExporterContactActivityService`."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.modules.onboarding.application.exporter_contact_activity_service import (
    ExporterContactActivityService,
)
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


@contextmanager
def _count_queries():
    """A one-off statement counter — this codebase has no established
    query-count-assertion convention (checked: no `query_count`/
    `before_cursor_execute` fixture anywhere in the test suite), so this is
    built locally for `test_list_pending_activities_has_no_n_plus_one` rather
    than invented as a new shared fixture other tests don't use yet."""
    counter = {"n": 0}

    def _on_execute(*_args, **_kwargs):
        counter["n"] += 1

    engine = db_services.engine.sync_engine
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


# ── Contacts ──────────────────────────────────────────────────────────────────


async def test_add_contact_creates_record():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        contact = await ExporterContactActivityService(db).add_contact(
            customer_id, name="Jane Doe", role="CFO", email="jane@example.com"
        )

    assert contact.customer_id == customer_id
    assert contact.name == "Jane Doe"
    assert contact.is_primary_contact is False


async def test_add_contact_second_primary_demotes_first():
    """Service-level half of the acceptance criterion: setting a second
    contact as primary demotes the first — never two primaries at once. The
    direct-SQL half lives in test_exp1_exporter_crm_schema.py."""
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        svc = ExporterContactActivityService(db)
        first = await svc.add_contact(customer_id, name="Jane Doe", is_primary=True)
        second = await svc.add_contact(customer_id, name="John Smith", is_primary=True)

    async with db_services.AsyncSessionLocal() as db:
        contacts = await ExporterContactActivityService(db).list_contacts(customer_id)

    by_id = {c.id: c for c in contacts}
    assert by_id[first.id].is_primary_contact is False
    assert by_id[second.id].is_primary_contact is True
    assert sum(1 for c in contacts if c.is_primary_contact) == 1


async def test_list_contacts_returns_all_for_customer():
    customer_id = uuid.uuid4()
    other_customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        svc = ExporterContactActivityService(db)
        await svc.add_contact(customer_id, name="Contact A")
        await svc.add_contact(customer_id, name="Contact B")
        await svc.add_contact(other_customer_id, name="Unrelated Contact")

    async with db_services.AsyncSessionLocal() as db:
        contacts = await ExporterContactActivityService(db).list_contacts(customer_id)

    assert {c.name for c in contacts} == {"Contact A", "Contact B"}


# ── Activities ────────────────────────────────────────────────────────────────


async def test_log_activity_creates_entry():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        activity = await ExporterContactActivityService(db).log_activity(
            customer_id,
            activity_type=ExporterActivityType.CALL,
            subject="Intro call",
            actor_id="agent_1",
        )

    assert activity.customer_id == customer_id
    assert activity.activity_type == ExporterActivityType.CALL
    assert activity.actor_id == "agent_1"
    assert activity.occurred_at is not None


async def test_log_activity_with_due_at_for_follow_up():
    customer_id = uuid.uuid4()
    due = datetime.now(UTC) + timedelta(days=3)
    async with db_services.AsyncSessionLocal() as db:
        activity = await ExporterContactActivityService(db).log_activity(
            customer_id,
            activity_type=ExporterActivityType.FOLLOW_UP,
            subject="Send pricing sheet",
            actor_id="agent_1",
            due_at=due,
        )

    assert activity.due_at is not None
    assert activity.due_at.date() == due.date()


async def test_list_activities_filters_by_type_and_orders_recent_first():
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        svc = ExporterContactActivityService(db)
        await svc.log_activity(
            customer_id, activity_type=ExporterActivityType.CALL, subject="Call 1", actor_id="a"
        )
        await svc.log_activity(
            customer_id, activity_type=ExporterActivityType.NOTE, subject="Note 1", actor_id="a"
        )
        await svc.log_activity(
            customer_id, activity_type=ExporterActivityType.CALL, subject="Call 2", actor_id="a"
        )

    async with db_services.AsyncSessionLocal() as db:
        calls_only = await ExporterContactActivityService(db).list_activities(
            customer_id, activity_type=ExporterActivityType.CALL
        )
        everything = await ExporterContactActivityService(db).list_activities(customer_id)

    assert {a.subject for a in calls_only} == {"Call 1", "Call 2"}
    assert len(everything) == 3
    # Most recent first.
    assert everything[0].subject == "Call 2"


# ── Pending activities (Piece 2: cross-exporter follow-up list) ───────────────


async def test_list_pending_activities_marks_past_due_as_overdue():
    customer_id = uuid.uuid4()
    actor_id = f"agent-{uuid.uuid4().hex[:8]}"
    past_due = datetime.now(UTC) - timedelta(days=1)
    future_due = datetime.now(UTC) + timedelta(days=5)

    async with db_services.AsyncSessionLocal() as db:
        svc = ExporterContactActivityService(db)
        await svc.log_activity(
            customer_id, activity_type=ExporterActivityType.FOLLOW_UP,
            subject="Overdue follow-up", actor_id=actor_id, due_at=past_due,
        )
        await svc.log_activity(
            customer_id, activity_type=ExporterActivityType.TASK,
            subject="Upcoming task", actor_id=actor_id, due_at=future_due,
        )
        # No due_at at all: never a "pending" item.
        await svc.log_activity(
            customer_id, activity_type=ExporterActivityType.NOTE,
            subject="Just a note", actor_id=actor_id,
        )

    async with db_services.AsyncSessionLocal() as db:
        pending = await ExporterContactActivityService(db).list_pending_activities(
            actor_id=actor_id
        )

    by_subject = {p.subject: p for p in pending}
    assert "Just a note" not in by_subject
    assert by_subject["Overdue follow-up"].is_overdue is True
    assert by_subject["Upcoming task"].is_overdue is False
    # Soonest-due (most overdue) first.
    assert pending[0].subject == "Overdue follow-up"


async def test_list_pending_activities_filters_by_actor_id():
    actor_a = f"agent-a-{uuid.uuid4().hex[:8]}"
    actor_b = f"agent-b-{uuid.uuid4().hex[:8]}"
    due = datetime.now(UTC) + timedelta(days=1)

    async with db_services.AsyncSessionLocal() as db:
        svc = ExporterContactActivityService(db)
        await svc.log_activity(
            uuid.uuid4(), activity_type=ExporterActivityType.TASK,
            subject="A's task", actor_id=actor_a, due_at=due,
        )
        await svc.log_activity(
            uuid.uuid4(), activity_type=ExporterActivityType.TASK,
            subject="B's task", actor_id=actor_b, due_at=due,
        )

    async with db_services.AsyncSessionLocal() as db:
        for_a = await ExporterContactActivityService(db).list_pending_activities(
            actor_id=actor_a
        )

    subjects = {p.subject for p in for_a}
    assert "A's task" in subjects
    assert "B's task" not in subjects
    assert all(p.actor_id == actor_a for p in for_a)


async def test_list_pending_activities_carries_exporter_display_name():
    """The exporter's display name (resolved via OnboardingRequest.legal_name,
    same join `search_profiles` already uses) is present on the row directly
    — no follow-up query needed to answer "pending, for which exporter"."""
    legal_name = f"Pending List Exporter {uuid.uuid4().hex[:8]}"
    actor_id = f"agent-{uuid.uuid4().hex[:8]}"

    async with db_services.AsyncSessionLocal() as db:
        request, _identity, _created = await ExporterProfileService(db).create_lead(
            name=legal_name,
            country="US",
            created_by_email="rep@example.com",
            idempotency_key=str(uuid.uuid4()),
            source=ExporterSource.SALES,
        )

    async with db_services.AsyncSessionLocal() as db:
        await ExporterContactActivityService(db).log_activity(
            request.customer_id, activity_type=ExporterActivityType.FOLLOW_UP,
            subject="Follow up with named exporter", actor_id=actor_id,
            due_at=datetime.now(UTC) + timedelta(days=1),
        )

    async with db_services.AsyncSessionLocal() as db:
        pending = await ExporterContactActivityService(db).list_pending_activities(
            actor_id=actor_id
        )

    assert len(pending) == 1
    assert pending[0].exporter_display_name == legal_name
    assert pending[0].customer_id == request.customer_id


async def test_list_pending_activities_has_no_n_plus_one():
    """Correctness *and* the no-N+1 acceptance criterion: fetching several
    exporters' worth of pending items issues one statement for the activities
    (joined to their display names), not one additional query per row."""
    actor_id = f"agent-{uuid.uuid4().hex[:8]}"
    due = datetime.now(UTC) + timedelta(hours=1)

    async with db_services.AsyncSessionLocal() as db:
        svc = ExporterContactActivityService(db)
        for i in range(5):
            profile_db_customer_id = uuid.uuid4()
            await svc.log_activity(
                profile_db_customer_id, activity_type=ExporterActivityType.TASK,
                subject=f"Task {i}", actor_id=actor_id, due_at=due,
            )

    async with db_services.AsyncSessionLocal() as db:
        with _count_queries() as counter:
            pending = await ExporterContactActivityService(db).list_pending_activities(
                actor_id=actor_id
            )

    assert len(pending) == 5
    # Exactly one statement for the whole list, regardless of row count.
    assert counter["n"] == 1
