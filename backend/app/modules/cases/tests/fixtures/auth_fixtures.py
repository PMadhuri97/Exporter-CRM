"""Test-only helper for creating `auth.users` rows, so the actor/assignee
validation added in ANER-4.3-S3T1/S3T3/S4T2 has real users to validate
against.

Uses the ORM directly, unlike `case_sql.py`'s raw-SQL convention: that
module's raw SQL exists specifically to prove Postgres enforces a constraint
the ORM would otherwise silently satisfy. Nothing here is proving a
constraint — it just needs a row to exist — and `app.platform.authentication`
is the one cross-module import this task's own services (and therefore their
tests) are allowed to make (ARCHITECTURE.md §6).

Each call opens its own short-lived session and commits immediately, mirroring
`case_sql.py`'s helpers (`insert_case`, etc.) being one-shot, synchronous-style
calls from the caller's point of view — just async, since there is no sync
driver wired up for `auth.users` the way `case_sql.py` uses psycopg2 for
`cases` schema tables.
"""
from __future__ import annotations

import uuid

from app.platform.authentication.models import User, UserRole
from app.platform.authentication.services import hash_password
from app.platform.database import services as database


async def create_user(*, is_active: bool = True, role: UserRole = UserRole.COMPLIANCE) -> str:
    """Insert a throwaway user and return its id as a string — matching how
    `compliance_case.assigned_to` / `case_timeline_event.actor_id` store ids.
    """
    async with database.AsyncSessionLocal() as session:
        user = User(
            email=f"test-{uuid.uuid4().hex[:12]}@aner-test.com",
            hashed_password=hash_password("Password1"),
            full_name="Test User",
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return str(user.id)


__all__ = ["create_user"]
