"""Request/response schemas for the EXP-2 verification API — **owner: Developer 4B**.

Changes since EXP-2 are additive (4b-task.md §11): `VerificationResultResponse` keeps
every field it had and gains evidence, the buyer snapshot, provenance, the
placeholder flag and the review chain. `reviewed_by` / `review_status` now report the
**current** review (the chain head) rather than the legacy columns, which are no
longer written.

What a request can never say: who recorded or reviewed (always the signed-in user),
the provider's provenance, or anything about the subject beyond its id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.masking import can_reveal_identifiers, mask_identifier
from app.modules.onboarding.application.verification_service import VerificationResultView
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.modules.onboarding.domain.verification_evidence import (
    EvidenceRef,
    EvidenceRefType,
    VerificationEvidence,
)
from app.platform.authentication.models import User

#: Registry keys of the real verification adapters: `ManualEntryAdapter`
#: (`"manual"`) and `StubRxilAdapter`'s `REGISTRY_KEY` (`"rxil"`). Widen this
#: when a new adapter is registered. Middesk, Trulioo and Sumsub stay
#: unreachable (A13).
VerificationProvider = Literal["manual", "rxil"]

#: What `POST /verifications` — the manual route — accepts. Decision **D7** (lead,
#: 28 Sep 2026): a person records results here, so only `"manual"`. `"rxil"` is
#: refused (422) and reserved for the future RXIL results-intake path (blocked on
#: D12), so nobody can record a result *as RXIL's* by picking it from a form.
ManualRouteProvider = Literal["manual"]


class VerificationEvidenceRefModel(BaseModel):
    """One evidence reference: a `crm_document.id` (`document`) or an `http://` /
    `https://` link (`url`) — any other scheme is refused (422).

    Prefixed because OpenAPI schema names are global: qualification already has an
    `EvidenceRefModel` / `EvidenceRefOut` (`schemas/qualification.py`), and a second
    class of the same name makes FastAPI rename *both* to module-qualified names,
    silently changing Developer 2's generated types."""

    model_config = ConfigDict(extra="forbid")

    type: EvidenceRefType
    ref: str = Field(min_length=1, max_length=2048)


class TriggerVerificationRequest(BaseModel):
    """Ask `trigger_verification` to run one check.

    `provider` defaults to `"manual"` (`ManualEntryAdapter`) and, on this route,
    is limited to it (`ManualRouteProvider`, decision D7) — the value is resolved
    to a module path, so anything else must be refused here at the boundary
    rather than reaching the registry. `payload` is
    opaque here by design: its shape is between the caller and whichever
    adapter `provider` resolves to (see `VerificationRequest`'s docstring),
    not something this schema can or should constrain further.

    `entity_reference` is a company id for `EXPORTER` and a `deal_buyer.id` for
    `BUYER` — never a company or deal id for a buyer.

    Evidence (`evidence_note`, `evidence_refs`) is what the outcome rests on, in the
    qualification contract's shape. A manual `PASSED` needs some (D16: a note or at
    least one reference). A `document` reference must belong to the subject and be
    `AVAILABLE` (scanned clean); a `url` reference must be an http(s) link.
    """

    model_config = ConfigDict(extra="forbid")

    verification_type: VerificationType
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    provider: ManualRouteProvider = "manual"
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_note: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[VerificationEvidenceRefModel] = Field(default_factory=list, max_length=50)

    def to_evidence(self) -> VerificationEvidence | None:
        if self.evidence_note is None and not self.evidence_refs:
            return None
        return VerificationEvidence(
            note=self.evidence_note,
            refs=tuple(EvidenceRef(type=ref.type, ref=ref.ref) for ref in self.evidence_refs),
        )


class RecordReviewRequest(BaseModel):
    """`reviewed_by` is deliberately not a field: the reviewer is always the
    authenticated caller (the router passes `str(current_user.id)`), matching
    the screening review's `actor_id`. With `extra="forbid"`, a client still
    sending `reviewed_by` is rejected (422) rather than silently ignored.

    A result's first review leaves `supersedes_review_id` out. Every later review
    names the result's current review there and says why in `note`; naming anything
    else is a 409, so a reviewer never overrules a review they have not seen.
    """

    model_config = ConfigDict(extra="forbid")

    review_status: VerificationReviewStatus
    note: str | None = Field(default=None, max_length=4000)
    supersedes_review_id: uuid.UUID | None = None


class VerificationEvidenceRefOut(BaseModel):
    """An evidence reference as stored. Prefixed for the reason
    `VerificationEvidenceRefModel` gives."""

    type: str
    ref: str


class VerificationReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    verification_result_id: uuid.UUID
    review_status: VerificationReviewStatus
    reviewed_by: str
    reviewed_at: datetime
    note: str | None
    supersedes_review_id: uuid.UUID | None


