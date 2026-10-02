"""Request/response schemas for the screening-review checklist and the
bank-activity panel — **owner: Developer 4** (architecture §8.1, §9.4).

Split out of `exporter.py` (L2-01) so the company shapes and the
background-check shapes stop sharing one file. The class names are what the
OpenAPI document and the frontend's generated types key on, so they stay
exactly as they were; Dev4B's changes (4B-1, 4B-6) only add fields and shapes.

The screening checklist is a compliance list inside the background check. It
is not qualification, and qualification does not reuse it (architecture §5.5).

Developer 1 (1 October 2026) added fields only: an answer's ``evidence_refs`` (plan
P2-1b; accepted on the ``PUT``, optional per IQ-14) and its ``cycle_id``, and the
check cycle a list is about (P2-3d). No identifier is carried by any of them.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.background_check import CheckCycleResponse
from app.modules.onboarding.api.schemas.verification import (
    VerificationEvidenceRefModel,
    VerificationEvidenceRefOut,
)
from app.modules.onboarding.domain.verification_evidence import (
    EvidenceRef,
    VerificationEvidence,
)

# ── E9 screening review workspace ──────────────────────────────────────────

#: Same four values as `screening_review.SCREENING_STATUSES` and
#: `ck_screening_review_item_status`.
ScreeningChecklistStatus = Literal["NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT"]


class UpdateScreeningReviewItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ScreeningChecklistStatus
    comment: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[VerificationEvidenceRefModel] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Optional (IQ-14). A `document` must be one of the company's own documents "
            "and `AVAILABLE` (scanned clean); a `url` must be an http(s) link."
        ),
    )

    def to_evidence(self) -> VerificationEvidence | None:
        if not self.evidence_refs:
            return None
        return VerificationEvidence(
            refs=tuple(EvidenceRef(type=ref.type, ref=ref.ref) for ref in self.evidence_refs)
        )


class ScreeningReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    item_key: str
    status: ScreeningChecklistStatus
    comment: str | None
    reviewed_by: str | None
    reviewed_by_name: str | None = Field(
        default=None,
        description=(
            "Who decided, by name: the account's full name, or its email when it has "
            "none. Null when no account with a name matches `reviewed_by`."
        ),
    )
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    evidence_refs: list[VerificationEvidenceRefOut] = Field(default_factory=list)
    cycle_id: uuid.UUID | None = Field(
        default=None,
        description="The check cycle of this answer (one recorded before cycles reads as cycle 1).",
    )

    def named(self, names: Mapping[str, str]) -> ScreeningReviewItemResponse:
        """This decision with `reviewed_by_name` filled from `names`."""
        return self.model_copy(update={"reviewed_by_name": names.get(self.reviewed_by or "")})


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
    #: The decision per item that has one in this cycle (latest row per key).
    items: list[ScreeningReviewItemResponse]
    #: Every checklist item, in display order.
    catalogue: list[ScreeningCatalogueItemResponse]
    capabilities: ScreeningCapabilities
    cycle: CheckCycleResponse | None = Field(
        default=None,
        description=(
            "The check cycle these answers belong to — the current one unless "
            "`cycle_id` was asked for; `cycle.is_current` says which. Answers are "
            "recorded only in the current cycle; an earlier one is read-only. Null "
            "before the company has a cycle."
        ),
    )


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
    """The bank panel, stated honestly (verification-and-screening.md §8): no bank-monitoring
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
