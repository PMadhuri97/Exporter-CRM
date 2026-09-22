import uuid

from pydantic import BaseModel, Field

from app.modules.compliance.domain.entities.compliance import (
    ApprovalDecision,
    ApproverRole,
    CaseStatus,
    CaseType,
    ScreeningStatus,
    ScreeningType,
)
from app.modules.payments import TransactionStatus

# ── Screening ─────────────────────────────────────────────────────────────────


class ScreeningResult(BaseModel):
    screening_id: uuid.UUID
    screening_type: ScreeningType
    status: ScreeningStatus
    provider: str | None
    result_payload: dict | None
    created_at: str


class ScreeningRunResponse(BaseModel):
    transaction_id: uuid.UUID
    transaction_status: TransactionStatus
    edd_required: bool = Field(
        description="True when DNFBP classification triggers Enhanced Due Diligence"
    )
    screenings: list[ScreeningResult]


# ── Approvals ─────────────────────────────────────────────────────────────────


class SubmitApprovalRequest(BaseModel):
    transaction_id: uuid.UUID
    decision: ApprovalDecision
    notes: str | None = Field(default=None, max_length=2000)


class ApprovalResult(BaseModel):
    approval_id: uuid.UUID
    approver_role: ApproverRole
    decision: ApprovalDecision
    notes: str | None
    created_at: str


class ApprovalSubmittedResponse(BaseModel):
    approval_id: uuid.UUID
    approver_role: ApproverRole
    decision: ApprovalDecision
    created_at: str


class ApprovalsStateResponse(BaseModel):
    transaction_id: uuid.UUID
    transaction_status: TransactionStatus
    approvals: list[ApprovalResult]


# ── Cases (read-only in this phase) ──────────────────────────────────────────


class CaseResult(BaseModel):
    case_id: uuid.UUID
    case_type: CaseType
    status: CaseStatus
    created_at: str
