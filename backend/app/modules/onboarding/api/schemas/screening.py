"""Request/response schemas for the screening-review checklist and the
bank-activity panel — **owner: Developer 4** (architecture §8.1, §9.4).

Split out of `exporter.py` (L2-01) so the company shapes and the
background-check shapes stop sharing one file. The class names are what the
OpenAPI document and the frontend's generated types key on, so they stay
exactly as they were; Dev4B's changes (4B-1, 4B-6) only add fields and shapes.

The screening checklist is a compliance list inside the background check. It
is not qualification, and qualification does not reuse it (architecture §5.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── E9 screening review workspace ──────────────────────────────────────────

#: Same four values as `screening_review.SCREENING_STATUSES` and
#: `ck_screening_review_item_status`.
ScreeningChecklistStatus = Literal["NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT"]


class UpdateScreeningReviewItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ScreeningChecklistStatus
    comment: str | None = Field(default=None, max_length=4000)


class ScreeningReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    item_key: str
    status: ScreeningChecklistStatus
    comment: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScreeningCatalogueItemResponse(BaseModel):
    """One checklist item as the workspace renders it — from the server's one
    catalogue (`screening_review_service.SCREENING_CATALOGUE_ITEMS`)."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    section: str


class ScreeningCapabilities(BaseModel):
    """What the caller may do on this checklist, so the UI keeps no role list."""

    can_record_decision: bool


class ScreeningReviewListResponse(BaseModel):
    customer_id: uuid.UUID
    #: The current decision per item that has one (latest row per key).
    items: list[ScreeningReviewItemResponse]
    #: Every checklist item, in display order.
    catalogue: list[ScreeningCatalogueItemResponse]
    capabilities: ScreeningCapabilities


class ScreeningItemHistoryResponse(BaseModel):
    """Every decision recorded on one checklist item, newest first, one page."""

    customer_id: uuid.UUID
    item_key: str
    items: list[ScreeningReviewItemResponse]
    total: int
    limit: int
    offset: int


class BankActivityFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    provider: str
    finding_type: str
    title: str
    description: str | None
    risk_level: str
    status: str
    provider_reference: str | None
    detected_at: datetime
    created_at: datetime


class BankActivityResponse(BaseModel):
    """The bank panel, stated honestly (4b-task.md §5.9): no bank-monitoring
    provider feed is connected, so `provider_feed_connected` is `false` and
    `connected_accounts` is `0` because nothing is connected — not because
    accounts were checked and none found. No finding is ever fabricated."""

    customer_id: uuid.UUID
    provider_feed_connected: bool = False
    provider_feed_status: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    provider_feed_message: str = (
        "No bank-monitoring provider feed is connected. Bank activity is not being "
        "monitored for this company."
    )
    connected_accounts: int = 0
    last_synced_at: datetime | None = None
    open_findings: int
    findings: list[BankActivityFindingResponse]


__all__ = [
    "BankActivityFindingResponse",
    "BankActivityResponse",
    "ScreeningCapabilities",
    "ScreeningCatalogueItemResponse",
    "ScreeningChecklistStatus",
    "ScreeningItemHistoryResponse",
    "ScreeningReviewItemResponse",
    "ScreeningReviewListResponse",
    "UpdateScreeningReviewItemRequest",
]
