"""Request/response schemas for the background check — **owner: Developer 4A**
(L4-03, L4-13; ``docs/contracts/background-check.md``).

**What a client may not send.** The move request carries a destination, a reason, a
risk rating and the value the client was looking at, and nothing else. It may not name the actor, the source, the
decided-by kind or the evidence: every one of those is the server's, and a client
that could choose them could forge who decided, claim a decision came from RXIL, or
pin a decision to evidence it never rested on. ``extra="forbid"`` makes the attempt a
422 rather than a silently ignored field — the difference between a caller learning
the field is not theirs and a caller believing it worked.

**No identifiers here to mask.** A decision carries a destination, a reason, a risk
and ids; it embeds no PAN, GSTIN or buyer contact detail, so there is nothing for
``masking.py`` to do. If a field ever arrives that does carry one, it goes through
Developer 1's helpers exactly as ``deal.py`` does — it does not get special-cased
here.

The reason *is* free text a person typed, which is why DEVELOPER may not read it
(**D8**, settled 28 September 2026): DEVELOPER does not reach these routes at all, so
the question does not arise in this schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.background_check_views import (
    BackgroundCheckDecisionView,
    BackgroundCheckMove,
    EvidenceItemView,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)


class BackgroundCheckMoveResponse(BaseModel):
    """One move this caller may make, and what it needs.

    The rules as data (contract §3): the screen offers exactly what is here and keeps
    no move table and no role list of its own, so a rule change cannot leave a stale
    button behind.
    """

    to_value: BackgroundCheckState
    reason_required: bool
    risk_required: bool

    @classmethod
    def from_view(cls, move: BackgroundCheckMove) -> BackgroundCheckMoveResponse:
        return cls(
            to_value=move.to,
            reason_required=move.reason_required,
            risk_required=move.risk_required,
        )


class EvidenceItemResponse(BaseModel):
    """One id a decision was recorded against. IDs only, never content (contract §6)."""

    kind: str
    crm_document_id: uuid.UUID | None = None
    verification_result_id: uuid.UUID | None = None
    verification_review_id: uuid.UUID | None = None
    screening_review_item_id: uuid.UUID | None = None

    @classmethod
    def from_view(cls, item: EvidenceItemView) -> EvidenceItemResponse:
        return cls(
            kind=item.kind.value,
            crm_document_id=item.crm_document_id,
            verification_result_id=item.verification_result_id,
            verification_review_id=item.verification_review_id,
            screening_review_item_id=item.screening_review_item_id,
        )


class BackgroundCheckDecisionResponse(BaseModel):
    """One recorded move, with the evidence it rested on."""

    id: uuid.UUID
    company_id: uuid.UUID
    from_value: BackgroundCheckState
    to_value: BackgroundCheckState
    decided_by: str | None
    decided_by_kind: str
    source: str
    decided_at: datetime
    reason: str | None
    risk_rating: BackgroundCheckRisk | None
    supersedes_decision_id: uuid.UUID | None
    evidence: list[EvidenceItemResponse]

    @classmethod
    def from_view(cls, view: BackgroundCheckDecisionView) -> BackgroundCheckDecisionResponse:
        return cls(
            id=view.id,
            company_id=view.company_id,
            from_value=view.from_value,
            to_value=view.to_value,
            decided_by=view.decided_by,
            decided_by_kind=view.decided_by_kind.value,
            source=view.source.value,
            decided_at=view.decided_at,
            reason=view.reason,
            risk_rating=view.risk_rating,
            supersedes_decision_id=view.supersedes_decision_id,
            evidence=[EvidenceItemResponse.from_view(item) for item in view.evidence],
        )


class BackgroundCheckResponse(BaseModel):
    """Where a company's check stands, and what this caller may do next."""

    company_id: uuid.UUID
    value: BackgroundCheckState
    risk_rating: BackgroundCheckRisk | None = Field(
        default=None,
        description=(
            "The risk of the most recent CLEAR decision (only CLEAR carries one). "
            "Read `value` before trusting it: a company cleared at LOW and then "
            "reopened still reports LOW while it sits at IN_REVIEW — the last "
            "recorded risk, to be labelled as such (D6)."
        ),
    )
    latest_decision_id: uuid.UUID | None = None
    clearing_decision_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The decision behind the company's current CLEAR. Null unless `value` is "
            "CLEAR, so a reopened company never reports a clearance that was withdrawn."
        ),
    )
    decided_at: datetime | None = None
    allowed_moves: list[BackgroundCheckMoveResponse] = Field(
        description=(
            "The moves this caller may make from the current value, with what each "
            "needs. Empty for a caller whose role makes no move from here. `CLEAR` "
            "may appear while its prerequisites are unmet — `clear_blocked_reasons` "
            "names those."
        )
    )
    clear_blocked_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Which of CLEAR's prerequisites are unmet right now, by name, so the "
            "screen can say what is outstanding instead of showing a 409 afterwards. "
            "Empty when the company is not IN_REVIEW or when nothing is outstanding."
        ),
    )


class RecordBackgroundCheckDecisionRequest(BaseModel):
    """A move, as a client may ask for it.

    Four fields, and `extra="forbid"`. The actor comes from the login session, the
    source and decided-by kind are the server's, and the evidence snapshot is
    assembled by the server from the 4A ↔ 4B seam and Developer 3B's documents. A
    request naming any of them is refused (422) rather than quietly ignored.
    """

    model_config = ConfigDict(extra="forbid")

    to_value: BackgroundCheckState = Field(
        description="The value to move to. Must be one the server offers in `allowed_moves`."
    )
    reason: Annotated[str, Field(min_length=1, max_length=4000)] | None = Field(
        default=None,
        description=(
            "Why, or the note of what is needed or what arrived. Required on every "
            "move except the first (`NOT_STARTED → IN_REVIEW`)."
        ),
    )
    risk_rating: BackgroundCheckRisk | None = Field(
        default=None,
        description=(
            "LOW, MEDIUM, HIGH or CRITICAL. Required on CLEAR and refused (422 "
            "`BACKGROUND_CHECK_RISK_NOT_ALLOWED`) on every other move."
        ),
    )
    from_value: BackgroundCheckState | None = Field(
        default=None,
        description=(
            "The value the client was looking at when it chose this move. If the check "
            "has moved since, the request is refused (409 "
            "`BACKGROUND_CHECK_STATE_CHANGED`) instead of becoming a different act — "
            "four moves share the destination IN_REVIEW. Optional, but a screen "
            "should always send it."
        ),
    )


class BackgroundCheckDecisionListResponse(BaseModel):
    """A company's decisions, newest first."""

    decisions: list[BackgroundCheckDecisionResponse]
    total: int
    limit: int
    offset: int


__all__ = [
    "BackgroundCheckDecisionListResponse",
    "BackgroundCheckDecisionResponse",
    "BackgroundCheckMoveResponse",
    "BackgroundCheckResponse",
    "EvidenceItemResponse",
    "RecordBackgroundCheckDecisionRequest",
]
