"""Two compliance users, ``approve_as`` and the required checks — the maker-checker
test utilities.

Maker-checker makes every ``CLEAR``, ``FLAGGED`` and
``ON_HOLD`` a two-person act: one COMPLIANCE or ADMIN user proposes, a *different* one
approves. With maker-checker on (the default, and what the suite runs with), no single
call can take a company there, so tests use these:

* ``compliance_maker`` / ``compliance_checker`` — module-scoped fixtures, two distinct
  COMPLIANCE accounts with tokens (``second_compliance_user`` is the checker's alias,
  for a test that only needs "another compliance officer");
* ``approve_as(checker, company_id, maker=…)`` — takes a company to a background-check
  value with ``maker`` proposing and ``checker`` approving, **in one call**, through
  ``BackgroundCheckService.propose`` and ``.approve``;
* ``propose_and_approve(client, company_id, maker_token=…, checker_token=…)`` — the
  same through the HTTP routes;
* ``record_required_checks(company_id)`` — the required checks: a ``CLEAR`` needs KYB,
  AML and sanctions each **passed** in the current cycle, so a test that clears a
  company records them first (manual results, through ``VerificationService``);
* ``StaticComplianceFactsReader`` and ``party_facts(...)`` — a fake of the published
  ``ComplianceFactsReader`` for a **consumer's** tests: the handover guard is
  tested "with a fake reader: each rule blocks with its own message", and this is
  that fake, answering exactly the facts a test gives it.

For "now" in tests, use ``app.shared.clock.use_clock(FixedClock(...))``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.onboarding.domain.background_check_views import BackgroundCheckDecisionView
from app.modules.onboarding.domain.compliance_facts import (
    BackgroundCheckValue,
    CheckState,
    PartyComplianceFacts,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import auth_header, user_with_role
from app.platform.database import services as db_services

BASE = "/api/v1/onboarding"

#: Rule B's required types (``CLEAR_POLICY.required_passed_types``).
REQUIRED_CHECK_TYPES: tuple[str, ...] = ("KYB", "AML", "SANCTIONS")


@dataclass(frozen=True)
class ComplianceUser:
    """A signed-in compliance (or admin) account a test acts as."""

    user_id: str
    role: UserRole = UserRole.COMPLIANCE
    token: str | None = None


async def make_compliance_user(
    client: AsyncClient, *, role: UserRole = UserRole.COMPLIANCE, label: str = "compliance"
) -> ComplianceUser:
    """A fresh account at ``role``, logged in."""
    user_id, token = await user_with_role(client, role, email_prefix=label)
    return ComplianceUser(user_id=user_id, role=role, token=token)


@pytest.fixture(scope="module")
async def compliance_maker(client: AsyncClient) -> ComplianceUser:
    """The compliance officer who records (proposes) a decision."""
    return await make_compliance_user(client, label="compliance-maker")


@pytest.fixture(scope="module")
async def compliance_checker(client: AsyncClient) -> ComplianceUser:
    """A **second** compliance officer — the one who approves."""
    return await make_compliance_user(client, label="compliance-checker")


@pytest.fixture(scope="module")
async def second_compliance_user(compliance_checker: ComplianceUser) -> ComplianceUser:
    """Another COMPLIANCE account, distinct from ``compliance_maker``."""
    return compliance_checker


async def record_required_checks(
    company_id: uuid.UUID,
    *,
    status: str = "PASSED",
    types: tuple[str, ...] = REQUIRED_CHECK_TYPES,
    actor_id: str = "compliance-checks",
) -> list[Any]:
    """Record a manual ``status`` result of each of ``types`` on the company — the required
    KYB, AML and sanctions by default — through ``VerificationService``. Each lands in
    the company's current check cycle."""
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
        VerificationType,
    )
    from app.modules.onboarding.domain.verification_evidence import VerificationEvidence

    results = []
    for verification_type in types:
        async with db_services.AsyncSessionLocal() as db:
            results.append(
                await VerificationService(db).trigger_verification(
                    VerificationType(verification_type),
                    VerificationEntityType.EXPORTER,
                    company_id,
                    provider="manual",
                    payload={"status": status},
                    actor_id=actor_id,
                    evidence=VerificationEvidence(
                        note=f"Test: {verification_type} checked manually."
                    ),
                )
            )
    return results


async def propose_as(
    maker: ComplianceUser,
    company_id: uuid.UUID,
    *,
    to_value: BackgroundCheckState = BackgroundCheckState.CLEAR,
    risk: BackgroundCheckRisk | None = BackgroundCheckRisk.LOW,
    reason: str = "Test: prerequisites met; for a second officer to approve.",
):
    """Propose ``to_value`` as ``maker``. Returns the proposal view."""
    from app.modules.onboarding.application.background_check_service import (
        BackgroundCheckService,
    )

    async with db_services.AsyncSessionLocal() as db:
        return await BackgroundCheckService(db).propose(
            company_id,
            to_value=to_value,
            reason=reason,
            risk=risk if to_value is BackgroundCheckState.CLEAR else None,
            actor_id=maker.user_id,
            actor_role=maker.role,
        )


