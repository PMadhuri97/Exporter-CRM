"""Two compliance users and ``approve_as`` — the maker-checker test utilities (plan
P0-5, allocation F1). **Owner: Developer 1.**

Decision A (maker-checker, plan P3-1) makes every ``CLEAR``, ``FLAGGED`` and
``ON_HOLD`` a two-person act: one COMPLIANCE or ADMIN user proposes, a *different* one
approves. Tests that clear a company as one user would all break the day it lands, so
they are written against these now:

* ``compliance_maker`` / ``compliance_checker`` — module-scoped fixtures, two distinct
  COMPLIANCE accounts with tokens (``second_compliance_user`` is the checker's alias,
  for a test that only needs "another compliance officer");
* ``approve_as(checker, company_id, maker=…)`` — takes a company to a background-check
  value with ``maker`` proposing and ``checker`` approving, **in one call**.

**Today there is no approval step** (P3-1b is not built): ``approve_as`` records the
move as ``maker`` through ``BackgroundCheckService`` and only guarantees — by refusing
otherwise — that ``checker`` is a different user. When P3-1b lands, this body becomes
"propose as the maker, approve as the checker" and every caller keeps working
unchanged; that is the point of writing the helper before the feature.

For "now" in tests, use ``app.shared.clock.use_clock(FixedClock(...))``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient

from app.modules.onboarding.domain.background_check_views import BackgroundCheckDecisionView
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import user_with_role
from app.platform.database import services as db_services


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

    ``risk`` is sent only for ``CLEAR`` (it is refused on every other move). See the
    module docstring for what happens today, before the approval step exists.

    Raises:
        AssertionError: ``maker`` and ``checker`` are the same user — the one thing
            maker-checker forbids, refused here already so no test is written that
            would pass today and fail under P3-1b.
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

    async with db_services.AsyncSessionLocal() as db:
        # P3-1b: `propose(..., actor=maker)` then `approve(..., actor=checker)`.
        return await BackgroundCheckService(db).record_decision(
            company_id,
            to_value=to_value,
            reason=reason,
            risk=risk if to_value is BackgroundCheckState.CLEAR else None,
            actor_id=maker.user_id,
            actor_role=maker.role,
        )


__all__ = [
    "ComplianceUser",
    "approve_as",
    "compliance_checker",
    "compliance_maker",
    "make_compliance_user",
    "second_compliance_user",
]
