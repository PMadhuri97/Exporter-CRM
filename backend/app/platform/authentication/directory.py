"""Who an actor id is, for a screen that shows it.

Records across the platform store the person who acted as `str(user.id)`. A reader
wants a name, not an id, and the user list (`/api/v1/auth/users`) is gated to user
management, which most staff do not have. This resolves the ids a caller is about to
serve into display names, in one query. It decides nothing about who may see a name:
the caller has already decided that its reader may see the record the id is on, and
chooses whether an account without a name may be shown by its email.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.authentication.models import User, UserRole


async def display_names(
    session: AsyncSession,
    actor_ids: Iterable[str | None],
    *,
    email_fallback: bool,
) -> dict[str, str]:
    """`{actor_id: name}` for every id that is a user's.

    The name is the account's `full_name`; an account with none is shown by its email
    when `email_fallback` is true, and left out otherwise. Ids that are not a user's —
    `None` (the platform itself), a string that is not a UUID, an account since
    removed — are simply absent, so the caller says "the platform" or falls back to the
    id as it did before. Keys are the ids exactly as given.
    """
    wanted: dict[str, uuid.UUID] = {}
    for actor_id in actor_ids:
        if not actor_id or actor_id in wanted:
            continue
        try:
            wanted[actor_id] = uuid.UUID(actor_id)
        except ValueError:
            continue
    if not wanted:
        return {}

    rows = await session.execute(
        select(User.id, User.full_name, User.email).where(User.id.in_(set(wanted.values())))
    )
    by_id = {row.id: row for row in rows}

    names: dict[str, str] = {}
    for actor_id, user_id in wanted.items():
        row = by_id.get(user_id)
        if row is None:
            continue
        name = (row.full_name or "").strip() or (row.email if email_fallback else "")
        if name:
            names[actor_id] = name
    return names


@dataclass(frozen=True)
class StaffMember:
    """An account as a staff picker or an assignment rule needs it: who, by name, in
    which built-in role, and whether it may still sign in. Never a password, token or
    custom-role detail."""

    id: str
    name: str
    role: UserRole
    is_active: bool


def _member(row) -> StaffMember:
    return StaffMember(
        id=str(row.id),
        name=(row.full_name or "").strip() or row.email,
        role=row.role,
        is_active=bool(row.is_active),
    )


async def staff_member(session: AsyncSession, user_id: str | None) -> StaffMember | None:
    """One account, or `None` for an id that is not a user's (or not a UUID)."""
    if not user_id:
        return None
    try:
        wanted = uuid.UUID(str(user_id))
    except ValueError:
        return None
    row = (
        await session.execute(
            select(User.id, User.full_name, User.email, User.role, User.is_active).where(
                User.id == wanted
            )
        )
    ).one_or_none()
    return _member(row) if row is not None else None


async def staff_members(
    session: AsyncSession, user_ids: Iterable[str | None]
) -> dict[str, StaffMember]:
    """`{id: member}` for every id that is a user's, active or not."""
    wanted: dict[str, uuid.UUID] = {}
    for user_id in user_ids:
        if not user_id or user_id in wanted:
            continue
        try:
            wanted[user_id] = uuid.UUID(str(user_id))
        except ValueError:
            continue
    if not wanted:
        return {}
    rows = await session.execute(
        select(User.id, User.full_name, User.email, User.role, User.is_active).where(
            User.id.in_(set(wanted.values()))
        )
    )
    by_id = {row.id: _member(row) for row in rows}
    return {key: by_id[value] for key, value in wanted.items() if value in by_id}


async def active_staff(session: AsyncSession, roles: Iterable[UserRole]) -> list[StaffMember]:
    """Every active account in one of `roles`, by name."""
    wanted = list(dict.fromkeys(roles))
    if not wanted:
        return []
    rows = await session.execute(
        select(User.id, User.full_name, User.email, User.role, User.is_active)
        .where(User.is_active.is_(True), User.role.in_(wanted))
        .order_by(User.full_name.asc().nulls_last(), User.email.asc())
    )
    return [_member(row) for row in rows]


__all__ = ["StaffMember", "active_staff", "display_names", "staff_member", "staff_members"]
