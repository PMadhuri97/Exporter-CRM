"""Request/response schemas for the background check
(``docs/contracts/background-check.md``).

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
the shared masking helpers exactly as ``deal.py`` does — it does not get special-cased
here.

The reason *is* free text a person typed, which is why DEVELOPER may not read it
(settled 28 September 2026): DEVELOPER does not reach these routes at all, so
the question does not arise in this schema.

Added 1 October 2026: the company's compliance facts on the standing, the check
cycles and the actions that start one, each decision's rules version and cycle, and
the resolved evidence of one decision. **None of them carries an identifier** — no
PAN, GSTIN, IEC, CIN, buyer tax id or contact detail — so ``masking.py`` still has
nothing to do here; the masking tests assert that for OPERATIONS, and DEVELOPER is
refused.

Also added 1 October 2026: maker-checker proposals and their approval, the
passed-checks rule's required checks, each Clear's expiry and the "Re-KYC due" list.
Still no identifier: a proposal carries a move, a reason, a
risk, user ids and names; the due list a company's **name**, journey and expiry —
never its PAN, GSTIN, IEC, CIN or contacts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.verification import VerificationEvidenceRefOut
from app.modules.onboarding.domain.background_check_views import (
    BackgroundCheckCycleAction,
    BackgroundCheckDecisionView,
    BackgroundCheckMove,
    EvidenceItemView,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.exporter_enums import CompanyPipelineStatus


class BackgroundCheckMoveResponse(BaseModel):
    """One move this caller may make, and what it needs.

    The rules as data (contract §3): the screen offers exactly what is here and keeps
    no move table and no role list of its own, so a rule change cannot leave a stale
    button behind.
    """

    to_value: BackgroundCheckState
    reason_required: bool
    risk_required: bool
    approval_required: bool = Field(
        default=False,
        description=(
            "Maker-checker: recording this move creates a proposal that a different "
            "COMPLIANCE user must approve before the check moves."
        ),
    )

    @classmethod
    def from_view(cls, move: BackgroundCheckMove) -> BackgroundCheckMoveResponse:
        return cls(
            to_value=move.to,
            reason_required=move.reason_required,
            risk_required=move.risk_required,
            approval_required=move.approval_required,
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
    decided_by_name: str | None = Field(
        default=None,
        description=(
            "Who decided, by name: the account's full name, or its email when it has "
            "none. Null when no account with a name matches `decided_by`. Resolved "
            "when read, not stored."
        ),
    )
    decided_by_kind: str
    source: str
    decided_at: datetime
    reason: str | None
    risk_rating: BackgroundCheckRisk | None
    supersedes_decision_id: uuid.UUID | None
    evidence: list[EvidenceItemResponse]
    rules_version: str | None = Field(
        default=None,
        description=(
            "The Clear rules in force when the decision was taken. Null on decisions "
            "recorded before rules were versioned: those read as "
            "`clear-2026-09-28-8items` (the eight-item checklist)."
        ),
    )
    cycle_id: uuid.UUID | None = Field(
        default=None,
        description="The check cycle the decision was taken in (a legacy decision reads as cycle 1).",
    )
    cycle_number: int | None = Field(
        default=None, description="That cycle's number: 1, 2, 3 …"
    )
    proposal_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Maker-checker: the proposal this decision approved. Null for a decision "
            "recorded by one person (a move that needs no approval, or one recorded "
            "before maker-checker)."
        ),
    )
    approved_by: str | None = Field(
        default=None,
        description="Who approved it (never `decided_by`, who proposed it).",
    )
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "When this CLEAR stops being current. Null on other moves, and on a CLEAR "
            "recorded before expiry was stored (it expires one year after `decided_at`)."
        ),
    )

    @classmethod
    def from_view(
        cls,
        view: BackgroundCheckDecisionView,
        *,
        decided_by_name: str | None = None,
        approved_by_name: str | None = None,
        cycle_id: uuid.UUID | None = None,
        cycle_number: int | None = None,
    ) -> BackgroundCheckDecisionResponse:
        return cls(
            id=view.id,
            company_id=view.company_id,
            from_value=view.from_value,
            to_value=view.to_value,
            decided_by=view.decided_by,
            decided_by_name=decided_by_name,
            decided_by_kind=view.decided_by_kind.value,
            source=view.source.value,
            decided_at=view.decided_at,
            reason=view.reason,
            risk_rating=view.risk_rating,
            supersedes_decision_id=view.supersedes_decision_id,
            evidence=[EvidenceItemResponse.from_view(item) for item in view.evidence],
            rules_version=view.rules_version,
            cycle_id=cycle_id or view.cycle_id,
            cycle_number=cycle_number,
            proposal_id=view.proposal_id,
            approved_by=view.approved_by,
            approved_by_name=approved_by_name,
            approved_at=view.approved_at,
            expires_at=view.expires_at,
        )


# ── Compliance facts, cycles ────────────────────────────────────────────────

CheckStateValue = Literal["PASSED", "FAILED", "MISSING", "PENDING"]


class CompanyComplianceFactsResponse(BaseModel):
    """The company's compliance facts now — ``ComplianceFactsReader.for_company``."""

    is_clear: bool
    clear_expires_at: datetime | None = Field(
        description=(
            "When the current Clear stops being current (one year from the clearing "
            "decision). Null unless the check is CLEAR."
        )
    )
    is_clear_current: bool = Field(
        description="CLEAR and not yet expired. An expired Clear is due for Re-KYC."
    )
    sanctions: CheckStateValue = Field(
        description=(
            "The latest real sanctions result in the current cycle: PASSED (or REVIEW "
            "with an ACCEPTED review), FAILED (or REVIEW with a REJECTED review), "
            "PENDING, or MISSING when none has been recorded."
        )
    )
    aml: CheckStateValue = Field(description="The same, for AML.")


