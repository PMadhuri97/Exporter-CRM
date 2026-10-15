"""Request/response schemas for the screening-review checklist (architecture §8.1,
§9.4).

Split out of `exporter.py` so the company shapes and the
background-check shapes stop sharing one file. The class names are what the
OpenAPI document and the frontend's generated types key on, so they stay
exactly as they were; later changes only add fields and shapes.

The screening checklist is a compliance list inside the background check. It
is not qualification, and qualification does not reuse it (architecture §5.5).

Added 1 October 2026, fields only: an answer's ``evidence_refs`` (accepted on the
``PUT``, optional) and its ``cycle_id``, and the check cycle a list is about. No
identifier is carried by any of them.
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

# ── Screening review workspace ─────────────────────────────────────────────

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
            "Optional. A `document` must be one of the company's own documents "
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


__all__ = [
    "ScreeningCapabilities",
    "ScreeningCatalogueItemResponse",
    "ScreeningChecklistStatus",
    "ScreeningItemHistoryResponse",
    "ScreeningReviewItemResponse",
    "ScreeningReviewListResponse",
    "UpdateScreeningReviewItemRequest",
]
