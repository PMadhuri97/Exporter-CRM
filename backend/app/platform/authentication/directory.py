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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.authentication.models import User


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


__all__ = ["display_names"]