class CheckCycleResponse(BaseModel):
    """One KYC/KYB round of a company's background check."""

    id: uuid.UUID
    company_id: uuid.UUID
    number: int
    kind: str = Field(description="INITIAL (cycle 1), RE_KYC, RE_KYB or FULL.")
    reason: str | None
    started_at: datetime
    started_by: str = Field(
        description=(
            "Who started it (a user id), or the migration or code path that created "
            "cycle 1."
        )
    )
    started_by_name: str | None = None
    source: str
    rules_version: str | None
    is_current: bool


class BackgroundCheckCycleActionResponse(BaseModel):
    """A new cycle this caller may start now — the Re-KYC / Re-KYB buttons."""

    kind: str
    reason_required: bool
    reopens: bool = Field(
        description=(
            "Starting it also moves this CLEAR company back to IN_REVIEW, in the same "
            "request, so handovers pause until the new cycle is cleared."
        )
    )

    @classmethod
    def from_view(cls, action: BackgroundCheckCycleAction) -> BackgroundCheckCycleActionResponse:
        return cls(
            kind=action.kind, reason_required=action.reason_required, reopens=action.reopens
        )


class CheckCycleListResponse(BaseModel):
    """Every cycle of one company, cycle 1 first."""

    cycles: list[CheckCycleResponse]
    current_cycle_id: uuid.UUID | None


