"""Request/response schemas for the screening-review checklist and the
bank-activity panel — **owner: Developer 4** (architecture §8.1, §9.4).

Split out of `exporter.py` (L2-01) so the company shapes and the
background-check shapes stop sharing one file. Every definition below is
unchanged; the class names are what the OpenAPI document and the frontend's
generated types key on, so they stay exactly as they were.

The screening checklist is a compliance list inside the background check. It
is not qualification, and qualification does not reuse it (architecture §5.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── E9 screening review workspace ──────────────────────────────────────────

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


class ScreeningReviewListResponse(BaseModel):
    customer_id: uuid.UUID
    items: list[ScreeningReviewItemResponse]


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
    customer_id: uuid.UUID
    connected_accounts: int = 0
    last_synced_at: datetime | None = None
    open_findings: int
    findings: list[BankActivityFindingResponse]


__all__ = [
    "BankActivityFindingResponse",
    "BankActivityResponse",
    "ScreeningChecklistStatus",
    "ScreeningReviewItemResponse",
    "ScreeningReviewListResponse",
    "UpdateScreeningReviewItemRequest",
]
