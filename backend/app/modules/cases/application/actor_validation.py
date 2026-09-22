"""Shared "is this a real, active platform user" check (ANER-4.3-S3T1/S3T3/S4T2).

`compliance_case.assigned_to` and `case_timeline_event.actor_id` are plain
strings with no foreign key to `auth.users` (S1T1's schema predates this
story and was never changed to add one — narrowing that would be a
migration this task does not need, since the columns already hold whatever
identity string a caller supplies). This task's brief is explicit that an id
should nonetheless be validated against `app.platform.authentication` as a
real, active user rather than treated as an opaque string — `app.platform.*`
is the one import this module is allowed outside its own tree
(ARCHITECTURE.md §6's exception to the cross-module import ban; `cases` still
imports nothing from `app.modules.*` elsewhere).

`require_active_user` mirrors `app.platform.authentication.dependencies.
get_current_user`'s own not-found/inactive checks (`UserRepository.get_by_id`
then `.is_active`) rather than inventing a second way to decide who counts as
a valid user.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.exceptions import UserNotFoundOrInactiveError
from app.platform.authentication.adapters.repository import UserRepository
from app.platform.authentication.models import User


async def require_active_user(session: AsyncSession, user_id: str, *, role: str) -> User:
    """Resolve `user_id` (a plain string, as stored on `assigned_to` /
    `actor_id`) to a real, active `auth.users` row.

    Args:
        role: a short label for which field is being validated (e.g.
            `"assignee"`, `"actor"`, `"proposer (proposed_by)"`, `"checker
            (checker_id)"`) — used only so `UserNotFoundOrInactiveError`'s
            message names the right field, not to change the check itself.

    Raises:
        UserNotFoundOrInactiveError: `user_id` is not a well-formed UUID, no
            `auth.users` row exists for it, or the row exists but
            `is_active` is `False`.
    """
    try:
        parsed = uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        raise UserNotFoundOrInactiveError(user_id, role) from None

    user = await UserRepository(session).get_by_id(parsed)
    if user is None or not user.is_active:
        raise UserNotFoundOrInactiveError(user_id, role)
    return user


__all__ = ["require_active_user"]