class StartCheckCycleRequest(BaseModel):
    """Start a Re-KYC or Re-KYB. Who starts it comes from the session."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["RE_KYC", "RE_KYB"]
    reason: Annotated[str, Field(min_length=1, max_length=4000)]


class StartCheckCycleResponse(BaseModel):
    cycle: CheckCycleResponse
    reopen_decision: BackgroundCheckDecisionResponse | None = Field(
        default=None,
        description="The CLEAR → IN_REVIEW decision recorded with it, when the company was CLEAR.",
    )


# ── Maker-checker, required checks, expiry ──────────────────────────────────

ProposalStatusValue = Literal["OPEN", "APPROVED", "REJECTED", "WITHDRAWN"]
ReviewActionValue = Literal["CLAIM", "RELEASE", "ASSIGN"]
ProposalActionValue = Literal["APPROVE", "REJECT", "WITHDRAW"]


class BackgroundCheckProposalResponse(BaseModel):
    """A proposed CLEAR, FLAGGED or ON_HOLD, and how it ended once resolved."""

    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str | None = Field(
        default=None, description="The company's name (no identifier is ever carried)."
    )
    based_on_decision_id: uuid.UUID
    from_value: BackgroundCheckState
    to_value: BackgroundCheckState
    risk_rating: BackgroundCheckRisk | None
    reason: str
    proposed_by: str
    proposed_by_name: str | None = None
    proposed_at: datetime
    cycle_id: uuid.UUID
    cycle_number: int | None = None
    rules_version: str
    evidence_count: int = Field(description="How many items the proposed decision rests on.")
    status: ProposalStatusValue = Field(
        description="OPEN while awaiting approval; then APPROVED, REJECTED or WITHDRAWN."
    )
    resolved_by: str | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    decision_id: uuid.UUID | None = Field(
        default=None, description="The decision an approval wrote."
    )
    stale_reason: str | None = Field(
        default=None,
        description=(
            "Set on an open proposal that can no longer be approved because the check "
            "or its inputs moved since; it can only be rejected or withdrawn. Served on "
            "the company's own reads, not in the cross-company queue."
        ),
    )
    allowed_actions: list[ProposalActionValue] = Field(
        default_factory=list,
        description=(
            "What **this caller** may do with it: the proposer may WITHDRAW; another "
            "COMPLIANCE user may APPROVE (unless stale) and REJECT — unless they "
            "are the review's reviewer or the company's RM, and APPROVE a HIGH or "
            "CRITICAL CLEAR only as a senior checker. Holders of "
            "compliance:assign may also WITHDRAW."
        ),
    )
    approval_blocked_reason: str | None = Field(
        default=None,
        description=(
            "Why this caller may not approve it, in words a screen can show beside a "
            "disabled Approve: the reviewer, the RM, or a senior approval needed."
        ),
    )
    needs_senior_approval: bool = Field(
        default=False,
        description="A CLEAR at HIGH or CRITICAL risk: only a senior checker approves it.",
    )
    due_at: datetime | None = Field(
        default=None, description="When the approval is due (business time), while open."
    )
    is_due_soon: bool = False
    is_overdue: bool = False
    eligible_checker_count: int | None = Field(
        default=None,
        description=(
            "How many active users could approve it now. 0 means nobody can, and a "
            "lead must step in."
        ),
    )


class BackgroundCheckProposalListResponse(BaseModel):
    proposals: list[BackgroundCheckProposalResponse]
    total: int
    limit: int
    offset: int


class RejectBackgroundCheckProposalRequest(BaseModel):
    """Reject a proposal. The reason is required; who rejects comes from the session."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=1, max_length=4000)]


class WithdrawBackgroundCheckProposalRequest(BaseModel):
    """Withdraw one's own proposal. The reason is optional."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=1, max_length=4000)] | None = None


class ApproveBackgroundCheckProposalResponse(BaseModel):
    decision: BackgroundCheckDecisionResponse
    proposal: BackgroundCheckProposalResponse


class RequiredCheckResponse(BaseModel):
    """One verification type CLEAR requires, and its state in the current cycle."""

    verification_type: str
    state: CheckStateValue = Field(
        description=(
            "PASSED (the latest real result is PASSED, or REVIEW with an ACCEPTED "
            "review), FAILED, PENDING, or MISSING."
        )
    )


class ReKycDueCompanyResponse(BaseModel):
    """A CLEAR company whose Clear has expired or expires before `before`."""

    company_id: uuid.UUID
    company_name: str | None
    journey: str
    background_check: BackgroundCheckState
    expires_at: datetime
    is_expired: bool
    current_cycle_number: int | None
    #: `IN_PIPELINE`, or `NOT_IN_PIPELINE` for a company that exists only as a buyer
    #: — so the list can say which renewals are for a buyer rather than a lead.
    pipeline_status: CompanyPipelineStatus


class ReKycDueListResponse(BaseModel):
    companies: list[ReKycDueCompanyResponse]
    total: int
    limit: int
    offset: int
    before: datetime = Field(description="The cut-off applied: expiring before this.")


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
            "recorded risk, to be labelled as such."
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
    compliance: CompanyComplianceFactsResponse
    current_cycle: CheckCycleResponse | None = Field(
        default=None,
        description="The cycle the check decides on now; null before the company has one.",
    )
    allowed_cycle_actions: list[BackgroundCheckCycleActionResponse] = Field(
        default_factory=list,
        description=(
            "The new cycles this caller may start now (Re-KYC, Re-KYB). Empty for a "
            "role that may not, on a FLAGGED or ON_HOLD company, while the current "
            "cycle has nothing recorded in it, or while a proposal awaits approval."
        ),
    )
    awaiting_approval: bool = Field(
        default=False,
        description=(
            "A proposed CLEAR, FLAGGED or ON_HOLD awaits a second approver. The gauge "
            "has not moved (it reads IN_REVIEW, or FLAGGED for a proposed ON_HOLD), and "
            "`allowed_moves` is empty until it is approved, rejected or withdrawn."
        ),
    )
    open_proposal: BackgroundCheckProposalResponse | None = None
    required_checks: list[RequiredCheckResponse] = Field(
        default_factory=list,
        description=(
            "The verification types CLEAR requires (KYB, AML, SANCTIONS) and "
            "the state of each in the current cycle."
        ),
    )
    rekyc_due: bool = Field(
        default=False,
        description=(
            "CLEAR, and the Clear has expired or expires within the Re-KYC window. An "
            "expired Clear still reads CLEAR — nothing moves the gauge — but no longer "
            "promotes the company or lets its deals be handed over."
        ),
    )
    reviewer_id: str | None = Field(
        default=None, description="Who holds the review; null when unassigned or not under review."
    )
    reviewer_name: str | None = None
    reviewer_assigned_at: datetime | None = None
    reviewer_inactive: bool = Field(
        default=False, description="The reviewer's account is deactivated: reassign it."
    )
    review_actions: list[ReviewActionValue] = Field(
        default_factory=list,
        description=(
            "What this caller may do with who holds the review: CLAIM (assign to me), "
            "RELEASE (back to Awaiting review), ASSIGN (to anyone; ADMIN or "
            "compliance:assign)."
        ),
    )
    relationship_manager_required: bool = Field(
        default=False,
        description=(
            "Starting the check needs a relationship manager in the same request: the "
            "company is in the pipeline, NOT_STARTED and has no RM."
        ),
    )


class RecordBackgroundCheckDecisionRequest(BaseModel):
    """A move, as a client may ask for it.

    Four fields, and `extra="forbid"`. The actor comes from the login session, the
    source and decided-by kind are the server's, and the evidence snapshot is
    assembled by the server from the compliance-inputs seam and the CRM's documents. A
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
    relationship_manager_user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "On a start (NOT_STARTED → IN_REVIEW) of an in-pipeline company with no RM: "
            "the RM to set in the same transaction. An RM names themselves; ADMIN or "
            "exporters:assign_rm may name any RM. Without it such a start is refused "
            "(409 `RELATIONSHIP_MANAGER_REQUIRED`)."
        ),
    )