class BuyerSnapshotResponse(BaseModel):
    """A BUYER check's subject as it was when the check was recorded. The
    registration number and tax id are masked for every role but COMPLIANCE and
    ADMIN — the deal buyer's own rule (`masking.py`)."""

    deal_buyer_id: uuid.UUID
    deal_id: uuid.UUID
    name: str
    country: str
    registration_number: str | None
    tax_id: str | None


Provenance = Literal["MANUAL", "STUB", "PROVIDER"]


class VerificationResultResponse(BaseModel):
    id: uuid.UUID
    verification_type: VerificationType
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    provider: str
    #: How much to trust `provider`: `MANUAL` (a person), `STUB` (the RXIL stub —
    #: not RXIL), `PROVIDER` (a real integration).
    provenance: Provenance
    #: A placeholder row: created without any provider (the retired dev generator).
    is_placeholder: bool
    provider_reference: str | None
    status: VerificationResultStatus
    risk_level: VerificationRiskLevel | None
    performed_at: datetime
    valid_until: datetime | None
    # D8 (lead, 28 Sep 2026): no change — returned as stored to the roles that
    # may read it; DEVELOPER stays refused.
    normalized_result: dict[str, Any]
    #: Retired: never written. Kept so the response shape does not shrink.
    evidence_reference: str | None
    evidence_note: str | None
    evidence_refs: list[VerificationEvidenceRefOut]
    subject_snapshot: BuyerSnapshotResponse | None
    #: The current review's reviewer and status (the chain head), or `None`.
    reviewed_by: str | None
    review_status: VerificationReviewStatus | None
    latest_review_id: uuid.UUID | None
    latest_reviewed_at: datetime | None
    #: Every review, first to current.
    reviews: list[VerificationReviewResponse]
    created_at: datetime
    updated_at: datetime

    # `raw_result` is deliberately excluded from this response model: it is
    # the documented PII/encryption-at-rest gap (see `VerificationResult`'s
    # docstring) and is not safe to hand back over the API unredacted until
    # that gap is closed.

    @classmethod
    def from_view(cls, view: VerificationResultView, viewer: User) -> VerificationResultResponse:
        result = view.result
        latest: VerificationReview | None = view.latest_review
        if latest is not None:
            reviewed_by, review_status = latest.reviewed_by, latest.review_status
        else:
            # A legacy column written outside the service after migration 0021.
            reviewed_by, review_status = result.reviewed_by, result.review_status
        return cls(
            id=result.id,
            verification_type=result.verification_type,
            entity_type=result.entity_type,
            entity_reference=result.entity_reference,
            provider=result.provider,
            provenance=result.provenance,
            is_placeholder=result.is_placeholder,
            provider_reference=result.provider_reference,
            status=result.status,
            risk_level=result.risk_level,
            performed_at=result.performed_at,
            valid_until=result.valid_until,
            normalized_result=result.normalized_result,
            evidence_reference=result.evidence_reference,
            evidence_note=result.evidence_note,
            evidence_refs=[
                VerificationEvidenceRefOut(**ref) for ref in (result.evidence_refs or [])
            ],
            subject_snapshot=_snapshot_for(result.subject_snapshot, viewer),
            reviewed_by=reviewed_by,
            review_status=review_status,
            latest_review_id=latest.id if latest is not None else None,
            latest_reviewed_at=latest.reviewed_at if latest is not None else None,
            reviews=[VerificationReviewResponse.model_validate(r) for r in view.reviews],
            created_at=result.created_at,
            updated_at=result.updated_at,
        )


def _snapshot_for(snapshot: dict[str, Any] | None, viewer: User) -> BuyerSnapshotResponse | None:
    if not snapshot:
        return None
    reveal = can_reveal_identifiers(viewer)
    registration_number = snapshot.get("registration_number")
    tax_id = snapshot.get("tax_id")
    return BuyerSnapshotResponse(
        deal_buyer_id=snapshot["deal_buyer_id"],
        deal_id=snapshot["deal_id"],
        name=snapshot["name"],
        country=snapshot["country"],
        registration_number=(
            registration_number if reveal else mask_identifier(registration_number)
        ),
        tax_id=tax_id if reveal else mask_identifier(tax_id),
    )


class VerificationCapabilities(BaseModel):
    """What the caller may do here, so the UI keeps no role list (§5.10)."""

    can_record_result: bool
    can_review: bool


class VerificationResultListResponse(BaseModel):
    entity_type: VerificationEntityType
    entity_reference: uuid.UUID
    results: list[VerificationResultResponse]
    total: int
    capabilities: VerificationCapabilities


__all__ = [
    "BuyerSnapshotResponse",
    "VerificationEvidenceRefModel",
    "VerificationEvidenceRefOut",
    "ManualRouteProvider",
    "RecordReviewRequest",
    "TriggerVerificationRequest",
    "VerificationCapabilities",
    "VerificationProvider",
    "VerificationResultListResponse",
    "VerificationResultResponse",
    "VerificationReviewResponse",
]
