import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.models import AppendOnlyModel

SCHEMA = "compliance"
PAYMENTS_SCHEMA = "payments"


class ScreeningType(str, enum.Enum):
    SANCTIONS_OFAC = "SANCTIONS_OFAC"
    SANCTIONS_UN = "SANCTIONS_UN"
    SANCTIONS_EU = "SANCTIONS_EU"
    SANCTIONS_RBI = "SANCTIONS_RBI"
    AML_RISK = "AML_RISK"
    DNFBP = "DNFBP"


class ScreeningStatus(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ApproverRole(str, enum.Enum):
    MAKER = "MAKER"
    CHECKER = "CHECKER"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CaseType(str, enum.Enum):
    SANCTIONS_HIT = "SANCTIONS_HIT"
    FAILED_SETTLEMENT = "FAILED_SETTLEMENT"
    RECONCILIATION_BREAK = "RECONCILIATION_BREAK"
    DNFBP_EDD = "DNFBP_EDD"


class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class ComplianceScreening(AppendOnlyModel):
    """Immutable — screenings are never modified once written."""

    __tablename__ = "compliance_screenings"
    __table_args__ = ({"schema": SCHEMA},)

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    screening_type: Mapped[ScreeningType] = mapped_column(
        Enum(ScreeningType, name="screening_type_enum", schema=SCHEMA), nullable=False
    )
    status: Mapped[ScreeningStatus] = mapped_column(
        Enum(ScreeningStatus, name="screening_status_enum", schema=SCHEMA), nullable=False
    )
    provider: Mapped[str | None] = mapped_column(nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ComplianceApproval(AppendOnlyModel):
    """
    Immutable maker-checker record.
    UNIQUE (transaction_id, approver_user_id) enforces that the same person
    cannot be both MAKER and CHECKER on the same transaction.
    """

    __tablename__ = "compliance_approvals"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    approver_role: Mapped[ApproverRole] = mapped_column(
        Enum(ApproverRole, name="approver_role_enum", schema=SCHEMA), nullable=False
    )
    approver_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, name="approval_decision_enum", schema=SCHEMA), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Prevents the same user from approving the same transaction in any role
        UniqueConstraint(
            "transaction_id",
            "approver_user_id",
            name="uq_compliance_approvals_transaction_approver",
        ),
        {"schema": SCHEMA},
    )


class ComplianceCase(AppendOnlyModel):
    __tablename__ = "compliance_cases"
    __table_args__ = ({"schema": SCHEMA},)

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{PAYMENTS_SCHEMA}.transactions.transaction_id", ondelete="RESTRICT"),
        nullable=False,
    )
    case_type: Mapped[CaseType] = mapped_column(
        Enum(CaseType, name="case_type_enum", schema=SCHEMA), nullable=False
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status_enum", schema=SCHEMA),
        nullable=False,
        default=CaseStatus.OPEN,
    )