class BackgroundCheckDecisionListResponse(BaseModel):
    """A company's decisions, newest first."""

    decisions: list[BackgroundCheckDecisionResponse]
    total: int
    limit: int
    offset: int


# ── One decision's evidence, resolved ───────────────────────────────────────


class DecisionEvidencePinnedReview(BaseModel):
    id: uuid.UUID
    review_status: str
    reviewed_by: str
    reviewed_by_name: str | None = None
    reviewed_at: datetime
    note: str | None


class DecisionEvidenceVerification(BaseModel):
    """A pinned verification result, as it stands (its outcome is frozen once reviewed)."""

    verification_result_id: uuid.UUID
    verification_type: str
    status: str
    risk_level: str | None
    provider: str = Field(description="The provider as stored (`manual` for a person).")
    provenance: Literal["MANUAL", "STUB", "PROVIDER"]
    is_placeholder: bool
    performed_at: datetime
    recorded_by: str | None = Field(
        description="Who recorded it (null for a result older than the history log)."
    )
    recorded_by_name: str | None = None
    evidence_note: str | None
    evidence_refs: list[VerificationEvidenceRefOut]
    pinned_review: DecisionEvidencePinnedReview | None = Field(
        description="The review the decision rested on; null if it had none yet."
    )
    review_superseded: bool = Field(
        description="A later review has been recorded since the decision."
    )
    cycle_id: uuid.UUID | None


class DecisionEvidenceScreeningItem(BaseModel):
    """The exact screening answer pinned (the checklist keeps every answer)."""

    screening_review_item_id: uuid.UUID
    item_key: str
    label: str
    retired: bool = Field(
        description="The item has since left the checklist (e.g. the website review)."
    )
    status: str
    comment: str | None
    evidence_refs: list[VerificationEvidenceRefOut]
    reviewed_by: str | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    cycle_id: uuid.UUID | None


class DecisionEvidenceDocument(BaseModel):
    """A pinned company document. Open it through the documents routes."""

    crm_document_id: uuid.UUID
    file_name: str
    category: str
    document_type: str
    scan_status: str
    is_downloadable: bool
    uploaded_by: str | None
    uploaded_by_name: str | None = None
    uploaded_at: datetime


