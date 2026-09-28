"""Request/response schemas for qualification — **owner: Developer 2**
(L2-09, L2-10, ``docs/contracts/criterion-result.md``).

What a caller can **not** send, on purpose, with ``extra="forbid"`` refusing
it: who recorded or decided anything (always the signed-in user), and a
result's or outcome's ``source``, ``decided_by_kind`` or ``confidence``. A
person entering results through the API is ``MANUAL`` by definition; the
other sources (import, RXIL, automation) are the platform's own callers of the
service, never a claim a request body can make — the same reasoning that
keeps a caller from forging a ``SYSTEM`` approval (L1-05).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.qualification import (
    QualificationCriterion,
    QualificationOutcome,
    QualificationResult,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
    QualificationState,
    ThresholdComparison,
)
from app.modules.onboarding.domain.qualification_views import (
    CriterionDefinition,
    EvidenceRef,
    QualificationView,
    ResultEntry,
)

# ── Criteria ──────────────────────────────────────────────────────────────────


class CriterionDefinitionRequest(BaseModel):
    """One version of a criterion. Every change is a new version."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=255)
    kind: CriterionKind
    required: bool
    active: bool = True
    comparison: ThresholdComparison | None = None
    threshold: Decimal | None = None
    unit: str | None = Field(default=None, max_length=32)
    allowed_values: list[str] | None = None

    def to_definition(self) -> CriterionDefinition:
        return CriterionDefinition(
            label=self.label,
            kind=self.kind,
            required=self.required,
            active=self.active,
            comparison=self.comparison,
            threshold=self.threshold,
            unit=self.unit,
            allowed_values=tuple(self.allowed_values) if self.allowed_values is not None else None,
        )


class CreateCriterionRequest(CriterionDefinitionRequest):
    """A new criterion, recorded as version 1."""

    key: str = Field(min_length=1, max_length=64)


class CriterionResponse(BaseModel):
    id: uuid.UUID
    key: str
    version: int
    label: str
    kind: CriterionKind
    comparison: ThresholdComparison | None
    threshold: float | None
    unit: str | None
    allowed_values: list[str] | None
    required: bool
    active: bool
    created_by: str | None
    created_at: datetime

    @classmethod
    def of(cls, row: QualificationCriterion) -> CriterionResponse:
        return cls(
            id=row.id,
            key=row.key,
            version=row.version,
            label=row.label,
            kind=row.kind,
            comparison=row.comparison,
            threshold=float(row.threshold) if row.threshold is not None else None,
            unit=row.unit,
            allowed_values=row.allowed_values,
            required=row.required,
            active=row.active,
            created_by=row.created_by,
            created_at=row.created_at,
        )


class CriterionListResponse(BaseModel):
    criteria: list[CriterionResponse]


class ReasonCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    requires_note: bool
    active: bool


class ReasonCodeListResponse(BaseModel):
    reason_codes: list[ReasonCodeResponse]


# ── Results ───────────────────────────────────────────────────────────────────


class EvidenceRefModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["document", "verification_result", "url"]
    ref: str = Field(min_length=1, max_length=2048)


class EvidenceRefOut(BaseModel):
    """An evidence reference as stored. Besides the three a request may send,
    a partner intake may store `partner_reference` — the partner's own id for
    its evidence."""

    type: str
    ref: str


class ResultRequest(BaseModel):
    """One criterion checked by the signed-in user. The server pins the
    criterion's current version."""

    model_config = ConfigDict(extra="forbid")

    criterion_key: str = Field(min_length=1, max_length=64)
    result: CriterionResultValue
    observed_value: str | None = Field(default=None, max_length=2000)
    evidence_note: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[EvidenceRefModel] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=4000)

    def to_entry(self) -> ResultEntry:
        return ResultEntry(
            criterion_key=self.criterion_key,
            result=self.result,
            observed_value=self.observed_value,
            evidence_note=self.evidence_note,
            evidence_refs=tuple(EvidenceRef(type=r.type, ref=r.ref) for r in self.evidence_refs),
            reason=self.reason,
        )


class RecordResultsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[ResultRequest] = Field(min_length=1, max_length=50)


class ResultResponse(BaseModel):
    id: uuid.UUID
    criterion_key: str
    criterion_version: int
    result: CriterionResultValue
    observed_value: str | None
    source: QualificationSource
    decided_by_kind: DecidedByKind
    evidence_note: str | None
    evidence_refs: list[EvidenceRefOut]
    reason: str | None
    confidence: float | None
    recorded_by: str | None
    recorded_at: datetime

    @classmethod
    def of(cls, row: QualificationResult) -> ResultResponse:
        return cls(
            id=row.id,
            criterion_key=row.criterion.key,
            criterion_version=row.criterion.version,
            result=row.result,
            observed_value=row.observed_value,
            source=row.source,
            decided_by_kind=row.decided_by_kind,
            evidence_note=row.evidence_note,
            evidence_refs=[EvidenceRefOut(**ref) for ref in row.evidence_refs],
            reason=row.reason,
            confidence=float(row.confidence) if row.confidence is not None else None,
            recorded_by=row.recorded_by,
            recorded_at=row.recorded_at,
        )


# ── Outcome ───────────────────────────────────────────────────────────────────


class RecordOutcomeRequest(BaseModel):
    """The signed-in reviewer's decision. `NOT_QUALIFIED` needs at least one
    reason code; `other` needs a note."""

    model_config = ConfigDict(extra="forbid")

    outcome: QualificationOutcomeValue
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=4000)


class OutcomeResponse(BaseModel):
    id: uuid.UUID
    outcome: QualificationOutcomeValue
    reason_codes: list[str]
    note: str | None
    #: What the server suggested when the decision was made — kept apart from
    #: `outcome`, which is the person's call.
    suggested_outcome: QualificationOutcomeValue
    result_ids: list[uuid.UUID]
    source: QualificationSource
    decided_by_kind: DecidedByKind
    supersedes_outcome_id: uuid.UUID | None
    decided_by: str | None
    decided_at: datetime

    @classmethod
    def of(cls, row: QualificationOutcome) -> OutcomeResponse:
        return cls(
            id=row.id,
            outcome=row.outcome,
            reason_codes=list(row.reason_codes),
            note=row.note,
            suggested_outcome=row.suggested_outcome,
            result_ids=[uuid.UUID(i) for i in row.result_ids],
            source=row.source,
            decided_by_kind=row.decided_by_kind,
            supersedes_outcome_id=row.supersedes_outcome_id,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
        )


# ── The company's qualification ───────────────────────────────────────────────


class CriterionStandingResponse(BaseModel):
    criterion: CriterionResponse
    latest_result: ResultResponse | None
    #: Whether `latest_result` was judged against the current version and so
    #: counts towards the suggestion.
    counts: bool


class QualificationResponse(BaseModel):
    customer_id: uuid.UUID
    state: QualificationState
    journey: ExporterJourney
    #: The server's suggestion from the current results. Never the decision.
    suggested_outcome: QualificationOutcomeValue
    standings: list[CriterionStandingResponse]
    results: list[ResultResponse]
    outcomes: list[OutcomeResponse]
    #: The outcomes the signed-in user may record now: none once QUALIFIED
    #: (final, A2) or for a role that may not record outcomes.
    allowed_outcomes: list[QualificationOutcomeValue] = Field(default_factory=list)
    #: Whether the signed-in user may record criterion results now.
    can_record_results: bool = False

    @classmethod
    def of(cls, customer_id: uuid.UUID, view: QualificationView) -> QualificationResponse:
        return cls(
            customer_id=customer_id,
            state=view.state,
            journey=view.journey,
            suggested_outcome=view.suggested_outcome,
            standings=[
                CriterionStandingResponse(
                    criterion=CriterionResponse.of(s.criterion),
                    latest_result=(
                        ResultResponse.of(s.latest_result) if s.latest_result is not None else None
                    ),
                    counts=s.counts,
                )
                for s in view.standings
            ],
            results=[ResultResponse.of(r) for r in view.results],
            outcomes=[OutcomeResponse.of(o) for o in view.outcomes],
        )
