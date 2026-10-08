"""Request and response shapes for a company's bank accounts.

A response never carries a full account number or IBAN: only ``••••`` and the last
four characters. The full values come from the reveal route alone.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Short = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=40)]


class BankAccountType(str, enum.Enum):
    CURRENT = "CURRENT"
    EEFC = "EEFC"
    SAVINGS = "SAVINGS"
    OTHER = "OTHER"


class BankAccountStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INACTIVE = "INACTIVE"


class BankVerificationMethod(str, enum.Enum):
    CANCELLED_CHEQUE = "CANCELLED_CHEQUE"
    BANK_LETTER = "BANK_LETTER"
    PENNY_DROP = "PENNY_DROP"


class ProposeBankAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_holder_name: _Name
    bank_name: _Name
    branch: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=255)] = None
    account_number: _Short = None
    iban: _Short = None
    ifsc: _Short = None
    swift_bic: _Short = None
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217, e.g. INR")
    account_type: BankAccountType
    ad_code: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20)] = None
    #: Why this account, or why the change.
    reason: str | None = Field(default=None, max_length=2000)
    #: The verified account this one replaces; it stays in force until this is verified.
    replaces_id: uuid.UUID | None = None


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class VerifyBankAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: BankVerificationMethod
    #: The cancelled cheque or bank letter, a document on the company's record.
    evidence_document_id: uuid.UUID | None = None
    #: A passed BANK_ACCOUNT verification of the company (penny drop).
    verification_result_id: uuid.UUID | None = None


def _masked(last4: str | None) -> str | None:
    return f"••••{last4}" if last4 else None


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    account_holder_name: str
    bank_name: str
    branch: str | None
    account_number_last4: str | None = Field(exclude=True)
    iban_last4: str | None = Field(exclude=True)
    ifsc: str | None
    swift_bic: str | None
    currency: str
    account_type: BankAccountType
    ad_code: str | None
    is_primary: bool
    status: BankAccountStatus
    replaces_id: uuid.UUID | None
    proposed_by: str | None
    proposed_by_name: str | None = None
    proposal_reason: str | None
    approved_by: str | None
    approved_by_name: str | None = None
    approved_at: datetime | None
    rejected_by: str | None
    rejected_at: datetime | None
    rejection_reason: str | None
    verification_method: BankVerificationMethod | None
    evidence_document_id: uuid.UUID | None
    verification_result_id: uuid.UUID | None
    verified_by: str | None
    verified_by_name: str | None = None
    verified_at: datetime | None
    deactivated_at: datetime | None
    deactivation_reason: str | None
    created_at: datetime
    #: Whether this reader may approve it now, under the approval mode.
    can_approve: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def account_number_masked(self) -> str | None:
        return _masked(self.account_number_last4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def iban_masked(self) -> str | None:
        return _masked(self.iban_last4)


class BankAccountCapabilities(BaseModel):
    """What this reader may do here, so the screen offers only that."""

    can_propose: bool
    can_approve: bool
    can_reveal: bool


class BankAccountListResponse(BaseModel):
    accounts: list[BankAccountResponse]
    capabilities: BankAccountCapabilities


class PendingBankAccountResponse(BankAccountResponse):
    company_name: str | None = None


class PendingBankAccountListResponse(BaseModel):
    accounts: list[PendingBankAccountResponse]


class RevealedBankAccountResponse(BaseModel):
    id: uuid.UUID
    account_number: str | None
    iban: str | None
