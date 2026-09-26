"""Read models and inputs for qualification — **owner: Developer 2**.

Pure data, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.qualification import (
    QualificationCriterion,
    QualificationOutcome,
    QualificationResult,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    QualificationOutcomeValue,
    QualificationState,
    ThresholdComparison,
)


@dataclass(frozen=True)
class CriterionDefinition:
    """Everything a criterion version says, as an ADMIN submits it."""

    label: str
    kind: CriterionKind
    required: bool
    active: bool = True
    comparison: ThresholdComparison | None = None
    threshold: Decimal | None = None
    unit: str | None = None
    allowed_values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class EvidenceRef:
    """A pointer to what a result rests on — never a copy of it."""

    type: str  # "document" | "verification_result" | "url"
    ref: str


@dataclass(frozen=True)
class ResultEntry:
    """One criterion checked, as a reviewer (or later an import, RXIL or
    automation) submits it. The criterion's version is not chosen by the
    caller: the server pins the current one."""

    criterion_key: str
    result: CriterionResultValue
    observed_value: str | None = None
    evidence_note: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: str | None = None
    confidence: Decimal | None = None


@dataclass(frozen=True)
class CriterionStanding:
    """One current criterion and where the company stands on it."""

    criterion: QualificationCriterion
    #: The most recent result for this criterion's key, at any version.
    latest_result: QualificationResult | None
    #: Whether `latest_result` was judged against the current version, and so
    #: counts towards the suggestion.
    counts: bool


@dataclass(frozen=True)
class QualificationView:
    """Everything the qualification panel shows."""

    state: QualificationState
    journey: ExporterJourney
    #: What the server suggests now. Never the decision: that is the latest
    #: outcome, recorded by a person.
    suggested_outcome: QualificationOutcomeValue
    standings: tuple[CriterionStanding, ...]
    results: tuple[QualificationResult, ...] = field(default_factory=tuple)
    outcomes: tuple[QualificationOutcome, ...] = field(default_factory=tuple)


__all__ = [
    "CriterionDefinition",
    "CriterionStanding",
    "EvidenceRef",
    "QualificationView",
    "ResultEntry",
]
