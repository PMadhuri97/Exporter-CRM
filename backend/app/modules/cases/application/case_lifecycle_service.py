"""Case assignment, status lifecycle, and onboarding-review resolution
(ANER-4.3-S3T1, S3T2, S4T2).

**Transition source.** The Epic 4.3 Jira doc (`4.3 Case Management
Console.docx`) turns out to contain an explicit "Permitted transitions" table
in its ANER-4.3-S3T2 section, immediately preceded by: "Implement the case
status lifecycle transition service that manages the permitted status
transitions for compliance_case records... Every transition writes a
case_timeline_event. Transitions not in this table are rejected with a
structured error identifying the invalid transition." That table, not an
inferred graph, is what `PERMITTED_TRANSITIONS` below reproduces.

The doc's table has 15 rows; `PERMITTED_TRANSITIONS` implements 10 of them —
every row relevant to the stories actually in scope here (S3T1, S3T2, S3T3,
S4T2). The 5 rows deliberately left out:

- `under_investigation -> resolved` and `escalated -> resolved` ("Who":
  assigned/senior officer, direct — no maker-checker): these are case-type
  -specific *direct* resolution paths owned by S4T1/S4T3/S4T4
  (transaction_flag, reconciliation, travel_rule/on_chain), none of which are
  built here. They do not apply to `onboarding_review`, this task's only
  in-scope resolution workflow — the doc's own S4T2 section states
  "approve_onboarding always requires Epic 5.4 maker-checker approval", so
  the only resolved-reaching edge an onboarding case ever needs is
  `pending_approval -> resolved`, which *is* implemented.
- `open -> escalated` and `assigned -> escalated` ("Who": System,
  trigger: "SLA auto-escalation"): these belong to S5T2's not-yet-built SLA
  auto-escalation job, not to `escalate_case` below, which the task brief
  describes as a *manual* escalation action. Only the doc's third escalation
  row — `under_investigation -> escalated`, "Who": assigned officer — is a
  manual trigger, and is the one implemented.

Any transition outside the 10 implemented edges — including the 5 above —
is rejected by `_transition` with `InvalidCaseStatusTransitionError`, exactly
matching the doc's "transitions not in this table are rejected" rule; the 5
omitted edges are absent from `PERMITTED_TRANSITIONS` rather than present but
unused, so there is no path by which this build could be made to perform a
transition it does not actually support.

**Extra methods beyond what Pieces 1/2/4's task text names.** The task text
names dedicated public methods only for the transitions Pieces 1 and 4
directly need (`assign_case`, `escalate_case`, `close_case_without_action`,
`propose_resolution`, `decide_resolution`). Three edges in the doc's own
table have no dedicated method named anywhere in the brief:
`assigned -> under_investigation`, `under_investigation <-> pending_external`,
and `escalated -> under_investigation`. Without *some* way to reach
`under_investigation`, `propose_resolution`'s own precondition (the case must
already be `under_investigation`) could never be satisfied by any code path
this module exposes — a case assigned via `assign_case` would be permanently
stuck. So this build adds two small generic methods to cover those three
edges: `begin_investigation` (covers all three "arrive at
under_investigation" edges — from `assigned`, `pending_external`, or
`escalated` — since all three are "this case is now under active work" from
the officer's perspective, and it is `PERMITTED_TRANSITIONS`, not the method,
that actually restricts which prior status is legal) and
`mark_pending_external` (the one edge leading *out* of
`under_investigation` to `pending_external`). Both go through the same
`_transition` helper as every other method here.

**Reassignment scope.** The task brief names `assigned` and
`under_investigation` explicitly as statuses a case can be re-assigned from
without forcing a status change. This build extends that, by inference, to
every non-terminal status (`pending_external`, `pending_approval`,
`escalated` too): who is assigned is orthogonal to which lifecycle stage a
case is in, and there is no stated reason a case pending external response or
under escalation cannot have its assignee corrected. Terminal statuses
(`resolved`, `closed_without_action`) remain rejected — a closed case has
nothing left to assign.

**`close_case_without_action` scope — a deliberate override of the task's
own fallback instruction.** The task brief's fallback graph (used only
"absent an explicit spec table") says closed_without_action is reachable
from "any non-terminal status". The doc's own table, found and used verbatim
per the task's own instruction to prefer it, lists exactly one row into
`closed_without_action`: `under_investigation -> closed_without_action`. This
build follows the doc, not the task's fallback text, and restricts
`close_case_without_action` to `under_investigation` only — a case that was
never even assigned cannot be "reviewed and determined to require no
action" (the doc's own definition of the state), since nobody has reviewed
it yet.

**The 50-character minimum on resolution/closure notes.** Not in the task
brief's own text, but stated plainly in the doc's S3T2 section: "The
resolution_note must be at least 50 characters — a one-word note does not
constitute an adequate compliance record. Implemented as a validation before
the transition is permitted." and "The closed_without_action terminal
state: requires a note explaining why no action was taken. Same minimum
length requirement." `MIN_SUBSTANTIVE_NOTE_LENGTH` enforces this at the
application layer, ahead of the DB's own `MIN_RESOLUTION_NOTE_LENGTH = 1`
check-constraint floor (see `domain/entities/compliance_case.py`) — the two
are deliberately different numbers: the DB guards against a null/empty
resolution being written by any path (including one that bypasses this
service), while this constant is the substantive-content bar the doc asks
this task's own validation layer to hold to.

**This is not Epic 5.4.** `propose_resolution` / `decide_resolution` /
`list_pending_approvals` are an explicit, lightweight placeholder for Epic
5.4's Maker-Checker and SoD Engine — built here only because an
`onboarding_review` case cannot be resolved without *some* two-person check,
and Epic 5.4 does not exist yet. No role hierarchy, no configurable
dual-control policy, no queue routing, no real notification delivery (Epic
4.6, also not built) — `list_pending_approvals` is a pull-based query
standing in for a push notification. The one rule enforced is the
irreducible one: the checker cannot be the maker
(`SelfApprovalNotAllowedError`). Whoever builds Epic 5.4 should replace this
wholesale, not extend it — the `compliance.ComplianceCase` /
`cases.ComplianceCase` naming collision this module's README documents is
the closest precedent for flagging a deliberate, temporary duplication this
loudly rather than letting it be mistaken for the real thing.

**Why resolution_action/resolution_note are not written until approval.**
Both columns are immutable once set (a DB trigger from S1T1 enforces this —
see `domain/entities/compliance_case.py`'s docstring). A rejected proposal
must be able to go through another proposal round without permanently
occupying those columns, so `propose_resolution` stores the proposed values
only in the `APPROVAL_REQUESTED` timeline event's `payload` JSON; `
decide_resolution`'s `approve` branch is the only place that ever writes them
onto the `compliance_case` row, read back from that same event.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.application.actor_validation import require_active_user
from app.modules.cases.config import REQUIRE_TWO_PERSON_RESOLUTION
from app.modules.cases.domain.entities.case_timeline_event import CaseTimelineEvent
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import (
    TERMINAL_CASE_STATUSES,
    ActorType,
    CaseStatus,
    ResolutionAction,
    TimelineEventType,
)
from app.modules.cases.exceptions import (
    CaseNotFoundError,
    InvalidCaseStatusTransitionError,
    SelfApprovalNotAllowedError,
)
from app.shared.exceptions import ValidationError

#: The Jira doc's "Permitted transitions" table (ANER-4.3-S3T2), narrowed to
#: the 10 rows this build's stories (S3T1/S3T2/S3T3/S4T2) actually implement
#: — see the module docstring for exactly which 5 rows were left out and why.
PERMITTED_TRANSITIONS: frozenset[tuple[CaseStatus, CaseStatus]] = frozenset(
    {
        (CaseStatus.OPEN, CaseStatus.ASSIGNED),
        (CaseStatus.ASSIGNED, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.PENDING_EXTERNAL),
        (CaseStatus.PENDING_EXTERNAL, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.PENDING_APPROVAL),
        (CaseStatus.PENDING_APPROVAL, CaseStatus.RESOLVED),
        (CaseStatus.PENDING_APPROVAL, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.CLOSED_WITHOUT_ACTION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.ESCALATED),
        (CaseStatus.ESCALATED, CaseStatus.UNDER_INVESTIGATION),
    }
)

#: Jira doc, S3T2: "The resolution_note must be at least 50 characters...
#: The closed_without_action terminal state... Same minimum length
#: requirement." Applied to `propose_resolution`'s `resolution_note` and
#: `close_case_without_action`'s `reason`. Distinct from, and stricter than,
#: `compliance_case.py`'s `MIN_RESOLUTION_NOTE_LENGTH = 1` DB floor — see the
#: module docstring.
MIN_SUBSTANTIVE_NOTE_LENGTH = 50


class CaseLifecycleService:
    """Drives a `compliance_case` through its `case_status` lifecycle:
    assignment (S3T1), the general transition graph (S3T2), and the
    onboarding-review maker-checker resolution stand-in (S4T2).

    Every status-changing method funnels through `_transition`, the single
    place `PERMITTED_TRANSITIONS` is checked — see the module docstring for
    where that table comes from and why it is narrower than the doc's full
    15-row version.
    """

    __slots__ = ("_require_two_person",)

    def __init__(self, *, require_two_person: bool | None = None) -> None:
        """`require_two_person` defaults to `config.REQUIRE_TWO_PERSON_RESOLUTION`
        (off). Pass it explicitly only to pin the rule regardless of config."""
        self._require_two_person = (
            REQUIRE_TWO_PERSON_RESOLUTION if require_two_person is None else require_two_person
        )

    # ── S3T1: assignment ────────────────────────────────────────────────────

    async def assign_case(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        assigned_to: str,
        actor_id: str,
        actor_type: ActorType,
        note: str | None = None,
    ) -> ComplianceCase:
        """Assign (or re-assign) `case_id` to `assigned_to`.

        No team/queue routing: the doc's S3T1 section describes routing a
        newly created case to a team queue via a GitOps routing config, keyed
        by case_type/severity, before an *optional* officer assignment on
        top. That does not apply here — there is a single reviewer, not
        multiple teams to route between — so this method is a direct "assign
        to this specific user" operation only, with no team-membership check
        (the doc's own validation, "the assignee belongs to the team
        designated for this case type", is what that routing layer would
        enforce and is skipped along with it).

        If the case is currently `OPEN`, this also transitions it to
        `ASSIGNED` (the doc's `open -> assigned` row). If it is already past
        `OPEN` (any non-terminal status), only `assigned_to`/`assigned_at`
        change — see the module docstring for why this is extended to every
        non-terminal status, not only `ASSIGNED`/`UNDER_INVESTIGATION`.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: the case is in a terminal
                status (`RESOLVED`, `CLOSED_WITHOUT_ACTION`).
            UserNotFoundOrInactiveError: `assigned_to` is not a real, active
                platform user.
        """
        case = await session.get(ComplianceCase, case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.case_status in TERMINAL_CASE_STATUSES:
            raise InvalidCaseStatusTransitionError(case_id, case.case_status, CaseStatus.ASSIGNED)

        await require_active_user(session, assigned_to, role="assignee")

        case.assigned_to = assigned_to
        case.assigned_at = _now()

        to_status = CaseStatus.ASSIGNED if case.case_status == CaseStatus.OPEN else case.case_status
        return await self._transition(
            session,
            case_id,
            to_status,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=TimelineEventType.ASSIGNED,
            payload={"assigned_to": assigned_to},
            note=note,
            allow_same_status=True,
        )

    # ── S3T2: general lifecycle transitions not covered by a named method ──

    async def begin_investigation(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        actor_id: str,
        actor_type: ActorType,
        note: str | None = None,
    ) -> ComplianceCase:
        """Move `case_id` to `UNDER_INVESTIGATION`.

        Covers three of the doc's table rows into `under_investigation` —
        from `ASSIGNED` (officer begins active work), from
        `PENDING_EXTERNAL` (the external wait is resolved), or from
        `ESCALATED` (the escalation is resolved and work resumes normally).
        All three read as "this case is now under active work" from the
        officer's perspective, so one method serves all three; it is
        `PERMITTED_TRANSITIONS`, not this method, that actually restricts
        which prior status is legal — see the module docstring.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: the case's current status is
                not `ASSIGNED`, `PENDING_EXTERNAL`, or `ESCALATED`.
        """
        return await self._transition(
            session,
            case_id,
            CaseStatus.UNDER_INVESTIGATION,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=TimelineEventType.STATUS_CHANGED,
            note=note,
        )

    async def mark_pending_external(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        actor_id: str,
        actor_type: ActorType,
        reason: str,
    ) -> ComplianceCase:
        """Move an `UNDER_INVESTIGATION` case to `PENDING_EXTERNAL` — the
        assigned officer is waiting on a response from the customer, a rail
        partner, a screening vendor, or another VASP.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: the case is not currently
                `UNDER_INVESTIGATION`.
            ValidationError: `reason` is empty or whitespace-only.
        """
        if not reason or not reason.strip():
            raise ValidationError("reason is required to mark a case pending_external")
        return await self._transition(
            session,
            case_id,
            CaseStatus.PENDING_EXTERNAL,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=TimelineEventType.STATUS_CHANGED,
            note=reason,
            payload={"reason": reason},
        )

    async def escalate_case(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        actor_id: str,
        actor_type: ActorType,
        reason: str,
    ) -> ComplianceCase:
        """Manually escalate an `UNDER_INVESTIGATION` case to `ESCALATED`.

        Manual only: the doc's table also lists `open -> escalated` and
        `assigned -> escalated`, both triggered by "SLA auto-escalation" /
        "System" — that belongs to S5T2's auto-escalation job, not built
        here, and is deliberately absent from `PERMITTED_TRANSITIONS` (see
        the module docstring), so this method can only ever succeed from
        `UNDER_INVESTIGATION`.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: the case is not currently
                `UNDER_INVESTIGATION`.
            ValidationError: `reason` is empty or whitespace-only.
        """
        if not reason or not reason.strip():
            raise ValidationError("reason is required to escalate a case")
        return await self._transition(
            session,
            case_id,
            CaseStatus.ESCALATED,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=TimelineEventType.ESCALATED,
            note=reason,
            payload={"reason": reason},
        )

    async def close_case_without_action(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        actor_id: str,
        actor_type: ActorType,
        reason: str,
    ) -> ComplianceCase:
        """Close an `UNDER_INVESTIGATION` case with no resolution action
        taken. Does not set `resolution_action`/`resolution_note` — both stay
        null, so `ck_compliance_case_resolution_note_required` (which only
        fires when `resolution_action IS NOT NULL`) is never implicated.

        Restricted to `UNDER_INVESTIGATION` only, per the doc's table — see
        the module docstring for why this overrides the task brief's own
        fallback ("any non-terminal status").

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: the case is not currently
                `UNDER_INVESTIGATION`.
            ValidationError: `reason` is shorter than
                `MIN_SUBSTANTIVE_NOTE_LENGTH` characters.
        """
        if not reason or len(reason.strip()) < MIN_SUBSTANTIVE_NOTE_LENGTH:
            raise ValidationError(
                f"reason must be at least {MIN_SUBSTANTIVE_NOTE_LENGTH} characters "
                f"to close a case without action"
            )
        return await self._transition(
            session,
            case_id,
            CaseStatus.CLOSED_WITHOUT_ACTION,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=TimelineEventType.CLOSED,
            note=reason,
            payload={"reason": reason},
        )

    # ── S4T2: onboarding-review maker-checker stand-in ──────────────────────
    # NOT Epic 5.4's Maker-Checker and SoD Engine — see the module docstring.

    async def propose_resolution(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        resolution_action: ResolutionAction,
        resolution_note: str,
        proposed_by: str,
        actor_type: ActorType,
    ) -> ComplianceCase:
        """Record a proposed resolution for an `UNDER_INVESTIGATION` case and
        move it to `PENDING_APPROVAL`.

        Does **not** write `resolution_action`/`resolution_note` onto the
        `compliance_case` row — see the module docstring for why. The
        proposal lives entirely in this call's `APPROVAL_REQUESTED`
        `case_timeline_event.payload`, read back by `decide_resolution`.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: the case is not currently
                `UNDER_INVESTIGATION` — "someone has actually looked at it"
                is the bar, so a case still `ASSIGNED` (nobody has started
                work) is rejected too, not only a case already resolved.
            ValidationError: `resolution_note` is shorter than
                `MIN_SUBSTANTIVE_NOTE_LENGTH` characters.
            UserNotFoundOrInactiveError: `proposed_by` is not a real, active
                platform user.
        """
        if not resolution_note or len(resolution_note.strip()) < MIN_SUBSTANTIVE_NOTE_LENGTH:
            raise ValidationError(
                f"resolution_note must be at least {MIN_SUBSTANTIVE_NOTE_LENGTH} characters"
            )
        await require_active_user(session, proposed_by, role="proposer (proposed_by)")

        return await self._transition(
            session,
            case_id,
            CaseStatus.PENDING_APPROVAL,
            actor_id=proposed_by,
            actor_type=actor_type,
            event_type=TimelineEventType.APPROVAL_REQUESTED,
            note=resolution_note,
            payload={
                "proposed_resolution_action": resolution_action.value,
                "proposed_resolution_note": resolution_note,
                "proposed_by": proposed_by,
            },
        )

    async def decide_resolution(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        decision: str,
        checker_id: str,
        actor_type: ActorType,
        checker_note: str | None = None,
    ) -> ComplianceCase:
        """Approve or reject the pending proposal on a `PENDING_APPROVAL` case.

        `decision` is the literal string `"approve"` or `"reject"`.

        On `"approve"`: reads the proposed `resolution_action`/
        `resolution_note` back from the case's most recent
        `APPROVAL_REQUESTED` event, writes them onto `compliance_case` for
        the first time along with `resolved_by=checker_id` /
        `resolved_at=now`, and transitions to `RESOLVED`. Two timeline events
        are written in the same commit — `APPROVAL_RECEIVED` then
        `RESOLVED` — rather than one combined event: they are distinct
        compliance facts ("the checker approved" vs. "the case is now
        closed"), and `case_timeline_event` is the audit trail a regulator
        reads, so collapsing them would hide which fact caused which.

        On `"reject"`: does not touch the resolution columns (never set),
        transitions back to `UNDER_INVESTIGATION`, and logs a single
        `APPROVAL_REJECTED` event with `checker_note` and a reference to the
        rejected proposal.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            ValidationError: `decision` is neither `"approve"` nor
                `"reject"`, or (defensively) the case is `PENDING_APPROVAL`
                with no `APPROVAL_REQUESTED` event to decide against — should
                be unreachable, since `propose_resolution` is the only way a
                case enters `PENDING_APPROVAL` and always writes one first.
            InvalidCaseStatusTransitionError: the case is not currently
                `PENDING_APPROVAL`.
            UserNotFoundOrInactiveError: `checker_id` is not a real, active
                platform user.
            SelfApprovalNotAllowedError: the two-person rule is on
                (`config.REQUIRE_TWO_PERSON_RESOLUTION`) and `checker_id` is
                the same user recorded as `proposed_by` on the pending
                proposal — checked for both `"approve"` and `"reject"`.
        """
        if decision not in ("approve", "reject"):
            raise ValidationError(f"decision must be 'approve' or 'reject', got {decision!r}")

        case = await session.get(ComplianceCase, case_id)
        if case is None:
            raise CaseNotFoundError(case_id)

        attempted_to = CaseStatus.RESOLVED if decision == "approve" else CaseStatus.UNDER_INVESTIGATION
        if case.case_status != CaseStatus.PENDING_APPROVAL:
            raise InvalidCaseStatusTransitionError(case_id, case.case_status, attempted_to)

        await require_active_user(session, checker_id, role="checker (checker_id)")

        proposal_event = await self._latest_approval_requested_event(session, case_id)
        if proposal_event is None:
            raise ValidationError(
                f"Case {case_id!r} is pending_approval but has no APPROVAL_REQUESTED "
                f"timeline event to decide against"
            )
        proposed_by = proposal_event.payload["proposed_by"]
        if self._require_two_person and checker_id == proposed_by:
            raise SelfApprovalNotAllowedError(case_id, checker_id)

        if decision == "approve":
            resolution_action = ResolutionAction(proposal_event.payload["proposed_resolution_action"])
            resolution_note = proposal_event.payload["proposed_resolution_note"]
            case.resolution_action = resolution_action
            case.resolution_note = resolution_note
            case.resolved_by = checker_id
            case.resolved_at = _now()

            return await self._transition(
                session,
                case_id,
                CaseStatus.RESOLVED,
                actor_id=checker_id,
                actor_type=actor_type,
                event_type=TimelineEventType.APPROVAL_RECEIVED,
                note=checker_note,
                payload={
                    "decision": "approve",
                    "approval_requested_event_id": str(proposal_event.id),
                    "proposed_by": proposed_by,
                },
                extra_events=[
                    CaseTimelineEvent(
                        case_id=case_id,
                        event_type=TimelineEventType.RESOLVED,
                        from_status=CaseStatus.RESOLVED.value,
                        to_status=CaseStatus.RESOLVED.value,
                        actor_id=checker_id,
                        actor_type=actor_type,
                        note=resolution_note,
                        payload={
                            "resolution_action": resolution_action.value,
                            "resolved_by": checker_id,
                        },
                    ),
                ],
            )

        return await self._transition(
            session,
            case_id,
            CaseStatus.UNDER_INVESTIGATION,
            actor_id=checker_id,
            actor_type=actor_type,
            event_type=TimelineEventType.APPROVAL_REJECTED,
            note=checker_note,
            payload={
                "decision": "reject",
                "approval_requested_event_id": str(proposal_event.id),
                "proposed_by": proposed_by,
            },
        )

    async def list_pending_approvals(
        self, session: AsyncSession, checker_id: str | None = None
    ) -> list[ComplianceCase]:
        """The pull-based stand-in for a push notification: every case
        currently `PENDING_APPROVAL`, oldest proposal first.

        **Ordering.** Sorted by the case's most recent `APPROVAL_REQUESTED`
        event's `occurred_at`, not `last_updated_at`. `last_updated_at` would
        be silently perturbed by an unrelated reassignment while a case sits
        in `PENDING_APPROVAL` (`assign_case` permits reassignment on any
        non-terminal status, `PENDING_APPROVAL` included), which would
        incorrectly reset a case's apparent wait time. `case_timeline_event`
        is append-only and never touched by anything but the event that
        created it, so anchoring the sort to it is the only way "oldest
        submitted proposal first" is guaranteed to actually hold.

        **`checker_id`.** There is no assignment-to-specific-checker concept
        yet (no Epic 5.4), so this is not a personal queue filter. Passing it
        excludes cases *this checker themselves proposed* — reinforcing the
        self-approval rule from the query side too, so a user is never even
        shown their own proposal as something to decide on. `None` (the
        default) returns every pending case unfiltered.
        """
        cases = (
            (
                await session.execute(
                    select(ComplianceCase).where(
                        ComplianceCase.case_status == CaseStatus.PENDING_APPROVAL
                    )
                )
            )
            .scalars()
            .all()
        )

        requested_at: dict[uuid.UUID, datetime] = {}
        proposed_by_of: dict[uuid.UUID, str | None] = {}
        for case in cases:
            event = await self._latest_approval_requested_event(session, case.id)
            requested_at[case.id] = event.occurred_at if event is not None else case.last_updated_at
            proposed_by_of[case.id] = event.payload.get("proposed_by") if event is not None else None

        if checker_id is not None:
            cases = [c for c in cases if proposed_by_of[c.id] != checker_id]

        return sorted(cases, key=lambda c: requested_at[c.id])

    # ── shared machinery ────────────────────────────────────────────────────

    async def _transition(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        to_status: CaseStatus,
        actor_id: str,
        actor_type: ActorType,
        event_type: TimelineEventType,
        payload: dict | None = None,
        note: str | None = None,
        allow_same_status: bool = False,
        extra_events: list[CaseTimelineEvent] | None = None,
    ) -> ComplianceCase:
        """The one place `PERMITTED_TRANSITIONS` is checked. Every public
        method above calls through this rather than mutating `case_status`
        itself.

        `allow_same_status` exists solely for `assign_case`'s re-assignment
        path, where `to_status == from_status` is a legitimate "no status
        change" call rather than a rejected transition — every other caller
        leaves it `False`, so a same-status call from anywhere else is
        (correctly) treated as invalid.

        `extra_events` lets a caller (`decide_resolution`'s approve branch)
        write more than one `case_timeline_event` in the same commit as the
        transition, without a second `_transition` call re-validating a
        transition that already happened.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseStatusTransitionError: `(from_status, to_status)` is
                not in `PERMITTED_TRANSITIONS` (and is not a same-status call
                with `allow_same_status=True`).
        """
        case = await session.get(ComplianceCase, case_id)
        if case is None:
            raise CaseNotFoundError(case_id)

        from_status = case.case_status
        if from_status != to_status:
            if (from_status, to_status) not in PERMITTED_TRANSITIONS:
                raise InvalidCaseStatusTransitionError(case_id, from_status, to_status)
            case.case_status = to_status
        elif not allow_same_status:
            raise InvalidCaseStatusTransitionError(case_id, from_status, to_status)

        session.add(
            CaseTimelineEvent(
                case_id=case.id,
                event_type=event_type,
                from_status=from_status.value,
                to_status=to_status.value,
                actor_id=actor_id,
                actor_type=actor_type,
                note=note,
                payload=payload or {},
            )
        )
        for event in extra_events or ():
            session.add(event)

        await session.commit()
        await session.refresh(case)
        return case

    async def _latest_approval_requested_event(
        self, session: AsyncSession, case_id: uuid.UUID
    ) -> CaseTimelineEvent | None:
        return await session.scalar(
            select(CaseTimelineEvent)
            .where(
                CaseTimelineEvent.case_id == case_id,
                CaseTimelineEvent.event_type == TimelineEventType.APPROVAL_REQUESTED,
            )
            .order_by(CaseTimelineEvent.occurred_at.desc())
            .limit(1)
        )


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["CaseLifecycleService", "MIN_SUBSTANTIVE_NOTE_LENGTH", "PERMITTED_TRANSITIONS"]
