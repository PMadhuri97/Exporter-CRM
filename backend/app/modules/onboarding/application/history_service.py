"""``HistoryService`` — the one writer of the shared CRM history log.

Every change to a company's journey, to any of its three gauges, to its marker
and to any of its deals lands in ``onboarding.exporter_lifecycle_history`` as one
row. This is the only code that writes it. Developers 2, 3 and 4 call ``record``
rather than each building their own insert, so "show me everything that ever
happened to this company" stays one query against one shape.

The contract is ``docs/contracts/history-row.md``. Two rules from it are
enforced here rather than left to the caller:

**It flushes. It never commits.** The caller owns the transaction, so the
current value and the row recording how it got there commit together or not at
all. A writer that committed on its own would turn one change into two
transactions, and a crash between them leaves a company whose gauge says one
thing and whose history has no record of it ever moving. ``record`` therefore
calls ``flush`` — which assigns the primary key and surfaces constraint
violations immediately — and stops there.

**Values are strings.** ``dimension``, ``from_value`` and ``to_value`` are
``varchar`` columns and this method takes ``str``. A history table has to be
able to record a value just added to an enum without a migration first, and to
keep serving one later removed. Callers pass ``SomeEnum.MEMBER.value``, not the
member.

What this service deliberately does **not** do is decide whether a move is
legal, whether a reason is required, or what the gauge's values mean. That is
the owning gauge service's job — section 3 of the architecture assigns each
gauge to a developer, and a shared writer that knew all of their rules would be
the coupling this module exists to avoid.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.infrastructure.repositories import (
    ExporterLifecycleHistoryRepository,
)
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: Column widths from migration 0013. Checked here so a caller gets a 422 naming
#: the field instead of a `StringDataRightTruncation` from Postgres halfway
#: through a transaction it thought was fine.
_MAX_DIMENSION = 32
_MAX_VALUE = 64
_MAX_SOURCE = 100


class HistoryService:
    """Writes and reads ``exporter_lifecycle_history``.

    Holds the caller's session and never opens its own: everything it writes
    belongs to whatever transaction the caller is already in.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = ExporterLifecycleHistoryRepository(db)

    # ── Write ────────────────────────────────────────────────────────────────

    async def record(
        self,
        company_id: uuid.UUID,
        *,
        dimension: str,
        to_value: str,
        actor_id: str | None,
        source: str,
        from_value: str | None = None,
        reason: str | None = None,
        deal_id: uuid.UUID | None = None,
        details: dict | None = None,
        event_type: str | None = None,
    ) -> ExporterLifecycleHistory:
        """Append one history row. Flushes; does not commit.

        Returns the row, with its ``id`` and ``created_at`` populated by the
        flush, so a caller that needs to reference the record it just wrote —
        an evidence snapshot, an event payload — does not have to re-query.

        Args:
            company_id: The company. Always required, including for deal rows:
                a deal's history is part of its company's story.
            dimension: Which row of the model changed (``journey``,
                ``qualification``, ``conversation``, ``background_check``,
                ``deal``, ``marker``, ``profile``, ``verification``). The list
                lives in the contract, not in code, so adding one needs no
                change here and no migration.
            to_value: The new value, as a string.
            actor_id: Who. Taken from the login session by the caller, never
                from a request body. ``None`` means the platform itself acted —
                the same meaning ``actor_id`` carries on ``case_state_transition``.
            source: The code path that wrote the row, dotted
                (``exporter_profile_service.transition_lifecycle_status``). For
                a human reading the trail; stored inside ``event_metadata``.
            from_value: The previous value. ``None`` means "entered at
                creation", which is also what selects the ``_initial``
                ``event_type`` below.
            reason: Why, in the actor's words. Whether a reason is *required*
                is the gauge service's rule (contract §4), not this method's.
            deal_id: The deal, when the change is about one.
            details: Anything else a reader should have without a second query.
                Merged into ``event_metadata`` alongside ``source``.
            event_type: Overrides the derived value. The journey passes its
                legacy ``lifecycle_initial`` / ``lifecycle_transition`` names,
                which a downstream consumer (ANER-4.2-S1T2) already polls for.

        Raises:
            ValidationError: a field is empty or longer than its column.
        """
        dimension = _require(dimension, "dimension", _MAX_DIMENSION)
        to_value = _require(to_value, "to_value", _MAX_VALUE)
        source = _require(source, "source", _MAX_SOURCE)
        if from_value is not None:
            from_value = _require(from_value, "from_value", _MAX_VALUE)

        # `<dimension>_initial` when the value was set at creation,
        # `<dimension>_transition` when it moved. Derived rather than required
        # so a new gauge gets consistent naming for free; overridable so the
        # journey keeps the names its consumer already watches.
        resolved_event_type = event_type or (
            f"{dimension}_transition" if from_value is not None else f"{dimension}_initial"
        )

        row = await self._history.create(
            ExporterLifecycleHistory(
                customer_id=company_id,
                dimension=dimension,
                deal_id=deal_id,
                event_type=resolved_event_type,
                from_status=from_value,
                to_status=to_value,
                actor_id=actor_id,
                reason=reason,
                event_metadata={"source": source, **(details or {})},
            )
        )
        # `AppendOnlyRepository.create` flushes. Nothing here commits: see the
        # module docstring, and `docs/contracts/history-row.md` §5.
        logger.debug(
            "history.recorded",
            company_id=str(company_id),
            dimension=dimension,
            from_value=from_value,
            to_value=to_value,
            actor_id=actor_id,
        )
        return row

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_for_company(
        self,
        company_id: uuid.UUID,
        *,
        dimension: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[ExporterLifecycleHistory], int]:
        """One company's history, newest first, with the total for paging.

        Unfiltered this returns the journey, every gauge and every deal
        interleaved — the company timeline. ``dimension`` narrows it to one
        gauge, which is what a gauge panel asks for.
        """
        rows = await self._history.list_by_customer(
            company_id, dimension=dimension, limit=limit, offset=offset
        )
        total = await self._history.count_by_customer(company_id, dimension=dimension)
        return rows, total

    async def list_for_deal(
        self, deal_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[ExporterLifecycleHistory], int]:
        """One deal's history, newest first, with the total for paging.

        Empty until deals exist (migration 0018, Developer 3). That is the
        correct answer for a deal with no recorded changes and for a deal id
        that was never real — this service has no deal table to check against,
        and inventing a 404 would mean guessing.
        """
        rows = await self._history.list_by_deal(deal_id, limit=limit, offset=offset)
        total = await self._history.count_by_deal(deal_id)
        return rows, total


def _require(value: str, field: str, max_length: int) -> str:
    """Non-empty and short enough for its column."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValidationError(f"history row requires a non-empty {field}")
    if len(cleaned) > max_length:
        raise ValidationError(
            f"history row {field} is {len(cleaned)} characters; the column holds {max_length}"
        )
    return cleaned


__all__ = ["HistoryService"]
