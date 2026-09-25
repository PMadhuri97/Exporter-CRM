"""Response schemas for the shared CRM history log.

Read-only. There is no request schema and no write route: a history row is
written by the service that made the change it records, inside that change's
own transaction, and the table refuses UPDATE and DELETE at the database. An
API that could post a history row would be a way to write history that never
happened.

Field names follow `docs/contracts/history-row.md`, which calls them
`from_value`/`to_value`. The columns are still `from_status`/`to_status` — 0013
did not rename them — so the aliases are declared here, at the boundary, where
a reader of the API sees the contract's vocabulary and a reader of the table
sees the column names.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)


class HistoryEntryResponse(BaseModel):
    """One recorded change: what moved, from what to what, who and why."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    deal_id: uuid.UUID | None = Field(
        default=None, description="The deal this change was about, when it was about one."
    )
    dimension: str = Field(
        description=(
            "Which row of the model changed: journey, qualification, conversation, "
            "background_check, deal, marker, profile or verification."
        )
    )
    event_type: str = Field(description="Why the row was written, e.g. lifecycle_transition.")
    from_value: str | None = Field(
        default=None, description="The previous value. Null means the value was set at creation."
    )
    to_value: str = Field(description="The new value.")
    actor_id: str | None = Field(
        default=None,
        description=(
            "Who made the change, taken from their login session. Null means the "
            "platform itself acted."
        ),
    )
    reason: str | None = Field(default=None, description="Why, in the actor's words.")
    source: str | None = Field(
        default=None, description="The code path that recorded the change."
    )
    details: dict | None = Field(
        default=None, description="Anything else the writer recorded alongside the change."
    )
    occurred_at: datetime = Field(description="When, from the database clock.")

    @classmethod
    def from_row(cls, row: ExporterLifecycleHistory) -> HistoryEntryResponse:
        """Build the response from a history row.

        `source` is lifted out of `event_metadata` and the rest stays in
        `details`, so a caller does not have to know that one of the keys in
        that blob is special. `event_metadata` is nullable, hence the `or {}`.
        """
        metadata = dict(row.event_metadata or {})
        source = metadata.pop("source", None)
        return cls(
            id=row.id,
            company_id=row.customer_id,
            deal_id=row.deal_id,
            dimension=row.dimension,
            event_type=row.event_type,
            from_value=row.from_status,
            to_value=row.to_status,
            actor_id=row.actor_id,
            reason=row.reason,
            source=source,
            details=metadata or None,
            occurred_at=row.created_at,
        )


class HistoryListResponse(BaseModel):
    """A page of history, newest first.

    `total` is the count matching the same filter, not the length of `entries`,
    so a caller can tell whether there is more without asking for it.
    """

    entries: list[HistoryEntryResponse]
    total: int
    limit: int
    offset: int


__all__ = ["HistoryEntryResponse", "HistoryListResponse"]
