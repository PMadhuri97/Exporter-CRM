"""Who may own a company, review its check and approve it — the pure rules.

The permissions are checked as "ADMIN, or the permission": a lead is a custom role
holding a grant, never an enum value, and nothing here names one.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain.assignment import (
    APPROVE_HIGH_RISK,
    ASSIGN_REVIEWS,
    ASSIGN_RM,
    checker_conflict,
    holds,
    may_set_relationship_manager,
    needs_senior_checker,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.authentication.models import UserRole
from app.platform.authorization.catalog import (
    BUILTIN_ROLE_PERMISSIONS,
    MODULES_BY_KEY,
    is_valid_permission,
)

NONE: frozenset = frozenset()


def test_the_three_permissions_are_in_the_catalogue_and_enforced():
    for module, action in (ASSIGN_RM, ASSIGN_REVIEWS, APPROVE_HIGH_RISK):
        assert is_valid_permission(module, action)
        spec = MODULES_BY_KEY[module]
        assert next(a for a in spec.actions if a.key == action).is_enforced(spec)
    # The rest of the exporters module is still declared-only.
    exporters = MODULES_BY_KEY["exporters"]
    assert not next(a for a in exporters.actions if a.key == "edit").is_enforced(exporters)


def test_only_admin_is_seeded_with_them():
    for role, granted in BUILTIN_ROLE_PERMISSIONS.items():
        for permission in (ASSIGN_RM, ASSIGN_REVIEWS, APPROVE_HIGH_RISK):
            assert (permission in granted) is (role is UserRole.ADMIN)


def test_no_lead_role_exists():
    assert {r.name for r in UserRole} == {
        "ADMIN",
        "COMPLIANCE",
        "OPERATIONS",
        "DEVELOPER",
        "API_USER",
    }


@pytest.mark.parametrize("permission", [ASSIGN_RM, ASSIGN_REVIEWS, APPROVE_HIGH_RISK])
def test_admin_holds_every_permission_without_a_grant(permission):
    assert holds(UserRole.ADMIN, NONE, permission)
    assert not holds(UserRole.COMPLIANCE, NONE, permission)
    assert holds(UserRole.COMPLIANCE, frozenset({permission}), permission)


def test_an_rm_may_claim_an_unowned_company_for_themselves_only():
    def may(role, current, target, perms=NONE):
        return may_set_relationship_manager(
            actor_id="me", actor_role=role, actor_permissions=perms, current=current, target=target
        )

    assert may(UserRole.OPERATIONS, None, "me")
    assert not may(UserRole.OPERATIONS, None, "someone")
    assert not may(UserRole.OPERATIONS, "someone", "me")  # a change
    assert not may(UserRole.OPERATIONS, "me", None)  # a clear
    assert not may(UserRole.COMPLIANCE, None, "me")  # compliance is never an RM
    # A sales lead (OPERATIONS + exporters:assign_rm) and ADMIN may do anything.
    lead = frozenset({ASSIGN_RM})
    assert may(UserRole.OPERATIONS, "someone", "other", lead)
    assert may(UserRole.OPERATIONS, "someone", None, lead)
    assert may(UserRole.ADMIN, None, "someone")


def test_only_a_high_or_critical_clear_needs_a_senior_checker():
    clear, flagged = BackgroundCheckState.CLEAR, BackgroundCheckState.FLAGGED
    assert needs_senior_checker(clear, BackgroundCheckRisk.HIGH)
    assert needs_senior_checker(clear, BackgroundCheckRisk.CRITICAL)
    assert not needs_senior_checker(clear, BackgroundCheckRisk.MEDIUM)
    assert not needs_senior_checker(clear, BackgroundCheckRisk.LOW)
    assert not needs_senior_checker(flagged, None)
    assert not needs_senior_checker(BackgroundCheckState.ON_HOLD, None)


def test_the_reviewer_and_the_rm_are_not_independent_checkers():
    assert checker_conflict(checker_id="r", reviewer_id="r", relationship_manager_id=None)
    assert checker_conflict(checker_id="m", reviewer_id="r", relationship_manager_id="m")
    assert checker_conflict(checker_id="x", reviewer_id="r", relationship_manager_id="m") is None
    assert checker_conflict(checker_id="x", reviewer_id=None, relationship_manager_id=None) is None
