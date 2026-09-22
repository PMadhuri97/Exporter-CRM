"""Request/response schemas for the EXP-2 verification API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)


class TriggerVerificationRequest(BaseModel):
    """Ask `trigger_verification` to run one check.

    `provider` defaults to `"manual"` (`ManualEntryAdapter`) — the only
    adapter this ticket ships. `payload` is opaque here by design: its shape
    is between the caller and whichever adapter `provider` resolves to (see
    `VerificationRequest`'s docstring), not something this schema can or
    should constrain further.
    """

    model_config = ConfigDict(extra="forbid")

    verification_type: VerificationType
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    provider: str = "manual"
    payload: dict[str, Any] = Field(default_factory=dict)


class RecordReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = Field(min_length=1, max_length=255)
    review_status: VerificationReviewStatus


class VerificationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    verification_type: VerificationType
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    provider: str
    provider_reference: str | None
    status: VerificationResultStatus
    risk_level: VerificationRiskLevel | None
    performed_at: datetime
    valid_until: datetime | None
    normalized_result: dict[str, Any]
    evidence_reference: str | None
    reviewed_by: str | None
    review_status: VerificationReviewStatus | None
    created_at: datetime
    updated_at: datetime

    # `raw_result` is deliberately excluded from this response model: it is
    # the documented PII/encryption-at-rest gap (see `VerificationResult`'s
    # docstring) and is not safe to hand back over the API unredacted until
    # that gap is closed.


class VerificationResultListResponse(BaseModel):
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    results: list[VerificationResultResponse]
    total: int


__all__ = [
    "RecordReviewRequest",
    "TriggerVerificationRequest",
    "VerificationResultListResponse",
    "VerificationResultResponse",
]
