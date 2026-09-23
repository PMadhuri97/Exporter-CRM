"""Request/response schemas for the EXP-2 verification API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)

#: Registry keys of the real verification adapters: `ManualEntryAdapter`
#: (`"manual"`) and `StubRxilAdapter`'s `REGISTRY_KEY` (`"rxil"`). Widen this
#: when a new adapter is registered.
VerificationProvider = Literal["manual", "rxil"]


class TriggerVerificationRequest(BaseModel):
    """Ask `trigger_verification` to run one check.

    `provider` defaults to `"manual"` (`ManualEntryAdapter`) and is limited to
    the registry keys of the adapters that actually exist (`VerificationProvider`)
    — the value is resolved to a module path, so anything else must be refused
    here at the boundary rather than reaching the registry. `payload` is
    opaque here by design: its shape is between the caller and whichever
    adapter `provider` resolves to (see `VerificationRequest`'s docstring),
    not something this schema can or should constrain further.
    """

    model_config = ConfigDict(extra="forbid")

    verification_type: VerificationType
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    provider: VerificationProvider = "manual"
    payload: dict[str, Any] = Field(default_factory=dict)


class RecordReviewRequest(BaseModel):
    """`reviewed_by` is deliberately not a field: the reviewer is always the
    authenticated caller (the router passes `str(current_user.id)`), matching
    the screening review's `actor_id`. With `extra="forbid"`, a client still
    sending `reviewed_by` is rejected (422) rather than silently ignored."""

    model_config = ConfigDict(extra="forbid")

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
    "VerificationProvider",
    "VerificationResultListResponse",
    "VerificationResultResponse",
]
