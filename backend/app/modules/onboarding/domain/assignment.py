"""Who may own a company, who may review its background check, and who may approve it.

Pure rules over a role, a permission set and ids, so they are unit-tested without a
database and read in one place. The services call them under the company row lock;
the routes call them to serve ``allowed_actions``.

**The three permissions are checked as permissions, nothing else.** They are held
through a role — the seeded *Compliance lead* and *Sales lead*, or any role an
administrator grants them to — on top of an OPERATIONS or COMPLIANCE enum value. The
administrator holds none of them: it runs the system and does not assign, review or
approve business work.

**Ownership grants nothing.** Being a company's relationship manager neither widens
what a user may see nor unmasks an identifier (``can_reveal_identifiers``); it only
narrows who may review and approve that company's check.
"""

from __future__ import annotations

from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.authentication.models import UserRole

Permission = tuple[str, str]

#: Assign someone else as RM, change or clear an RM, reassign in bulk.
ASSIGN_RM: Permission = ("exporters", "assign_rm")
#: Assign and reassign reviewers; withdraw an absent proposer's proposal; the
#: In review (everyone), Overdue and Needs attention views.
ASSIGN_REVIEWS: Permission = ("compliance", "assign")
#: Approve a CLEAR proposed with HIGH or CRITICAL risk.
APPROVE_HIGH_RISK: Permission = ("compliance", "approve_high_risk")

#: Who may be a company's relationship manager. COMPLIANCE never is, which keeps "the reviewer is not the RM" meaningful.
RM_ROLES: frozenset[UserRole] = frozenset({UserRole.OPERATIONS})
#: Who may review a background check (and so be assigned one).
REVIEWER_ROLES: frozenset[UserRole] = frozenset({UserRole.COMPLIANCE})
#: Who may approve or reject a proposal (maker-checker). Never the administrator.
CHECKER_ROLES: frozenset[UserRole] = frozenset({UserRole.COMPLIANCE})

#: The risks a senior checker must approve a CLEAR at.
HIGH_RISKS: frozenset[BackgroundCheckRisk] = frozenset(
    {BackgroundCheckRisk.HIGH, BackgroundCheckRisk.CRITICAL}
)

#: The gauge values a review exists in.
UNDER_REVIEW: frozenset[BackgroundCheckState] = frozenset(
    {BackgroundCheckState.IN_REVIEW, BackgroundCheckState.MORE_INFO}
)

#: `event_type`s of the `relationship_manager` history dimension.
RM_ASSIGNED = "relationship_manager_assigned"
RM_REASSIGNED = "relationship_manager_reassigned"
RM_CLEARED = "relationship_manager_cleared"

#: `event_type`s of the `background_check_assignment` history dimension.
REVIEW_CLAIMED = "review_claimed"
REVIEW_ASSIGNED = "review_assigned"
REVIEW_REASSIGNED = "review_reassigned"
REVIEW_RELEASED = "review_released"
REVIEW_ENDED = "review_ended"

#: The history row's `to_value` when nobody holds the thing any more.
UNASSIGNED = "UNASSIGNED"


def holds(permissions: frozenset[Permission], permission: Permission) -> bool:
    """Whether ``permissions`` include ``permission``. Named for the rules that read it
    ("a holder of ``compliance:assign``"); there is no role that holds everything."""
    return permission in permissions


def needs_senior_checker(
    to_value: BackgroundCheckState, risk: BackgroundCheckRisk | None
) -> bool:
    """A CLEAR at HIGH or CRITICAL risk. FLAGGED and ON_HOLD never do."""
    return to_value is BackgroundCheckState.CLEAR and risk in HIGH_RISKS


def checker_conflict(
    *,
    checker_id: str,
    reviewer_id: str | None,
    relationship_manager_id: str | None,
) -> str | None:
    """Why ``checker_id`` is not independent of this review, or ``None``.

    The proposer is refused separately (``BACKGROUND_CHECK_SELF_APPROVAL``, also a
    database rule); this adds the review's current reviewer and the company's RM.
    """
    if reviewer_id is not None and checker_id == reviewer_id:
        return "you are this review's reviewer"
    if relationship_manager_id is not None and checker_id == relationship_manager_id:
        return "you are this company's relationship manager"
    return None


def may_set_relationship_manager(
    *,
    actor_id: str,
    actor_role: UserRole,
    actor_permissions: frozenset[Permission],
    current: str | None,
    target: str | None,
) -> bool:
    """Whether the actor may move the company's RM from ``current`` to ``target``.

    An OPERATIONS user may claim a company with **no** RM for themselves. Anything
    else — someone else as RM, a change, a clear — needs ``exporters:assign_rm``.
    """
    if holds(actor_permissions, ASSIGN_RM):
        return True
    return (
        current is None
        and target is not None
        and target == actor_id
        and actor_role in RM_ROLES
    )


__all__ = [
    "APPROVE_HIGH_RISK",
    "ASSIGN_REVIEWS",
    "ASSIGN_RM",
    "CHECKER_ROLES",
    "HIGH_RISKS",
    "REVIEWER_ROLES",
    "REVIEW_ASSIGNED",
    "REVIEW_CLAIMED",
    "REVIEW_ENDED",
    "REVIEW_REASSIGNED",
    "REVIEW_RELEASED",
    "RM_ASSIGNED",
    "RM_CLEARED",
    "RM_REASSIGNED",
    "RM_ROLES",
    "UNASSIGNED",
    "UNDER_REVIEW",
    "Permission",
    "checker_conflict",
    "holds",
    "may_set_relationship_manager",
    "needs_senior_checker",
]
