"""ANER-4.3-S3T3: `CaseNoteService.add_case_note` against a real database."""
from __future__ import annotations

import uuid

import pytest

from app.modules.cases.application.case_note_service import MAX_NOTE_LENGTH, CaseNoteService
from app.modules.cases.domain.entities.enums import ActorType
from app.modules.cases.exceptions import (
    CaseIsTerminalError,
    CaseNotFoundError,
    UserNotFoundOrInactiveError,
)
from app.modules.cases.tests.fixtures.auth_fixtures import create_user
from app.modules.cases.tests.fixtures.case_sql import fetchone, insert_case
from app.platform.database import services as database
from app.shared.exceptions import ValidationError


@pytest.fixture
def service() -> CaseNoteService:
    return CaseNoteService()


async def test_add_note_appears_on_timeline_with_actor_and_timestamp(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    author = await create_user()

    async with database.AsyncSessionLocal() as session:
        event = await service.add_case_note(
            session, uuid.UUID(case["id"]), "Reviewed the KYB extract.", author, ActorType.COMPLIANCE_OFFICER
        )

    assert event.note == "Reviewed the KYB extract."
    assert event.actor_id == author
    assert event.occurred_at is not None

    row = fetchone(
        "SELECT event_type, note, actor_id FROM cases.case_timeline_event WHERE case_id = %s",
        (case["id"],),
    )
    assert row == ("NOTE_ADDED", "Reviewed the KYB extract.", author)


async def test_add_note_does_not_change_case_status(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    author = await create_user()

    async with database.AsyncSessionLocal() as session:
        await service.add_case_note(
            session, uuid.UUID(case["id"]), "A note.", author, ActorType.COMPLIANCE_OFFICER
        )

    row = fetchone("SELECT case_status FROM cases.compliance_case WHERE id = %s", (case["id"],))
    assert row == ("UNDER_INVESTIGATION",)


async def test_add_note_updates_last_updated_at(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    author = await create_user()
    before = fetchone("SELECT last_updated_at FROM cases.compliance_case WHERE id = %s", (case["id"],))[0]

    async with database.AsyncSessionLocal() as session:
        await service.add_case_note(
            session, uuid.UUID(case["id"]), "A note.", author, ActorType.COMPLIANCE_OFFICER
        )

    after = fetchone("SELECT last_updated_at FROM cases.compliance_case WHERE id = %s", (case["id"],))[0]
    assert after > before


async def test_add_note_rejects_empty_note(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    author = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.add_case_note(session, uuid.UUID(case["id"]), "", author, ActorType.COMPLIANCE_OFFICER)


async def test_add_note_rejects_whitespace_only_note(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    author = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.add_case_note(
                session, uuid.UUID(case["id"]), "   \n\t ", author, ActorType.COMPLIANCE_OFFICER
            )


async def test_add_note_rejects_a_note_over_the_max_length(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    author = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(ValidationError):
            await service.add_case_note(
                session,
                uuid.UUID(case["id"]),
                "x" * (MAX_NOTE_LENGTH + 1),
                author,
                ActorType.COMPLIANCE_OFFICER,
            )


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "CLOSED_WITHOUT_ACTION"])
async def test_add_note_rejected_on_a_terminal_case(service, terminal_status):
    """AC (doc, S3T3): a note may be added at any point in the lifecycle
    except terminal states."""
    case = insert_case(case_status=terminal_status)
    author = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseIsTerminalError):
            await service.add_case_note(
                session, uuid.UUID(case["id"]), "Too late.", author, ActorType.COMPLIANCE_OFFICER
            )


async def test_add_note_raises_for_an_unknown_case(service):
    author = await create_user()
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(CaseNotFoundError):
            await service.add_case_note(session, uuid.uuid4(), "A note.", author, ActorType.COMPLIANCE_OFFICER)


async def test_add_note_rejects_a_nonexistent_actor(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.add_case_note(
                session, uuid.UUID(case["id"]), "A note.", str(uuid.uuid4()), ActorType.COMPLIANCE_OFFICER
            )


async def test_add_note_rejects_an_inactive_actor(service):
    case = insert_case(case_status="UNDER_INVESTIGATION")
    inactive = await create_user(is_active=False)
    async with database.AsyncSessionLocal() as session:
        with pytest.raises(UserNotFoundOrInactiveError):
            await service.add_case_note(
                session, uuid.UUID(case["id"]), "A note.", inactive, ActorType.COMPLIANCE_OFFICER
            )
