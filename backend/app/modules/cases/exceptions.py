"""Exceptions for the cases module."""
from __future__ import annotations

from app.shared.exceptions import AnerBaseException


class SlaConfigurationError(AnerBaseException):
    """The SLA configuration file is missing, malformed, or incomplete."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail=detail,
            error_code="SLA_CONFIGURATION_ERROR",
            status_code=500,
        )


class SlaTargetNotFoundError(AnerBaseException):
    """No SLA target is configured for a (case_type, severity) pair.

    Raised by `SlaCalculationService` rather than silently defaulting: an
    unconfigured pair is a GitOps gap the deploy should have caught (S1T2's
    acceptance criteria requires the config to cover every combination), not a
    condition a case-creation call site should have to guess a fallback for.
    """

    def __init__(self, case_type: str, severity: str) -> None:
        self.case_type = case_type
        self.severity = severity
        super().__init__(
            detail=(
                f"No SLA target is configured for case_type='{case_type}', "
                f"severity='{severity}'"
            ),
            error_code="SLA_TARGET_NOT_FOUND",
            status_code=500,
        )


class CaseNotFoundError(AnerBaseException):
    """No `compliance_case` row exists for the given id."""

    def __init__(self, case_id: object) -> None:
        self.case_id = case_id
        super().__init__(
            detail=f"No compliance_case exists with id={case_id!r}",
            error_code="CASE_NOT_FOUND",
            status_code=404,
        )


class InvalidCaseTransitionError(AnerBaseException):
    """The case is not in a state that allows the attempted transition.

    Raised by `application/case_transition_service.py`'s
    `transition_case_to_review` when the case it is asked to move to
    `ONBOARDING_REVIEW` is not currently `ONBOARDING_INTAKE` — the transition
    is defined to happen exactly once per case, not to be idempotent or to
    silently no-op on a case that already moved past intake.
    """

    def __init__(self, case_id: object, from_case_type: object, to_case_type: object) -> None:
        self.case_id = case_id
        self.from_case_type = from_case_type
        self.to_case_type = to_case_type
        super().__init__(
            detail=(
                f"Case {case_id!r} cannot transition to {to_case_type!r}: its "
                f"case_type is {from_case_type!r}, not ONBOARDING_INTAKE"
            ),
            error_code="INVALID_CASE_TRANSITION",
            status_code=409,
        )


class InvalidCaseStatusTransitionError(AnerBaseException):
    """The case's current `case_status` does not permit the attempted
    `case_status` transition (ANER-4.3-S3T2).

    Sibling to `InvalidCaseTransitionError`, not a reuse of it: that class's
    message is hardcoded to the one `case_type` transition
    (`ONBOARDING_INTAKE` -> `ONBOARDING_REVIEW`) `case_transition_service.py`
    implements ("its case_type is X, not ONBOARDING_INTAKE"), and reusing it
    verbatim for an unrelated `case_status` transition would produce a
    nonsensical message for a column it was never about. Raised by
    `application/case_lifecycle_service.py`'s `CaseLifecycleService._transition`
    for any `(from_status, to_status)` pair not in `PERMITTED_TRANSITIONS` —
    that set is the "Permitted transitions" table from the Epic 4.3 Jira doc's
    ANER-4.3-S3T2 section, reproduced verbatim (see that module's docstring),
    including the doc's own words: "Transitions not in this table are
    rejected with a structured error identifying the invalid transition."
    A case already in a terminal status (`RESOLVED`, `CLOSED_WITHOUT_ACTION`)
    has no outbound edges in the table at all, so any attempted transition out
    of one surfaces through this same path with no special-casing needed.
    """

    def __init__(self, case_id: object, from_status: object, to_status: object) -> None:
        self.case_id = case_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            detail=(
                f"Case {case_id!r} cannot transition from {from_status!r} to "
                f"{to_status!r}: not a permitted case_status transition"
            ),
            error_code="INVALID_CASE_STATUS_TRANSITION",
            status_code=409,
        )


class CaseIsTerminalError(AnerBaseException):
    """The case has reached a terminal `case_status` (`RESOLVED` or
    `CLOSED_WITHOUT_ACTION`) and this operation is not permitted after that.

    Distinct from `InvalidCaseStatusTransitionError`: that one is raised when
    a *transition* (a change of `case_status`) is attempted and rejected.
    This one is raised by `CaseNoteService.add_case_note` (ANER-4.3-S3T3),
    which never attempts a transition at all (`case_status` is untouched) but
    is still barred by the Jira doc's own text: "Officers can add notes to a
    case at any point in its lifecycle (except terminal states)."
    """

    def __init__(self, case_id: object, case_status: object) -> None:
        self.case_id = case_id
        self.case_status = case_status
        super().__init__(
            detail=(
                f"Case {case_id!r} is in a terminal status ({case_status!r}) "
                f"and cannot be modified further"
            ),
            error_code="CASE_IS_TERMINAL",
            status_code=409,
        )


class UserNotFoundOrInactiveError(AnerBaseException):
    """`user_id` does not correspond to a real, active `auth.users` row.

    Raised wherever this module is handed an id it must trust corresponds to
    a real person before acting on it — an assignee (S3T1), the actor on a
    note or timeline event (S3T1/S3T3), or the maker/checker on a resolution
    proposal/decision (S4T2) — even though the columns that store these ids
    (`compliance_case.assigned_to`, `case_timeline_event.actor_id`) are plain
    strings with no foreign key to `auth.users`. See
    `application/actor_validation.py`'s `require_active_user`: it mirrors
    `app.platform.authentication.dependencies.get_current_user`'s own
    not-found/inactive checks rather than inventing a second way to decide
    who counts as a valid user — `app.platform.*` is the one import this
    module is allowed outside its own tree (ARCHITECTURE.md §6).
    """

    def __init__(self, user_id: object, role: str) -> None:
        self.user_id = user_id
        self.role = role
        super().__init__(
            detail=f"No active user exists for {role} id={user_id!r}",
            error_code="USER_NOT_FOUND_OR_INACTIVE",
            status_code=422,
        )


class SelfApprovalNotAllowedError(AnerBaseException):
    """A user attempted `CaseLifecycleService.decide_resolution` on a
    proposal they themselves made via `propose_resolution` (ANER-4.3-S4T2).

    The one segregation-of-duties rule this module's maker-checker stand-in
    enforces — see `application/case_lifecycle_service.py`'s module docstring
    for why this is explicitly *not* Epic 5.4's Maker-Checker and SoD Engine.
    Deliberately minimal: no role hierarchy, no configurable dual-control
    policy, just "not the same person" — enforced for both `approve` and
    `reject` decisions, not only `approve`.
    """

    def __init__(self, case_id: object, user_id: object) -> None:
        self.case_id = case_id
        self.user_id = user_id
        super().__init__(
            detail=(
                f"User {user_id!r} proposed the pending resolution on case "
                f"{case_id!r} and cannot also decide it"
            ),
            error_code="SELF_APPROVAL_NOT_ALLOWED",
            status_code=409,
        )
