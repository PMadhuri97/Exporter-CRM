"""``CompanyBankAccountService`` — a company's bank accounts.

Propose, approve, verify — and reject, make primary, deactivate and reveal.

* **Propose** (``exporters:manage_bank_accounts``) a new account, or a change to a
  verified one (``replaces_id``): a new row, ``PENDING_APPROVAL``. The account number
  and IBAN are encrypted before they reach the session. With approvals turned off
  (``CRM_BANK_CHANGE_APPROVAL_MODE=OFF``) a proposal is approved as it is made.
* **Approve** — who may is the approval mode's rule (``domain/approval_mode.py``):
  ``PENDING_APPROVAL`` -> ``PENDING_VERIFICATION``. **Reject** either pending state,
  with a reason.
* **Verify** (``exporters:approve_bank_accounts``) with a cancelled cheque or bank
  letter on the company's record, or a passed ``BANK_ACCOUNT`` verification of the
  company: -> ``VERIFIED``. A verified change retires the account it replaces and takes
  over its primary flag; a company's first verified account in a currency becomes its
  primary.
* **Primary** — only a verified account, one per currency.
* **Deactivate** a verified account, with a reason.
* **Reveal** (``exporters:view_bank_details``) the full number: audited.

Every write is one ``bank_account`` history row and one audit event; neither ever
carries more than the last four characters of a number. Writes lock the company row
first, so two approvals of the same company's accounts queue.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.application.compliance_settings import bank_change_approval_mode
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.approval_mode import ApprovalMode, approval_refusal
from app.modules.onboarding.domain.entities.company_bank_account import CompanyBankAccount
from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationResultStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.storage import DocumentScanStatus
from app.modules.onboarding.exceptions import (
    BankAccountApprovalRefusedError,
    BankAccountNotFoundError,
    BankAccountWrongStatusError,
    ExporterProfileNotFoundError,
)
from app.platform.security.field_cipher import decrypt_field, encrypt_field
from app.shared import clock
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

MANAGE = "exporters:manage_bank_accounts"
APPROVE = "exporters:approve_bank_accounts"

#: The associated data each encrypted column is sealed with.
NUMBER_PURPOSE = "company_bank_account.account_number"
IBAN_PURPOSE = "company_bank_account.iban"

PENDING_APPROVAL = "PENDING_APPROVAL"
PENDING_VERIFICATION = "PENDING_VERIFICATION"
VERIFIED = "VERIFIED"
REJECTED = "REJECTED"
INACTIVE = "INACTIVE"
#: Proof a person checks by hand, and the one a provider returns.
DOCUMENT_METHODS = frozenset({"CANCELLED_CHEQUE", "BANK_LETTER"})
RESULT_METHOD = "PENNY_DROP"

BANK_ACCOUNT_PROPOSED = "crm.bank_account.proposed"
BANK_ACCOUNT_APPROVED = "crm.bank_account.approved"
BANK_ACCOUNT_REJECTED = "crm.bank_account.rejected"
BANK_ACCOUNT_VERIFIED = "crm.bank_account.verified"
BANK_ACCOUNT_PRIMARY_SET = "crm.bank_account.primary_set"
BANK_ACCOUNT_DEACTIVATED = "crm.bank_account.deactivated"
BANK_ACCOUNT_REVEALED = "crm.bank_account.revealed"

_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_SWIFT = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_IBAN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
_ACCOUNT = re.compile(r"^[A-Z0-9]{6,34}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class Actor:
    id: str
    name: str | None
    permissions: frozenset[str]


@dataclass(frozen=True)
class RevealedNumbers:
    account_number: str | None
    iban: str | None


def _compact(value: object) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[\s-]", "", str(value)).upper()
    return cleaned or None


def normalise_proposal(fields: Mapping[str, object]) -> dict[str, object]:
    """Check and tidy a proposal's fields: identifiers upper-cased with spaces removed,
    each checked for its shape, and a number the bank can be found by."""
    out = dict(fields)
    number = _compact(fields.get("account_number"))
    iban = _compact(fields.get("iban"))
    ifsc = _compact(fields.get("ifsc"))
    swift = _compact(fields.get("swift_bic"))
    currency = _compact(fields.get("currency"))
    if number is None and iban is None:
        raise ValidationError("Give the account number or the IBAN")
    if number is not None and not _ACCOUNT.match(number):
        raise ValidationError("The account number must be 6–34 letters or digits")
    if iban is not None and not _IBAN.match(iban):
        raise ValidationError("The IBAN is not in the right form, e.g. NL91ABNA0417164300")
    if ifsc is not None and not _IFSC.match(ifsc):
        raise ValidationError("The IFSC must be 11 characters, e.g. HDFC0001234")
    if swift is not None and not _SWIFT.match(swift):
        raise ValidationError("The SWIFT/BIC must be 8 or 11 characters, e.g. HDFCINBBXXX")
    if number is not None and iban is None and ifsc is None and swift is None:
        raise ValidationError("An account number needs the IFSC or the SWIFT/BIC of its bank")
    if currency is None or not _CURRENCY.match(currency):
        raise ValidationError("The currency must be a three-letter ISO 4217 code, e.g. INR")
    out.update(
        account_number=number, iban=iban, ifsc=ifsc, swift_bic=swift, currency=currency
    )
    return out


class CompanyBankAccountService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    # ── Reads ────────────────────────────────────────────────────────────────

    async def list_for_company(self, customer_id: uuid.UUID) -> list[CompanyBankAccount]:
        """Every version, newest first; the screen groups them by status."""
        await self._require_company(customer_id, lock=False)
        return list(
            await self._db.scalars(
                select(CompanyBankAccount)
                .where(CompanyBankAccount.customer_id == customer_id)
                .order_by(CompanyBankAccount.created_at.desc())
            )
        )

    async def pending(self) -> list[CompanyBankAccount]:
        """Every account waiting on someone: approval or verification, oldest first."""
        return list(
            await self._db.scalars(
                select(CompanyBankAccount)
                .where(CompanyBankAccount.status.in_((PENDING_APPROVAL, PENDING_VERIFICATION)))
                .order_by(CompanyBankAccount.created_at)
            )
        )

    # ── Propose ──────────────────────────────────────────────────────────────

    async def propose(
        self,
        customer_id: uuid.UUID,
        *,
        fields: Mapping[str, object],
        reason: str | None,
        replaces_id: uuid.UUID | None,
        actor: Actor,
    ) -> CompanyBankAccount:
        await self._require_company(customer_id, lock=True)
        clean = normalise_proposal(fields)
        if replaces_id is not None:
            replaced = await self._get(replaces_id, lock=True)
            if replaced.customer_id != customer_id:
                raise BankAccountNotFoundError(replaces_id)
            if replaced.status != VERIFIED:
                raise BankAccountWrongStatusError(replaces_id, replaced.status, "replaced")
            open_change = await self._db.scalar(
                select(CompanyBankAccount.id).where(
                    CompanyBankAccount.replaces_id == replaces_id,
                    CompanyBankAccount.status.in_((PENDING_APPROVAL, PENDING_VERIFICATION)),
                )
            )
            if open_change is not None:
                raise ValidationError(
                    "A change to this account is already waiting; approve or reject it first"
                )

        number, iban = clean.pop("account_number"), clean.pop("iban")
        account = CompanyBankAccount(
            customer_id=customer_id,
            account_holder_name=str(clean["account_holder_name"]).strip(),
            bank_name=str(clean["bank_name"]).strip(),
            branch=clean.get("branch"),
            account_number_encrypted=(
                encrypt_field(str(number), purpose=NUMBER_PURPOSE) if number else None
            ),
            account_number_last4=str(number)[-4:] if number else None,
            iban_encrypted=encrypt_field(str(iban), purpose=IBAN_PURPOSE) if iban else None,
            iban_last4=str(iban)[-4:] if iban else None,
            ifsc=clean.get("ifsc"),
            swift_bic=clean.get("swift_bic"),
            currency=str(clean["currency"]),
            account_type=str(clean["account_type"]),
            ad_code=clean.get("ad_code"),
            status=PENDING_APPROVAL,
            replaces_id=replaces_id,
            proposed_by=actor.id,
            proposal_reason=(reason or "").strip() or None,
        )
        self._db.add(account)
        await self._db.flush()
        await self._write(account, BANK_ACCOUNT_PROPOSED, "bank_account_proposed", actor,
                          reason=account.proposal_reason)
        if bank_change_approval_mode() is ApprovalMode.OFF:
            account.status = PENDING_VERIFICATION
            account.approved_at = clock.now()
            await self._write(account, BANK_ACCOUNT_APPROVED, "bank_account_approved", actor,
                              details={"automatic": True})
        await self._commit(account)
        return account

    # ── Approve / reject ─────────────────────────────────────────────────────

    async def approve(self, account_id: uuid.UUID, *, actor: Actor) -> CompanyBankAccount:
        account = await self._locked(account_id)
        if account.status != PENDING_APPROVAL:
            raise BankAccountWrongStatusError(account_id, account.status, "approved")
        refusal = approval_refusal(
            bank_change_approval_mode(),
            proposer_id=account.proposed_by,
            approver_id=actor.id,
            approver_permissions=actor.permissions,
            propose_permission=MANAGE,
            approve_permission=APPROVE,
        )
        if refusal is not None:
            raise BankAccountApprovalRefusedError(refusal)
        account.status = PENDING_VERIFICATION
        account.approved_by = actor.id
        account.approved_at = clock.now()
        await self._write(account, BANK_ACCOUNT_APPROVED, "bank_account_approved", actor)
        await self._commit(account)
        return account

    async def reject(
        self, account_id: uuid.UUID, *, reason: str, actor: Actor
    ) -> CompanyBankAccount:
        account = await self._locked(account_id)
        if account.status not in (PENDING_APPROVAL, PENDING_VERIFICATION):
            raise BankAccountWrongStatusError(account_id, account.status, "rejected")
        reason = reason.strip()
        if not reason:
            raise ValidationError("A reason is required to reject a bank account")
        previous = account.status
        account.status = REJECTED
        account.rejected_by = actor.id
        account.rejected_at = clock.now()
        account.rejection_reason = reason
        await self._write(account, BANK_ACCOUNT_REJECTED, "bank_account_rejected", actor,
                          reason=reason, from_value=previous)
        await self._commit(account)
        return account

    # ── Verify ───────────────────────────────────────────────────────────────

    async def verify(
        self,
        account_id: uuid.UUID,
        *,
        method: str,
        evidence_document_id: uuid.UUID | None,
        verification_result_id: uuid.UUID | None,
        actor: Actor,
    ) -> CompanyBankAccount:
        account = await self._locked(account_id)
        if account.status != PENDING_VERIFICATION:
            raise BankAccountWrongStatusError(account_id, account.status, "verified")
        if method in DOCUMENT_METHODS:
            if evidence_document_id is None:
                raise ValidationError("Attach the cancelled cheque or bank letter")
            await self._require_evidence_document(account.customer_id, evidence_document_id)
            verification_result_id = None
        elif method == RESULT_METHOD:
            if verification_result_id is None:
                raise ValidationError("Link the passed bank-account verification")
            await self._require_passed_result(account.customer_id, verification_result_id)
            evidence_document_id = None
        else:
            raise ValidationError(f"Unknown verification method {method!r}")

        account.status = VERIFIED
        account.verification_method = method
        account.evidence_document_id = evidence_document_id
        account.verification_result_id = verification_result_id
        account.verified_by = actor.id
        account.verified_at = clock.now()

        took_primary = False
        if account.replaces_id is not None:
            replaced = await self._get(account.replaces_id, lock=True)
            if replaced.status == VERIFIED:
                took_primary = replaced.is_primary
                replaced.is_primary = False
                replaced.status = INACTIVE
                replaced.deactivated_by = actor.id
                replaced.deactivated_at = clock.now()
                replaced.deactivation_reason = "Replaced by a verified change"
                await self._db.flush()
                await self._write(replaced, BANK_ACCOUNT_DEACTIVATED,
                                  "bank_account_deactivated", actor,
                                  reason=replaced.deactivation_reason, from_value=VERIFIED,
                                  details={"replaced_by": str(account.id)})
        if not took_primary:
            took_primary = await self._primary_of(account.customer_id, account.currency) is None
        if took_primary:
            await self._db.flush()
            account.is_primary = True
        await self._write(account, BANK_ACCOUNT_VERIFIED, "bank_account_verified", actor,
                          from_value=PENDING_VERIFICATION,
                          details={"method": method, "is_primary": account.is_primary})
        await self._commit(account)
        return account

    # ── Primary / deactivate ─────────────────────────────────────────────────

    async def set_primary(self, account_id: uuid.UUID, *, actor: Actor) -> CompanyBankAccount:
        account = await self._locked(account_id)
        if account.status != VERIFIED:
            raise BankAccountWrongStatusError(account_id, account.status, "made primary")
        if account.is_primary:
            return account
        await self._db.execute(
            update(CompanyBankAccount)
            .where(
                CompanyBankAccount.customer_id == account.customer_id,
                CompanyBankAccount.currency == account.currency,
                CompanyBankAccount.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
        await self._db.flush()
        account.is_primary = True
        await self._write(account, BANK_ACCOUNT_PRIMARY_SET, "bank_account_primary_set", actor)
        await self._commit(account)
        return account

    async def deactivate(
        self, account_id: uuid.UUID, *, reason: str, actor: Actor
    ) -> CompanyBankAccount:
        account = await self._locked(account_id)
        if account.status != VERIFIED:
            raise BankAccountWrongStatusError(account_id, account.status, "deactivated")
        reason = reason.strip()
        if not reason:
            raise ValidationError("A reason is required to deactivate a bank account")
        account.status = INACTIVE
        account.is_primary = False
        account.deactivated_by = actor.id
        account.deactivated_at = clock.now()
        account.deactivation_reason = reason
        await self._write(account, BANK_ACCOUNT_DEACTIVATED, "bank_account_deactivated", actor,
                          reason=reason, from_value=VERIFIED)
        await self._commit(account)
        return account

    # ── Reveal ───────────────────────────────────────────────────────────────

    async def reveal(self, account_id: uuid.UUID, *, actor: Actor) -> RevealedNumbers:
        """The full account number and IBAN. The audit event is committed before the
        numbers are returned: a reveal the trail does not show did not happen."""
        account = await self._get(account_id, lock=False)
        numbers = RevealedNumbers(
            account_number=(
                decrypt_field(account.account_number_encrypted, purpose=NUMBER_PURPOSE)
                if account.account_number_encrypted
                else None
            ),
            iban=(
                decrypt_field(account.iban_encrypted, purpose=IBAN_PURPOSE)
                if account.iban_encrypted
                else None
            ),
        )
        await self._audit(account, BANK_ACCOUNT_REVEALED, actor)
        await self._db.commit()
        return numbers

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require_company(self, customer_id: uuid.UUID, *, lock: bool) -> None:
        statement = select(ExporterProfile.customer_id).where(
            ExporterProfile.customer_id == customer_id
        )
        if lock:
            statement = statement.with_for_update()
        if await self._db.scalar(statement) is None:
            raise ExporterProfileNotFoundError(customer_id)

    async def _get(self, account_id: uuid.UUID, *, lock: bool) -> CompanyBankAccount:
        statement = select(CompanyBankAccount).where(CompanyBankAccount.id == account_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        account = await self._db.scalar(statement)
        if account is None:
            raise BankAccountNotFoundError(account_id)
        return account

    async def _locked(self, account_id: uuid.UUID) -> CompanyBankAccount:
        """The company row, then the account — the order every write takes."""
        customer_id = await self._db.scalar(
            select(CompanyBankAccount.customer_id).where(CompanyBankAccount.id == account_id)
        )
        if customer_id is None:
            raise BankAccountNotFoundError(account_id)
        await self._require_company(customer_id, lock=True)
        return await self._get(account_id, lock=True)

    async def _primary_of(self, customer_id: uuid.UUID, currency: str) -> uuid.UUID | None:
        return await self._db.scalar(
            select(CompanyBankAccount.id).where(
                CompanyBankAccount.customer_id == customer_id,
                CompanyBankAccount.currency == currency,
                CompanyBankAccount.is_primary.is_(True),
            )
        )

    async def _require_evidence_document(
        self, customer_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        document = await self._db.get(CrmDocument, document_id)
        if document is None or document.company_id != customer_id:
            raise ValidationError("The evidence must be a document on this company's record")
        if document.scan_status is not DocumentScanStatus.AVAILABLE:
            raise ValidationError("The evidence document has not passed its scan")

    async def _require_passed_result(
        self, customer_id: uuid.UUID, result_id: uuid.UUID
    ) -> None:
        result = await self._db.get(VerificationResult, result_id)
        if (
            result is None
            or result.verification_type is not VerificationType.BANK_ACCOUNT
            or customer_id not in (result.subject_company_id, result.entity_reference)
        ):
            raise ValidationError("Link a bank-account verification of this company")
        if result.status is not VerificationResultStatus.PASSED:
            raise ValidationError("Only a passed bank-account verification can verify an account")

    async def _write(
        self,
        account: CompanyBankAccount,
        audit_event: str,
        history_event: str,
        actor: Actor,
        *,
        reason: str | None = None,
        from_value: str | None = None,
        details: dict | None = None,
    ) -> None:
        await self._history.record(
            account.customer_id,
            dimension=history_dimensions.BANK_ACCOUNT,
            event_type=history_event,
            from_value=from_value,
            to_value=account.status,
            reason=reason,
            actor_id=actor.id,
            source="company_bank_account_service",
            details={**_summary(account), **(details or {})},
        )
        await self._audit(account, audit_event, actor, extra=details)

    async def _audit(
        self,
        account: CompanyBankAccount,
        event: str,
        actor: Actor,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        await AuditService(self._db).record(
            event,
            actor_id=uuid.UUID(actor.id),
            actor_type=ActorType.COMPLIANCE_OFFICER,
            payload={
                "subject_type": "bank_account",
                "subject_id": str(account.id),
                "company_id": str(account.customer_id),
                "status": account.status,
                "actor_name": actor.name,
                **_summary(account),
                **(extra or {}),
            },
        )

    async def _commit(self, account: CompanyBankAccount) -> None:
        await self._db.commit()
        await self._db.refresh(account)
        logger.info(
            "company_bank_account.changed",
            account_id=str(account.id),
            customer_id=str(account.customer_id),
            status=account.status,
        )


def _summary(account: CompanyBankAccount) -> dict[str, object]:
    """What a history row or audit event may say about an account: never more than the
    last four characters of a number."""
    return {
        "bank_account_id": str(account.id),
        "bank_name": account.bank_name,
        "currency": account.currency,
        "account_type": account.account_type,
        "account_last4": account.account_number_last4 or account.iban_last4,
        "replaces_id": str(account.replaces_id) if account.replaces_id else None,
    }


def actor_from(user: object, permissions: Collection[tuple[str, str]]) -> Actor:
    """The signed-in user as this service needs them, with the request's resolved
    permissions as ``module:action`` strings."""
    return Actor(
        id=str(user.id),  # type: ignore[attr-defined]
        name=getattr(user, "full_name", None) or getattr(user, "email", None),
        permissions=frozenset(f"{module}:{action}" for module, action in permissions),
    )
