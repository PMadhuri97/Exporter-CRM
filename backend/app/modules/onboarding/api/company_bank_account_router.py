"""A company's bank accounts.

* **Read** — every CRM reader (`exporters:view`), numbers masked to their last four.
* **Propose** a new account or a change — `exporters:manage_bank_accounts` (RMs and
  compliance).
* **Approve** — whoever the approval mode allows (`CRM_BANK_CHANGE_APPROVAL_MODE`):
  the route admits holders of the propose or approve permission and the service decides.
* **Reject, verify, make primary, deactivate** — `exporters:approve_bank_accounts`
  (compliance): which account a company is paid into is a compliance decision.
* **Reveal** the full number — `exporters:view_bank_details`, audited.
* **The queue** of accounts waiting for approval or verification — holders of either
  permission; it is the approval card on Compliance work.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.bank_account import (
    BankAccountCapabilities,
    BankAccountListResponse,
    BankAccountResponse,
    PendingBankAccountListResponse,
    PendingBankAccountResponse,
    ProposeBankAccountRequest,
    ReasonRequest,
    RevealedBankAccountResponse,
    VerifyBankAccountRequest,
)
from app.modules.onboarding.application.company_bank_account_service import (
    APPROVE,
    MANAGE,
    CompanyBankAccountService,
    actor_from,
)
from app.modules.onboarding.application.compliance_settings import bank_change_approval_mode
from app.modules.onboarding.domain.approval_mode import approval_refusal
from app.modules.onboarding.domain.entities.company_bank_account import CompanyBankAccount
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication import display_names
from app.platform.authentication.models import User
from app.platform.authorization.services import (
    get_current_permissions,
    has_permission,
    require_any_permission,
    require_permission,
)
from app.platform.database.services import get_db

router = APIRouter(tags=["Exporter CRM"])

_COMPANY_VIEW = require_permission("exporters", "view")
_PROPOSE = require_permission("exporters", "manage_bank_accounts")
_APPROVE = require_permission("exporters", "approve_bank_accounts")
_PROPOSE_OR_APPROVE = require_any_permission(
    ("exporters", "manage_bank_accounts"), ("exporters", "approve_bank_accounts")
)
_REVEAL = require_permission("exporters", "view_bank_details")
_PERMISSIONS = Annotated[frozenset[tuple[str, str]], Depends(get_current_permissions)]

_ACCOUNT_ERRORS = {
    401: {"description": "Unauthorized"},
    404: {"description": "No such bank account (BANK_ACCOUNT_NOT_FOUND)"},
    409: {"description": "Not in a state that allows this (BANK_ACCOUNT_WRONG_STATUS)"},
}


def _may_approve(account: CompanyBankAccount, actor) -> bool:
    return (
        account.status == "PENDING_APPROVAL"
        and approval_refusal(
            bank_change_approval_mode(),
            proposer_id=account.proposed_by,
            approver_id=actor.id,
            approver_permissions=actor.permissions,
            propose_permission=MANAGE,
            approve_permission=APPROVE,
        )
        is None
    )


async def _responses(
    db: AsyncSession, accounts: list[CompanyBankAccount], actor=None
) -> list[BankAccountResponse]:
    names = await display_names(
        db,
        [
            who
            for account in accounts
            for who in (account.proposed_by, account.approved_by, account.verified_by)
        ],
        email_fallback=True,
    )
    out = []
    for account in accounts:
        response = BankAccountResponse.model_validate(account)
        response.proposed_by_name = names.get(account.proposed_by or "")
        response.approved_by_name = names.get(account.approved_by or "")
        response.verified_by_name = names.get(account.verified_by or "")
        response.can_approve = actor is not None and _may_approve(account, actor)
        out.append(response)
    return out


async def _one(db: AsyncSession, account: CompanyBankAccount) -> BankAccountResponse:
    return (await _responses(db, [account]))[0]


@router.get(
    "/exporters/{customer_id}/bank-accounts",
    response_model=BankAccountListResponse,
    summary="A company's bank accounts",
    description=(
        "Every version, newest first, numbers masked to their last four "
        "(`account_number_masked`, `iban_masked`). `capabilities` says what this reader "
        "may do."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:view` permission required"},
        404: {"description": "Company not found"},
    },
)
async def list_bank_accounts(
    customer_id: uuid.UUID,
    current_user: Annotated[User, Depends(_COMPANY_VIEW)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountListResponse:
    accounts = await CompanyBankAccountService(db).list_for_company(customer_id)
    return BankAccountListResponse(
        accounts=await _responses(db, accounts, actor_from(current_user, permissions)),
        capabilities=BankAccountCapabilities(
            can_propose=has_permission(current_user, "exporters", "manage_bank_accounts"),
            can_approve=has_permission(current_user, "exporters", "approve_bank_accounts"),
            can_reveal=has_permission(current_user, "exporters", "view_bank_details"),
        ),
    )


@router.post(
    "/exporters/{customer_id}/bank-accounts",
    response_model=BankAccountResponse,
    status_code=201,
    summary="Propose a bank account, or a change to one",
    description=(
        "Starts PENDING_APPROVAL (PENDING_VERIFICATION when approvals are off). Give the "
        "account number (with its IFSC or SWIFT/BIC) or the IBAN. `replaces_id` names a "
        "verified account this one changes; that account stays in force until this one "
        "is verified."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:manage_bank_accounts` permission required"},
        404: {"description": "Company, or the account replaced, not found"},
        409: {"description": "The account replaced is not verified"},
        422: {"description": "Invalid details"},
        503: {"description": "No field encryption key is configured"},
    },
)
async def propose_bank_account(
    customer_id: uuid.UUID,
    body: ProposeBankAccountRequest,
    current_user: Annotated[User, Depends(_PROPOSE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    fields = body.model_dump(exclude={"reason", "replaces_id"})
    fields["account_type"] = body.account_type.value
    account = await CompanyBankAccountService(db).propose(
        customer_id,
        fields=fields,
        reason=body.reason,
        replaces_id=body.replaces_id,
        actor=actor_from(current_user, permissions),
    )
    return await _one(db, account)


@router.get(
    "/bank-accounts/pending",
    response_model=PendingBankAccountListResponse,
    summary="Bank accounts waiting for approval or verification",
    description=(
        "Oldest first, with each company's name and whether this reader may approve it "
        "under the approval mode. The approval card on Compliance work."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "A bank-account permission is required"},
    },
)
async def list_pending_bank_accounts(
    current_user: Annotated[User, Depends(_PROPOSE_OR_APPROVE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> PendingBankAccountListResponse:
    accounts = await CompanyBankAccountService(db).pending()
    companies = {
        row.customer_id: row.name
        for row in await db.execute(
            select(ExporterProfile.customer_id, ExporterProfile.name).where(
                ExporterProfile.customer_id.in_({a.customer_id for a in accounts})
            )
        )
    }
    actor = actor_from(current_user, permissions)
    out = []
    for account, response in zip(
        accounts, await _responses(db, accounts, actor), strict=True
    ):
        pending = PendingBankAccountResponse.model_validate(account)
        pending.proposed_by_name = response.proposed_by_name
        pending.approved_by_name = response.approved_by_name
        pending.verified_by_name = response.verified_by_name
        pending.can_approve = response.can_approve
        pending.company_name = companies.get(account.customer_id)
        out.append(pending)
    return PendingBankAccountListResponse(accounts=out)


@router.post(
    "/bank-accounts/{account_id}/approve",
    response_model=BankAccountResponse,
    summary="Approve a proposed bank account",
    description=(
        "PENDING_APPROVAL -> PENDING_VERIFICATION. Who may approve follows "
        "`CRM_BANK_CHANGE_APPROVAL_MODE`; a refusal says why "
        "(BANK_ACCOUNT_APPROVAL_REFUSED)."
    ),
    responses={**_ACCOUNT_ERRORS, 403: {"description": "Not allowed to approve this one"}},
)
async def approve_bank_account(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(_PROPOSE_OR_APPROVE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    account = await CompanyBankAccountService(db).approve(
        account_id, actor=actor_from(current_user, permissions)
    )
    return await _one(db, account)


@router.post(
    "/bank-accounts/{account_id}/reject",
    response_model=BankAccountResponse,
    summary="Reject a proposed bank account",
    responses={
        **_ACCOUNT_ERRORS,
        403: {"description": "`exporters:approve_bank_accounts` permission required"},
    },
)
async def reject_bank_account(
    account_id: uuid.UUID,
    body: ReasonRequest,
    current_user: Annotated[User, Depends(_APPROVE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    account = await CompanyBankAccountService(db).reject(
        account_id, reason=body.reason, actor=actor_from(current_user, permissions)
    )
    return await _one(db, account)


@router.post(
    "/bank-accounts/{account_id}/verify",
    response_model=BankAccountResponse,
    summary="Verify an approved bank account",
    description=(
        "PENDING_VERIFICATION -> VERIFIED, on a cancelled cheque or bank letter on the "
        "company's record (`evidence_document_id`) or a passed bank-account verification "
        "of the company (`verification_result_id`, method PENNY_DROP). A verified change "
        "retires the account it replaces and takes over its primary flag; the first "
        "verified account in a currency becomes primary."
    ),
    responses={
        **_ACCOUNT_ERRORS,
        403: {"description": "`exporters:approve_bank_accounts` permission required"},
        422: {"description": "Missing or unsuitable evidence"},
    },
)
async def verify_bank_account(
    account_id: uuid.UUID,
    body: VerifyBankAccountRequest,
    current_user: Annotated[User, Depends(_APPROVE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    account = await CompanyBankAccountService(db).verify(
        account_id,
        method=body.method.value,
        evidence_document_id=body.evidence_document_id,
        verification_result_id=body.verification_result_id,
        actor=actor_from(current_user, permissions),
    )
    return await _one(db, account)


@router.post(
    "/bank-accounts/{account_id}/primary",
    response_model=BankAccountResponse,
    summary="Make a verified account the primary one for its currency",
    responses={
        **_ACCOUNT_ERRORS,
        403: {"description": "`exporters:approve_bank_accounts` permission required"},
    },
)
async def set_primary_bank_account(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(_APPROVE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    account = await CompanyBankAccountService(db).set_primary(
        account_id, actor=actor_from(current_user, permissions)
    )
    return await _one(db, account)


@router.post(
    "/bank-accounts/{account_id}/deactivate",
    response_model=BankAccountResponse,
    summary="Stop paying into a verified account",
    responses={
        **_ACCOUNT_ERRORS,
        403: {"description": "`exporters:approve_bank_accounts` permission required"},
    },
)
async def deactivate_bank_account(
    account_id: uuid.UUID,
    body: ReasonRequest,
    current_user: Annotated[User, Depends(_APPROVE)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    account = await CompanyBankAccountService(db).deactivate(
        account_id, reason=body.reason, actor=actor_from(current_user, permissions)
    )
    return await _one(db, account)


@router.post(
    "/bank-accounts/{account_id}/reveal",
    response_model=RevealedBankAccountResponse,
    summary="Reveal a bank account's full number",
    description="Every reveal is written to the audit trail before the number is returned.",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "`exporters:view_bank_details` permission required"},
        404: {"description": "No such bank account"},
        503: {"description": "No field encryption key is configured"},
    },
)
async def reveal_bank_account(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(_REVEAL)],
    permissions: _PERMISSIONS,
    db: AsyncSession = Depends(get_db),
) -> RevealedBankAccountResponse:
    numbers = await CompanyBankAccountService(db).reveal(
        account_id, actor=actor_from(current_user, permissions)
    )
    return RevealedBankAccountResponse(
        id=account_id, account_number=numbers.account_number, iban=numbers.iban
    )
