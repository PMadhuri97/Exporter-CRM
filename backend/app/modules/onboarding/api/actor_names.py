"""Who acted, by name, for the CRM's list responses.

History rows, background-check decisions, activities and follow-ups store the person
who acted as a user id. Each response that carries one also carries the person's
display name (`actor_name`, `decided_by_name`), resolved here through the platform's
auth facade, so every staff role sees a name without being given the user list —
which `/auth/users` keeps to user management.

OPERATIONS, COMPLIANCE and ADMIN see the account's full name, or its email when it has
none. DEVELOPER sees the full name only: the architecture sets no masking rule for
staff, and a read-only role has no need of anyone's address. An id with no name to
show is served with the name `null`; the screen then shows what it showed before.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.authentication import display_names
from app.platform.authentication.models import User, UserRole


async def actor_names(
    db: AsyncSession, reader: User, actor_ids: Iterable[str | None]
) -> dict[str, str]:
    """`{actor_id: display name}` for the ids `reader` is about to be served."""
    return await display_names(
        db, actor_ids, email_fallback=reader.role != UserRole.DEVELOPER
    )


__all__ = ["actor_names"]