class DecisionEvidenceItemResponse(BaseModel):
    """One pinned id, resolved. Exactly the detail for `kind` is set (all three are null
    only for a pinned row that can no longer be found)."""

    kind: str
    verification: DecisionEvidenceVerification | None = None
    screening_item: DecisionEvidenceScreeningItem | None = None
    document: DecisionEvidenceDocument | None = None


class DecisionEvidenceResponse(BaseModel):
    """What one decision rested on, readable."""

    decision_id: uuid.UUID
    company_id: uuid.UUID
    to_value: BackgroundCheckState
    rules_version: str = Field(
        description="The Clear rules it was taken under (a legacy decision reads as v1)."
    )
    cycle_id: uuid.UUID | None
    cycle_number: int | None
    items: list[DecisionEvidenceItemResponse]


__all__ = [
    "ApproveBackgroundCheckProposalResponse",
    "BackgroundCheckProposalListResponse",
    "BackgroundCheckProposalResponse",
    "ReKycDueCompanyResponse",
    "ReKycDueListResponse",
    "RejectBackgroundCheckProposalRequest",
    "RequiredCheckResponse",
    "WithdrawBackgroundCheckProposalRequest",
    "BackgroundCheckCycleActionResponse",
    "CheckCycleListResponse",
    "CheckCycleResponse",
    "CompanyComplianceFactsResponse",
    "DecisionEvidenceDocument",
    "DecisionEvidenceItemResponse",
    "DecisionEvidencePinnedReview",
    "DecisionEvidenceResponse",
    "DecisionEvidenceScreeningItem",
    "DecisionEvidenceVerification",
    "StartCheckCycleRequest",
    "StartCheckCycleResponse",
    "BackgroundCheckDecisionListResponse",
    "BackgroundCheckDecisionResponse",
    "BackgroundCheckMoveResponse",
    "BackgroundCheckResponse",
    "EvidenceItemResponse",
    "RecordBackgroundCheckDecisionRequest",
]


# ── Who holds the review, and the worklists ─────────────────────────────────


class AssignReviewerRequest(BaseModel):
    """Assign or reassign a review. A reason is required to take it from someone."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=1000)


class ReleaseReviewRequest(BaseModel):
    """Hand a review back to Awaiting review, with an optional note."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)


WorkStageValue = Literal["review", "info", "approval"]


class ComplianceWorkItemResponse(BaseModel):
    """One company's open compliance work. Names and times only — never an
    identifier, and never a decision's reason."""

    company_id: uuid.UUID
    company_name: str | None
    journey: str
    pipeline_status: CompanyPipelineStatus
    background_check: BackgroundCheckState
    stage: WorkStageValue = Field(
        description="review (with or awaiting a reviewer), info (waiting on information) "
        "or approval (a proposal awaits its checker)."
    )
    relationship_manager_id: str | None
    relationship_manager_name: str | None = None
    relationship_manager_inactive: bool = False
    reviewer_id: str | None
    reviewer_name: str | None = None
    reviewer_inactive: bool = False
    waiting_since: datetime
    due_at: datetime | None = Field(
        default=None, description="Null for a review nobody has picked up yet."
    )
    is_due_soon: bool
    is_overdue: bool
    rejection_count: int = Field(description="Proposals returned since the check last moved.")
    proposal_id: uuid.UUID | None = None
    proposed_by_name: str | None = None
    proposal_to_value: BackgroundCheckState | None = None
    risk_rating: BackgroundCheckRisk | None = None
    needs_senior_approval: bool = False
    eligible_checker_count: int | None = None
    needs_attention: bool = False
    info_note: str | None = Field(
        default=None,
        description="What the information request asked for: on the information list only.",
    )


class ComplianceWorklistResponse(BaseModel):
    view: str
    items: list[ComplianceWorkItemResponse]
    total: int


class WorklistCountsResponse(BaseModel):
    """The nav badges. A list this caller may not see is null, not 0."""

    awaiting_review: int | None
    my_reviews: int | None
    awaiting_approval: int | None
    info_requested: int
    overdue: int | None
    needs_attention: int | None


class RecentDecisionResponse(BaseModel):
    """An outcome on a company the caller owns or reviewed. No reason text."""

    company_id: uuid.UUID
    company_name: str | None
    decision_id: uuid.UUID
    to_value: BackgroundCheckState
    risk_rating: BackgroundCheckRisk | None
    decided_at: datetime
    decided_by_name: str | None = None
    approved_by_name: str | None = None


class RecentDecisionListResponse(BaseModel):
    decisions: list[RecentDecisionResponse]
    days: int
