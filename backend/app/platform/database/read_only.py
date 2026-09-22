"""Read-only enforcement for the sessions query services run on.

BUILD.md #10 requires query services to be read-only *provably*, with database
credentials that cannot write. Credentials are the layer that actually enforces
it, but they only prove the property for the process holding them, and they fail
late — at the database, with a privilege error, after the code has already been
written and reviewed as though the write were legitimate.

Two cheaper guards sit in front of that one:

``READ_ONLY_CONNECT_ARGS``
    Opens every transaction on the connection as READ ONLY, so raw SQL is
    refused too — not only ORM writes. PostgreSQL rejects the statement with
    SQLSTATE 25006, which names the reason ("cannot execute INSERT in a
    read-only transaction") rather than merely denying permission.

``forbid_writes``
    Refuses at the ORM, before any SQL is emitted, naming the objects that were
    pending. This is the layer a developer meets first, and the only one whose
    error message can point at the mistake in Python rather than at a SQLSTATE.

None of the three is redundant. Remove the credentials and a bug becomes a
silent write; remove the transaction setting and raw SQL slips past the ORM
guard; remove the ORM guard and the same mistake surfaces as a database error
several layers from where it was made.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

#: asyncpg connect arguments that start every transaction on the connection as
#: READ ONLY. Applied per engine rather than per session: these engines are
#: dedicated to read-only roles, so there is no caller on the pool that a
#: connection-wide setting could surprise, and nothing has to remember to opt in.
READ_ONLY_CONNECT_ARGS = {"server_settings": {"default_transaction_read_only": "on"}}

#: PostgreSQL raises this when a write is attempted in a READ ONLY transaction.
#: Distinct from 42501 (insufficient_privilege), which is what the *role* raises.
#: Tests assert on both, because they prove different layers.
READ_ONLY_SQL_TRANSACTION = "25006"


class ReadOnlySessionError(RuntimeError):
    """A session reserved for queries was asked to write."""


def forbid_writes(session: AsyncSession) -> None:
    """Make ORM flushes on ``session`` raise instead of emitting DML.

    The listener is attached to this session's underlying sync session, so it
    goes away when the session does. Nothing has to unregister it, and one
    request's guard cannot outlive its request.
    """

    @event.listens_for(session.sync_session, "before_flush")
    def _reject_flush(sync_session, flush_context, instances) -> None:  # noqa: ANN001
        pending = {
            "new": sorted(type(o).__name__ for o in sync_session.new),
            "dirty": sorted(type(o).__name__ for o in sync_session.dirty),
            "deleted": sorted(type(o).__name__ for o in sync_session.deleted),
        }
        changed = {kind: names for kind, names in pending.items() if names}
        raise ReadOnlySessionError(
            f"this session belongs to a read-only query service and cannot write, "
            f"but a flush was attempted with {changed or 'no tracked changes'}. "
            f"Use the writable session from get_db() if the operation is meant to "
            f"persist something."
        )