async def approve_as(
    checker: ComplianceUser,
    company_id: uuid.UUID,
    *,
    maker: ComplianceUser,
    to_value: BackgroundCheckState = BackgroundCheckState.CLEAR,
    risk: BackgroundCheckRisk | None = BackgroundCheckRisk.LOW,
    reason: str = "Test: prerequisites met; approved by a second officer.",
) -> BackgroundCheckDecisionView:
    """Take ``company_id`` to ``to_value`` — ``maker`` proposing, ``checker`` approving.

    ``risk`` is sent only for ``CLEAR`` (it is refused on every other move). Returns the
    decision the approval wrote (``decided_by`` the maker, ``approved_by`` the checker).

    Raises:
        AssertionError: ``maker`` and ``checker`` are the same user, or either is not
            COMPLIANCE or ADMIN — refused here so the test fails with a plain message
            rather than the service's 403.
    """
    if maker.user_id == checker.user_id:
        raise AssertionError("approve_as needs two different users: the maker cannot approve")
    for actor in (maker, checker):
        if actor.role not in (UserRole.COMPLIANCE, UserRole.ADMIN):
            raise AssertionError(f"{actor.role.value} cannot record or approve a decision")

    # Imported here, like `companies.make_prospect`: fixture modules are imported by
    # tests of every layer.
    from app.modules.onboarding.application.background_check_service import (
        BackgroundCheckService,
    )
    from app.modules.onboarding.domain.assignment import APPROVE_HIGH_RISK

    proposal = await propose_as(maker, company_id, to_value=to_value, risk=risk, reason=reason)
    async with db_services.AsyncSessionLocal() as db:
        # The checker is a senior approver, so a test about something else may clear
        # at any risk; the senior rule has its own tests.
        approved = await BackgroundCheckService(db).approve(
            company_id,
            proposal.id,
            actor_id=checker.user_id,
            actor_role=checker.role,
            actor_permissions=frozenset({APPROVE_HIGH_RISK}),
        )
    return approved.decision


async def propose_and_approve(
    client: AsyncClient,
    company_id: uuid.UUID | str,
    *,
    maker_token: str,
    checker_token: str,
    to_value: str = "CLEAR",
    reason: str = "Test: proposed by one officer, approved by another.",
    risk_rating: str | None = "LOW",
    from_value: str | None = None,
) -> dict:
    """``POST …/decisions`` as the maker (202, a proposal), then ``…/approve`` as the
    checker (200). Returns the approval's body: ``{"decision": …, "proposal": …}``."""
    body: dict[str, Any] = {"to_value": to_value, "reason": reason}
    if to_value == "CLEAR":
        body["risk_rating"] = risk_rating
    if from_value is not None:
        body["from_value"] = from_value
    proposed = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json=body,
        headers=auth_header(maker_token),
    )
    assert proposed.status_code == 202, proposed.text
    approved = await client.post(
        f"{BASE}/exporters/{company_id}/background-check/proposals/{proposed.json()['id']}/approve",
        headers=auth_header(checker_token),
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


# ── A fake ComplianceFactsReader, for consumers' tests ────────────────────────


def party_facts(
    background_check: BackgroundCheckValue = "CLEAR",
    *,
    clear_expires_at: datetime | None = None,
    is_clear_current: bool | None = None,
    sanctions: CheckState = "PASSED",
    aml: CheckState = "PASSED",
) -> PartyComplianceFacts:
    """``PartyComplianceFacts`` for a test. ``is_clear`` follows ``background_check``;
    ``is_clear_current`` defaults to ``is_clear`` (pass ``False`` for an expired Clear)."""
    is_clear = background_check == "CLEAR"
    return PartyComplianceFacts(
        background_check=background_check,
        is_clear=is_clear,
        clear_expires_at=clear_expires_at,
        is_clear_current=is_clear if is_clear_current is None else is_clear_current,
        sanctions=sanctions,
        aml=aml,
    )


@dataclass
class StaticComplianceFactsReader:
    """Implements ``ComplianceFactsReader`` from fixed answers, for a consumer's tests.

    An id it was not given raises what the real reader raises for an unknown party
    (``ExporterProfileNotFoundError`` / ``ComplianceInputsBuyerNotFoundError``), so a
    consumer's error handling is exercised too. ``calls`` records ``(method, id, now)``.
    """

    companies: dict[uuid.UUID, PartyComplianceFacts] = field(default_factory=dict)
    legacy_buyers: dict[uuid.UUID, PartyComplianceFacts] = field(default_factory=dict)
    calls: list[tuple[str, uuid.UUID, datetime]] = field(default_factory=list)

    async def for_company(self, company_id: uuid.UUID, now: datetime) -> PartyComplianceFacts:
        from app.modules.onboarding.exceptions import ExporterProfileNotFoundError

        self.calls.append(("for_company", company_id, now))
        if company_id not in self.companies:
            raise ExporterProfileNotFoundError(company_id)
        return self.companies[company_id]

    async def for_legacy_buyer(
        self, deal_buyer_id: uuid.UUID, now: datetime
    ) -> PartyComplianceFacts:
        from app.modules.onboarding.exceptions import ComplianceInputsBuyerNotFoundError

        self.calls.append(("for_legacy_buyer", deal_buyer_id, now))
        if deal_buyer_id not in self.legacy_buyers:
            raise ComplianceInputsBuyerNotFoundError(deal_buyer_id)
        return self.legacy_buyers[deal_buyer_id]


__all__ = [
    "StaticComplianceFactsReader",
    "party_facts",
    "REQUIRED_CHECK_TYPES",
    "ComplianceUser",
    "approve_as",
    "compliance_checker",
    "compliance_maker",
    "make_compliance_user",
    "propose_and_approve",
    "propose_as",
    "record_required_checks",
    "second_compliance_user",
]
