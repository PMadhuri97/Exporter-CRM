"""``BackgroundCheckService`` — the background-check gauge — **owner: Developer 4A**
(L4-03, L4-04, L4-06, L4-08; ``docs/contracts/background-check.md``).

The gauge answers "is it safe and lawful to work with them?" (architecture §3.3). It
is **not** the journey and not the qualification: this service never writes
``exporter_profile.journey`` and never touches another gauge's column, so a company
that is reopened, flagged or put on hold stays exactly as far along its journey as it
was (company-record §3.1, A5). The journey's one dependency on this gauge — a
``PROSPECT`` whose check becomes ``CLEAR`` becomes a ``CUSTOMER`` (decision 2) — is
Developer 2's method, called at step 7b in this move's transaction.

**Every move is one transaction** (contract §9), in this order:

1. lock the company row ``FOR UPDATE``;
2. check the caller's premise, the move, the role, the text and the risk — nothing
   is assigned yet;
3. read the inputs through the 4A ↔ 4B seam in the same session;
4. (``CLEAR`` only) evaluate A3's prerequisites, still assigning nothing;
5. insert the decision and its evidence rows;
6. assign ``exporter_profile.background_check``;
7. write the history row through Developer 1's service (flush only);
7b. (``CLEAR`` only) Developer 2's ``promote_to_customer_if_ready`` — a ``PROSPECT``
    becomes a ``CUSTOMER``, with its journey history row (flush only);
8. commit once, then announce ``company.became_customer`` if 7b promoted.

A refusal at step 2 or 4 leaves nothing behind because nothing has been written; a
failure after step 5 rolls the value, the decision, its evidence, the history row and
any promotion back together, because they are one transaction.

**Roles are enforced per move, not per route** (contract §3). A route-level check
alone would let an OPERATIONS user flag a company, since the route that serves move 1
is the route that serves move 5.

**The 4A ↔ 4B seam is the only way in to screening and verification.** This module
imports ``ComplianceInputsReader``/``ComplianceInputsService`` and nothing else of
Developer 4B's: no ``screening_review_item``, no ``verification_result``, no review
tables (``4a-task.md`` §6.4). The reader is injectable so a unit test can pass a fake
without a database.

**Cycles and rules versions (Developer 1, plans P2-3a–c and P2-4a).** Every decision
is stamped, at step 5, with the company's current check cycle (cycle 1 is created on
the company's first decision if no input created it first) and with the Clear rules
in force (``CURRENT_CLEAR_RULES``). The inputs read at step 3 are the current cycle's
only (seam v2). :meth:`start_cycle` begins a new cycle — a Re-KYC or Re-KYB — under the
same row lock, and on a ``CLEAR`` company records the reopen in the same transaction
(IQ-3), because there is no ``CLEAR → CLEAR`` move and the gauge must not read
``CLEAR`` while the new cycle's checks are outstanding.

**Maker-checker (Developer 1, plan P3-1b, decision A, IQ-1, IQ-17).** ``CLEAR``,
``FLAGGED`` and ``ON_HOLD`` need two people. :meth:`propose` records the move as a
proposal — every rule a move checks, plus ``CLEAR``'s prerequisites, evaluated now —
and the gauge does not move ("awaiting approval"). :meth:`approve`, by a *different*
COMPLIANCE or ADMIN user, re-checks that nothing has moved (the chain head, the gauge
and the inputs' fingerprint) and then writes the decision through the same
:meth:`_apply_move` every move uses, with ``decided_by`` the proposer and
``approved_by`` the approver, pins the evidence and promotes, in one transaction.
:meth:`reject` (with a reason, by someone else) and :meth:`withdraw` (by the proposer)
close it. While a proposal is open nothing else moves the check. ``_apply_move`` is
the one place a decision is written, and it refuses an approval-needing move that
does not come from :meth:`approve` (``BACKGROUND_CHECK_APPROVAL_REQUIRED``) — so no
path lets one user take a company to ``CLEAR``. The switch
``CRM_BACKGROUND_CHECK_MAKER_CHECKER`` may be off only in local/test
(``compliance_settings``).

**Expiry (Developer 1, plan P3-3a).** Every ``CLEAR`` stores ``expires_at`` =
``decided_at`` + the validity setting, both from one server timestamp, and writes the
company's current ``background_check_expires_at``; any move away from ``CLEAR`` clears
it. Nothing moves the gauge when a Clear expires (P3-3b): the readers report it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.compliance_settings import (
    clear_validity,
    maker_checker_enabled,
)
from app.modules.onboarding.application.exporter_profile_service import (
    CustomerAnnouncement,
    ExporterProfileService,
    announce_became_customer,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_POLICY,
    CURRENT_CLEAR_RULES,
    PROPOSAL_OPEN,
    BackgroundCheckCycleAction,
    BackgroundCheckDecisionView,
    BackgroundCheckMove,
    BackgroundCheckProposalView,
    ClearPolicy,
    DocumentInput,
    EvidenceItemView,
    EvidenceSelection,
    RequiredCheckState,
    evaluate_clear_prerequisites,
    inputs_fingerprint,
    required_check_states,
    select_evidence,
)
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ComplianceInputsReader,
)
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.background_check_proposal import (
    APPROVAL_MOVES,
    BackgroundCheckProposal,
    BackgroundCheckProposalResolution,
    ProposalOutcome,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle, CheckCycleKind
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.history_dimensions import (
    BACKGROUND_CHECK_APPROVAL,
    CHECK_CYCLE,
)
from app.modules.onboarding.exceptions import (
    BackgroundCheckApprovalRequiredError,
    BackgroundCheckApproverRoleNotAllowedError,
    BackgroundCheckMoveNotAllowedError,
    BackgroundCheckPrerequisitesUnmetError,
    BackgroundCheckProposalNotFoundError,
    BackgroundCheckProposalNotYoursError,
    BackgroundCheckProposalOpenError,
    BackgroundCheckProposalResolvedError,
    BackgroundCheckProposalStaleError,
    BackgroundCheckReasonRequiredError,
    BackgroundCheckRiskNotAllowedError,
    BackgroundCheckRiskRequiredError,
    BackgroundCheckRoleNotAllowedError,
    BackgroundCheckSelfApprovalError,
    BackgroundCheckStateChangedError,
    CheckCycleEmptyError,
    CheckCycleNotAllowedError,
    CheckCycleRoleNotAllowedError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.infrastructure.repositories.background_check_proposal_repository import (  # noqa: E501
    BackgroundCheckProposalRepository,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
)
from app.modules.onboarding.infrastructure.repositories.crm_document_repository import (
    CrmDocumentRepository,
)
from app.platform.authentication.models import UserRole
from app.shared import clock
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

_State = BackgroundCheckState

#: Who may make each move, and whether it needs text — contract §3, verbatim and
#: complete: all nine rows. Anything absent from this table is refused, which is what
#: keeps ``CLEAR → FLAGGED`` impossible without a separate rule saying so.
_MOVES: dict[tuple[_State, _State], frozenset[UserRole]] = {
    # 1 — the start. The only move with no text, and the only one OPERATIONS may
    #     make besides answering a MORE_INFO.
    (_State.NOT_STARTED, _State.IN_REVIEW): frozenset(
        {UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN}
    ),
    # 2 — CLEAR. Compliance or admin only, and the only move with prerequisites.
    (_State.IN_REVIEW, _State.CLEAR): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
    # 3 — asking for more.
    (_State.IN_REVIEW, _State.MORE_INFO): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
    # 4 — recording what arrived.
    (_State.MORE_INFO, _State.IN_REVIEW): frozenset(
        {UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN}
    ),
    # 5 — flagging.
    (_State.IN_REVIEW, _State.FLAGGED): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
    # 6 — holding a flagged company.
    (_State.FLAGGED, _State.ON_HOLD): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
    # 7 — reassessing a flagged company.
    (_State.FLAGGED, _State.IN_REVIEW): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
    # 8 — reassessing a company on hold.
    (_State.ON_HOLD, _State.IN_REVIEW): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
    # 9 — reopening a cleared company (decision 5). The only way new information about
    #     a cleared company is acted on: there is no `CLEAR → FLAGGED`.
    (_State.CLEAR, _State.IN_REVIEW): frozenset({UserRole.COMPLIANCE, UserRole.ADMIN}),
}

#: Every move but the start needs a reason or a note (contract §4). Expressed as the
#: exception so the rule reads the way the contract states it.
_NO_TEXT_REQUIRED: frozenset[tuple[_State, _State]] = frozenset(
    {(_State.NOT_STARTED, _State.IN_REVIEW)}
)

#: Risk is required on `CLEAR` and refused everywhere else (contract §7): it is
#: compliance's rating at the moment of clearing, and a rating on any other move would
#: become what the reader reports as the company's risk. The database refuses it too
#: (`ck_background_check_decision_risk_only_on_clear`).
_RISK_REQUIRED: frozenset[_State] = frozenset({_State.CLEAR})

#: Which act each move is, for the history row's ``source``. The route takes a
#: destination rather than a verb, so without this every move made through the API
#: would record the same source and the trail would no longer say whether a company
#: reached ``IN_REVIEW`` by being started, by answering a request, or by being
#: reassessed — three quite different things.
_METHOD_FOR_MOVE: dict[tuple[_State, _State], str] = {
    (_State.NOT_STARTED, _State.IN_REVIEW): "start_review",
    (_State.IN_REVIEW, _State.CLEAR): "clear",
    (_State.IN_REVIEW, _State.MORE_INFO): "request_more_info",
    (_State.MORE_INFO, _State.IN_REVIEW): "record_more_info",
    (_State.IN_REVIEW, _State.FLAGGED): "flag",
    (_State.FLAGGED, _State.ON_HOLD): "hold",
    (_State.FLAGGED, _State.IN_REVIEW): "reassess",
    (_State.ON_HOLD, _State.IN_REVIEW): "reassess",
    (_State.CLEAR, _State.IN_REVIEW): "reopen",
}


#: Who may start a new check cycle (IQ-3: compliance and admin, not the RM).
_CYCLE_ROLES: frozenset[UserRole] = frozenset({UserRole.COMPLIANCE, UserRole.ADMIN})

#: The gauge values a new cycle may start from (plan P2-3c). `CLEAR` also reopens;
#: `FLAGGED` and `ON_HOLD` are reassessed first, so they are absent.
_CYCLE_START_STATES: frozenset[_State] = frozenset(
    {_State.NOT_STARTED, _State.IN_REVIEW, _State.MORE_INFO, _State.CLEAR}
)

#: The kinds the API starts: the Re-KYC and Re-KYB buttons. `FULL` is reserved.
STARTABLE_CYCLE_KINDS: tuple[CheckCycleKind, ...] = (CheckCycleKind.RE_KYC, CheckCycleKind.RE_KYB)

#: How a kind is named in the reopen decision's reason ("Re-KYC: …", IQ-3).
_CYCLE_LABELS: dict[CheckCycleKind, str] = {
    CheckCycleKind.RE_KYC: "Re-KYC",
    CheckCycleKind.RE_KYB: "Re-KYB",
    CheckCycleKind.FULL: "Full re-check",
}

#: `event_type` of the `check_cycle` history row.
CYCLE_STARTED_EVENT = "check_cycle_started"

#: Who may propose, approve or reject (decision A): compliance and admin. The RM never
#: approves compliance (plan §8).
_APPROVER_ROLES: frozenset[UserRole] = frozenset({UserRole.COMPLIANCE, UserRole.ADMIN})

#: `event_type` of each `background_check_approval` history row. `from_status` /
#: `to_status` are the proposal's status: `OPEN` on proposing, then its outcome.
PROPOSED_EVENT = "background_check_proposed"
RESOLVED_EVENTS: dict[ProposalOutcome, str] = {
    ProposalOutcome.APPROVED: "background_check_approved",
    ProposalOutcome.REJECTED: "background_check_rejected",
    ProposalOutcome.WITHDRAWN: "background_check_withdrawn",
}


@dataclass(frozen=True)
class _Approval:
    """The approval :meth:`BackgroundCheckService.approve` carries into ``_apply_move``:
    the one way an approval-needing move is written while maker-checker is on."""

    proposal: BackgroundCheckProposal
    approved_by: str


@dataclass(frozen=True)
class ApprovedProposal:
    """What :meth:`BackgroundCheckService.approve` did: the decision it wrote, and the
    proposal, now ``APPROVED``."""

    decision: BackgroundCheckDecisionView
    proposal: BackgroundCheckProposalView


def proposal_view(
    proposal: BackgroundCheckProposal,
    resolution: BackgroundCheckProposalResolution | None = None,
) -> BackgroundCheckProposalView:
    """A proposal row and its resolution (if any), as a reader sees them."""
    return BackgroundCheckProposalView(
        id=proposal.id,
        company_id=proposal.company_id,
        based_on_decision_id=proposal.based_on_decision_id,
        from_value=proposal.from_value,
        to_value=proposal.to_value,
        risk_rating=proposal.risk_rating,
        reason=proposal.reason,
        proposed_by=proposal.created_by,
        proposed_at=proposal.created_at,
        cycle_id=proposal.cycle_id,
        rules_version=proposal.rules_version,
        evidence_count=proposal.evidence_count,
        status=resolution.outcome if resolution is not None else PROPOSAL_OPEN,
        resolved_by=resolution.created_by if resolution is not None else None,
        resolved_at=resolution.created_at if resolution is not None else None,
        resolution_reason=resolution.reason if resolution is not None else None,
        decision_id=resolution.decision_id if resolution is not None else None,
    )


@dataclass(frozen=True)
class StartedCycle:
    """What :meth:`BackgroundCheckService.start_cycle` did: the new cycle, and the
    reopen decision when the company was ``CLEAR``."""

    cycle: CheckCycle
    previous_cycle: CheckCycle
    reopen: BackgroundCheckDecisionView | None


class BackgroundCheckService:
    """Moves one company's background-check gauge, and records why.

    Args:
        db: The session. Every move commits it exactly once.
        reader: The 4A ↔ 4B seam. Defaults to Developer 4B's
            ``ComplianceInputsService`` on the same session; a test may pass a fake
            implementing ``ComplianceInputsReader`` to drive the rules without a
            database.
        clear_policy: What A3's ambiguous phrases mean (D1–D4, settled 28 September
            2026). Defaults to ``background_check_views.CLEAR_POLICY``; injectable so a
            test can pin behaviour without depending on the shipped answer.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        reader: ComplianceInputsReader | None = None,
        clear_policy: ClearPolicy | None = None,
    ) -> None:
        self._db = db
        self._reader: ComplianceInputsReader = reader or ComplianceInputsService(db)
        self._decisions = BackgroundCheckDecisionRepository(db)
        self._history = HistoryService(db)
        self._clear_policy = clear_policy or CLEAR_POLICY
        self._documents = CrmDocumentRepository(db)
        self._cycles = CheckCycleRepository(db)
        self._proposals = BackgroundCheckProposalRepository(db)

    # ── The rules as data ────────────────────────────────────────────────────

    @staticmethod
    def needs_approval(to_value: _State) -> bool:
        """Whether a move to ``to_value`` is proposed rather than recorded (IQ-1, with
        maker-checker on). Each of ``CLEAR``, ``FLAGGED`` and ``ON_HOLD`` has one legal
        origin, so the destination decides."""
        return maker_checker_enabled() and any(to is to_value for (_, to) in APPROVAL_MOVES)

    @staticmethod
    def allowed_moves(current: _State, role: UserRole) -> list[BackgroundCheckMove]:
        """Every move ``role`` may make from ``current``, with what each needs.

        A ``staticmethod`` because it is the rule table and touches no session — the
        same shape as ``ConversationService.allowed_moves`` and
        ``DealService.allowed_stage_moves``, so a reader comparing the three finds one
        pattern. Empty for DEVELOPER and API_USER, who make no move.

        ``approval_required`` marks the moves that will be proposed rather than
        recorded (maker-checker). While a proposal is open the read offers no move at
        all — the route asks :meth:`open_proposal` first.

        This does **not** take ``CLEAR``'s prerequisites into account: whether they are
        met needs the seam and the company row, so a caller that wants an honest
        ``CLEAR`` button asks :meth:`clear_prerequisites`. Keeping the table pure is
        what lets it be unit-tested without a database.
        """
        approval_on = maker_checker_enabled()
        return [
            BackgroundCheckMove(
                to=to_value,
                reason_required=(current, to_value) not in _NO_TEXT_REQUIRED,
                risk_required=to_value in _RISK_REQUIRED,
                approval_required=approval_on and (current, to_value) in APPROVAL_MOVES,
            )
            for (from_value, to_value), roles in _MOVES.items()
            if from_value is current and role in roles
        ]

    @staticmethod
    def startable_cycle_kinds(current: _State, role: UserRole) -> list[CheckCycleKind]:
        """The cycle kinds ``role`` may start from ``current``, ignoring whether the
        current cycle is empty (that needs the database: :meth:`cycle_actions`)."""
        if role not in _CYCLE_ROLES or current not in _CYCLE_START_STATES:
            return []
        return list(STARTABLE_CYCLE_KINDS)

    async def cycle_actions(
        self, company_id: uuid.UUID, current: _State, role: UserRole
    ) -> list[BackgroundCheckCycleAction]:
        """The new cycles this viewer may start now — served to the screen so the
        Re-KYC / Re-KYB buttons appear exactly when :meth:`start_cycle` would accept
        them. Read-only; advisory, like :meth:`clear_prerequisites`."""
        kinds = self.startable_cycle_kinds(current, role)
        if (
            not kinds
            or await self._proposals.open_for_company(company_id) is not None
            or await self._current_cycle_is_empty(company_id)
        ):
            return []
        return [
            BackgroundCheckCycleAction(
                kind=kind.value, reason_required=True, reopens=current is _State.CLEAR
            )
            for kind in kinds
        ]

    async def _current_cycle_is_empty(self, company_id: uuid.UUID) -> bool:
        """Nothing recorded in the current cycle: no result and no screening answer —
        read through the seam, which is already scoped to that cycle."""
        inputs = await self._reader.company_inputs(company_id)
        return not inputs.verifications and all(
            item.screening_review_item_id is None for item in inputs.screening_items
        )

    # ── Moves ────────────────────────────────────────────────────────────────

    async def start_review(
        self,
        company_id: uuid.UUID,
        *,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 1 — ``NOT_STARTED → IN_REVIEW``. The only move needing no text."""
        return await self._move(
            company_id,
            to_value=_State.IN_REVIEW,
            expected_from=frozenset({_State.NOT_STARTED}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=None,
            risk=None,
            method="start_review",
        )

    async def request_more_info(
        self,
        company_id: uuid.UUID,
        *,
        note: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 3 — ``IN_REVIEW → MORE_INFO``. ``note`` says what is needed."""
        return await self._move(
            company_id,
            to_value=_State.MORE_INFO,
            expected_from=frozenset({_State.IN_REVIEW}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=note,
            risk=None,
            method="request_more_info",
        )

    async def record_more_info(
        self,
        company_id: uuid.UUID,
        *,
        note: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 4 — ``MORE_INFO → IN_REVIEW``. ``note`` says what arrived.

        The architecture requires this note; ``history-row.md`` §4 omits it (**D14**,
        Developer 1's contract text). This service enforces the architecture.
        """
        return await self._move(
            company_id,
            to_value=_State.IN_REVIEW,
            expected_from=frozenset({_State.MORE_INFO}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=note,
            risk=None,
            method="record_more_info",
        )

    async def flag(
        self,
        company_id: uuid.UUID,
        *,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 5 — ``IN_REVIEW → FLAGGED``.

        Only from ``IN_REVIEW``. A cleared company is never flagged directly: that
        goes through a reopen (architecture §4.2), which is phase 4A-5.
        """
        return await self._move(
            company_id,
            to_value=_State.FLAGGED,
            expected_from=frozenset({_State.IN_REVIEW}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=None,
            method="flag",
        )

    async def hold(
        self,
        company_id: uuid.UUID,
        *,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 6 — ``FLAGGED → ON_HOLD``."""
        return await self._move(
            company_id,
            to_value=_State.ON_HOLD,
            expected_from=frozenset({_State.FLAGGED}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=None,
            method="hold",
        )

    async def clear(
        self,
        company_id: uuid.UUID,
        *,
        risk: BackgroundCheckRisk | None,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 2 — ``IN_REVIEW → CLEAR`` (phase 4A-4).

        One COMPLIANCE or ADMIN user decides; there is no second approver in the
        prototype (decision 5). Risk is required. A3's four prerequisites are
        evaluated by one pure function (``evaluate_clear_prerequisites``) under the row
        lock; D1–D4 settled what its phrases mean on 28 September 2026. Nothing is
        assigned until they pass.

        Raises:
            BackgroundCheckRiskRequiredError: no risk rating was given.
            BackgroundCheckPrerequisitesUnmetError: naming every unmet prerequisite.
        """
        return await self._move(
            company_id,
            to_value=_State.CLEAR,
            expected_from=frozenset({_State.IN_REVIEW}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=risk,
            method="clear",
        )

    async def reassess(
        self,
        company_id: uuid.UUID,
        *,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Moves 7 and 8 — ``FLAGGED → IN_REVIEW`` and ``ON_HOLD → IN_REVIEW``.

        One method for both because they are the same act: a concern is being looked at
        again. The starting value is whichever the company holds, and a company in
        neither state is refused.

        The decision being reassessed is **not** edited. This writes a new decision that
        supersedes it, so what was concluded at the time stays on the record
        (contract §5.4).
        """
        return await self._move(
            company_id,
            to_value=_State.IN_REVIEW,
            expected_from=frozenset({_State.FLAGGED, _State.ON_HOLD}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=None,
            method="reassess",
        )

    async def reopen(
        self,
        company_id: uuid.UUID,
        *,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckDecisionView:
        """Move 9 — ``CLEAR → IN_REVIEW`` (reopen, decision 5).

        The only route by which new information about a cleared company is acted on:
        ``CLEAR → FLAGGED`` does not exist (architecture §4.2), so the reopen's reason
        is always on the record before anything is concluded.

        **The company's journey is untouched.** A company that reached ``CUSTOMER``
        stays ``CUSTOMER`` while its check is reopened (company-record §3.1, A5) — this
        service never writes ``journey``, and a reopen is not a demotion.

        The clearing decision itself is unchanged in the database; the reopen is a new
        decision that supersedes it.
        """
        return await self._move(
            company_id,
            to_value=_State.IN_REVIEW,
            expected_from=frozenset({_State.CLEAR}),
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=None,
            method="reopen",
        )

    async def record_decision(
        self,
        company_id: uuid.UUID,
        *,
        to_value: _State,
        reason: str | None,
        risk: BackgroundCheckRisk | None,
        actor_id: str,
        actor_role: UserRole,
        seen_value: _State | None = None,
    ) -> BackgroundCheckDecisionView:
        """Record a move by naming where it goes. One entry point for the route.

        The API takes a destination rather than a verb, because the screen offers
        whatever ``allowed_moves`` returned and should not have to know that
        ``IN_REVIEW`` is reached by four different acts. Which act it is — and so what
        the history row records as its source — is resolved here from the company's
        current value, under the row lock.

        ``expected_from`` is every value that legally reaches ``to_value``, so a
        company sitting somewhere else is still refused with
        ``BACKGROUND_CHECK_MOVE_NOT_ALLOWED`` rather than being carried along by
        whichever move happens to fit.

        ``seen_value`` is the value the caller was looking at when it chose the move.
        Because four acts share the destination ``IN_REVIEW``, a request made from a
        stale screen could otherwise become a different act — a reassessment of a
        ``FLAGGED`` company arriving after someone cleared it would reopen the
        clearance. When given, it must equal the current value under the row lock or
        the move is refused with ``BACKGROUND_CHECK_STATE_CHANGED``.

        The named methods (``start_review``, ``clear``, ``reopen`` …) remain the
        internal vocabulary and are what other server code should call: they say what
        is happening at the call site.
        """
        origins = frozenset(
            from_value for (from_value, target) in _MOVES if target is to_value
        )
        if not origins:
            # Nothing legally reaches this value — `NOT_STARTED` is the only one, and
            # a check that has begun has begun.
            raise BackgroundCheckMoveNotAllowedError(company_id, "any value", to_value)
        return await self._move(
            company_id,
            to_value=to_value,
            expected_from=origins,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=risk,
            seen_value=seen_value,
        )

    async def start_cycle(
        self,
        company_id: uuid.UUID,
        *,
        kind: CheckCycleKind,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> StartedCycle:
        """Start a new check cycle — a Re-KYC or Re-KYB (plan P2-3c, IQ-3).

        One transaction, under the company row lock every move takes:

        1. lock the company ``FOR UPDATE`` — writers of inputs hold ``FOR SHARE``, so no
           input can land half in the old cycle and half in the new;
        2. check the role (COMPLIANCE, ADMIN), the kind, the reason and the gauge:
           ``NOT_STARTED``, ``IN_REVIEW``, ``MORE_INFO`` and ``CLEAR`` may start one;
           ``FLAGGED`` and ``ON_HOLD`` are reassessed first (409);
        3. refuse if the current cycle is still empty (409) — which is also why two
           starts at the same moment make **one** cycle: the second finds the first's
           new cycle empty;
        4. insert the next cycle (the seam now reads it, and it is empty);
        5. write the ``check_cycle`` history row;
        6. on a ``CLEAR`` company, record the reopen ``CLEAR → IN_REVIEW`` in the new
           cycle with the reason "Re-KYC: …" — the same move, rules and history row as
           :meth:`reopen` — so handovers pause until the new cycle is cleared;
        7. commit once.

        Raises:
            CheckCycleRoleNotAllowedError: (403) not COMPLIANCE or ADMIN.
            ValidationError: (422) a kind the API does not start, or no reason.
            CheckCycleNotAllowedError: (409) the company is ``FLAGGED`` or ``ON_HOLD``.
            CheckCycleEmptyError: (409) the current cycle has nothing recorded yet.
        """
        profile = await self._lock_profile(company_id)
        if actor_role not in _CYCLE_ROLES:
            raise CheckCycleRoleNotAllowedError(actor_role)
        if kind not in STARTABLE_CYCLE_KINDS:
            raise ValidationError(
                f"a {kind.value} cycle cannot be started here; start one of: "
                + ", ".join(k.value for k in STARTABLE_CYCLE_KINDS)
            )
        text = reason.strip() if reason else None
        if not text:
            raise ValidationError("a new check cycle needs a reason")
        current = profile.background_check
        if current not in _CYCLE_START_STATES:
            raise CheckCycleNotAllowedError(company_id, current)
        # A new cycle would change the inputs an open proposal rests on (P3-1b).
        await self._refuse_if_awaiting_approval(company_id)

        now = clock.now()
        previous = await self._cycles.current_or_initial(
            company_id, actor_id=actor_id, source_ref="background_check_service.start_cycle", at=now
        )
        if await self._current_cycle_is_empty(company_id):
            raise CheckCycleEmptyError(company_id, previous.number)

        reopen_id = uuid.uuid4() if current is _State.CLEAR else None
        cycle = await self._cycles.add_next(
            company_id,
            previous=previous,
            kind=kind,
            reason=text,
            actor_id=actor_id,
            source="background_check_service.start_cycle",
            source_ref=str(reopen_id) if reopen_id is not None else None,
            rules_version=CURRENT_CLEAR_RULES,
            at=now,
        )
        await self._history.record(
            company_id,
            dimension=CHECK_CYCLE,
            from_value=str(previous.number),
            to_value=str(cycle.number),
            actor_id=actor_id,
            source="background_check_service.start_cycle",
            reason=text,
            event_type=CYCLE_STARTED_EVENT,
            details={
                "cycle_id": str(cycle.id),
                "kind": kind.value,
                "previous_cycle_id": str(previous.id),
                "reopen_decision_id": str(reopen_id) if reopen_id is not None else None,
            },
        )

        reopen_view = None
        if current is _State.CLEAR:
            decision, evidence, _ = await self._apply_move(
                profile,
                to_value=_State.IN_REVIEW,
                expected_from=frozenset({_State.CLEAR}),
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"{_CYCLE_LABELS[kind]}: {text}",
                risk=None,
                method="reopen",
                cycle=cycle,
                decision_id=reopen_id,
            )
            reopen_view = self._to_view(decision, evidence)

        await self._db.commit()
        logger.info(
            "background_check.cycle_started",
            company_id=str(company_id),
            cycle_id=str(cycle.id),
            number=cycle.number,
            kind=kind.value,
            reopened=reopen_view is not None,
            actor_id=actor_id,
        )
        return StartedCycle(cycle=cycle, previous_cycle=previous, reopen=reopen_view)

    # ── Reads ────────────────────────────────────────────────────────────────

    async def clear_prerequisites(self, company_id: uuid.UUID) -> tuple[str, ...]:
        """Which of A3's prerequisites are unmet right now, ignoring the risk rating.

        For a screen that wants to explain what is outstanding before anyone presses
        anything. Read-only: it takes no lock, writes nothing and commits nothing, so
        it is safe to call on a page load. The answer is advisory — :meth:`clear`
        evaluates the same rule again under the row lock, which is what actually
        decides.

        ``risk`` is excluded because it is the actor's input at decision time, not a
        fact about the company.
        """
        inputs = await self._reader.company_inputs(company_id)
        prerequisites = evaluate_clear_prerequisites(
            inputs,
            # The risk is supplied with the decision, so a company is never "missing"
            # it in advance; the rule would otherwise always report it unmet here.
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs, await self._company_documents(company_id)),
            policy=self._clear_policy,
        )
        return prerequisites.unmet

    async def required_checks(self, company_id: uuid.UUID) -> tuple[RequiredCheckState, ...]:
        """Rule B's required types and their state in the current cycle (plan P3-2),
        for the read — so the screen keeps no list of its own. Read-only."""
        inputs = await self._reader.company_inputs(company_id)
        return required_check_states(inputs, self._clear_policy)

    # ── Maker-checker (Developer 1, plan P3-1b) ──────────────────────────────

    async def propose(
        self,
        company_id: uuid.UUID,
        *,
        to_value: _State,
        reason: str | None,
        risk: BackgroundCheckRisk | None,
        actor_id: str,
        actor_role: UserRole,
        seen_value: _State | None = None,
    ) -> BackgroundCheckProposalView:
        """Propose ``CLEAR``, ``FLAGGED`` or ``ON_HOLD`` (IQ-1). One transaction:

        1. lock the company ``FOR UPDATE``;
        2. every rule the move itself checks — premise, legality, role, text, risk —
           and that it is one of the approval moves;
        3. refuse if a proposal is already open (one per company);
        4. read the inputs; for ``CLEAR`` evaluate the prerequisites now, so a proposal
           that could never be approved is refused here, naming what is missing;
        5. insert the proposal — the chain head it rests on, the fingerprint of its
           evidence, the cycle and the rules — and its ``background_check_approval``
           history row; commit. The gauge does not move.

        Raises:
            BackgroundCheckProposalOpenError: (409) one is already awaiting approval.
            BackgroundCheckPrerequisitesUnmetError: (409) ``CLEAR`` with prerequisites
                outstanding.
            and every refusal a move raises (403/409/422).
        """
        profile = await self._lock_profile(company_id)
        current = profile.background_check
        origins = frozenset(origin for (origin, target) in APPROVAL_MOVES if target is to_value)
        if not origins:
            raise ValidationError(
                f"a move to {to_value.value} needs no approval; record it as a decision"
            )
        text, _method = self._check_move(
            profile,
            to_value=to_value,
            expected_from=origins,
            actor_role=actor_role,
            reason=reason,
            risk=risk,
            seen_value=seen_value,
        )
        await self._refuse_if_awaiting_approval(company_id)

        inputs = await self._reader.company_inputs(company_id)
        evidence = select_evidence(inputs, await self._company_documents(company_id))
        if to_value is _State.CLEAR:
            self._require_clear_prerequisites(company_id, inputs, risk=risk, evidence=evidence)

        head = await self._decisions.latest_for_company(company_id)
        if head is None:  # pragma: no cover — IN_REVIEW and FLAGGED always have a decision
            raise BackgroundCheckMoveNotAllowedError(company_id, current, to_value)
        cycle = await self._cycles.current_or_initial(
            company_id,
            actor_id=actor_id,
            source_ref="background_check_service.propose",
            at=clock.now(),
        )
        proposal = await self._proposals.add_proposal(
            BackgroundCheckProposal(
                id=uuid.uuid4(),
                company_id=company_id,
                based_on_decision_id=head.id,
                from_value=current,
                to_value=to_value,
                risk_rating=risk,
                reason=text,
                inputs_fingerprint=inputs_fingerprint(inputs, evidence),
                evidence_count=evidence.count,
                cycle_id=cycle.id,
                rules_version=CURRENT_CLEAR_RULES,
                created_by=actor_id,
                source="background_check_service.propose",
                source_ref=None,
            )
        )
        await self._history.record(
            company_id,
            dimension=BACKGROUND_CHECK_APPROVAL,
            from_value=None,
            to_value=PROPOSAL_OPEN,
            actor_id=actor_id,
            source="background_check_service.propose",
            reason=text,
            event_type=PROPOSED_EVENT,
            details={
                "proposal_id": str(proposal.id),
                "from_value": current.value,
                "to_value": to_value.value,
                "risk_rating": risk.value if risk else None,
                "based_on_decision_id": str(head.id),
                "evidence_count": evidence.count,
                "cycle_id": str(cycle.id),
                "rules_version": CURRENT_CLEAR_RULES,
            },
        )
        view = proposal_view(proposal)
        await self._db.commit()
        logger.info(
            "background_check.proposed",
            company_id=str(company_id),
            proposal_id=str(proposal.id),
            to_value=to_value.value,
            actor_id=actor_id,
        )
        return view

    async def approve(
        self,
        company_id: uuid.UUID,
        proposal_id: uuid.UUID,
        *,
        actor_id: str,
        actor_role: UserRole,
    ) -> ApprovedProposal:
        """Approve a proposal as a **different** COMPLIANCE or ADMIN user. One
        transaction: lock the company; refuse the proposer, a resolved proposal and a
        stale one (the gauge, the chain head or the inputs' fingerprint moved); write
        the decision through ``_apply_move`` — the same rules, ``CLEAR``'s prerequisites
        re-evaluated, the evidence pinned, the expiry set and the promotion made —
        with ``decided_by`` the proposer and ``approved_by`` this user; then the
        ``APPROVED`` resolution and its history row; commit once and announce.

        Raises:
            BackgroundCheckApproverRoleNotAllowedError: (403) not COMPLIANCE or ADMIN.
            BackgroundCheckProposalNotFoundError: (404) not this company's.
            BackgroundCheckProposalResolvedError: (409) already resolved.
            BackgroundCheckSelfApprovalError: (403) the proposer.
            BackgroundCheckProposalStaleError: (409) something moved since.
        """
        profile = await self._lock_profile(company_id)
        proposal = await self._open_proposal_to_resolve(company_id, proposal_id, actor_role)
        if actor_id == proposal.created_by:
            raise BackgroundCheckSelfApprovalError(proposal_id)
        why = await self._staleness(profile, proposal)
        if why is not None:
            raise BackgroundCheckProposalStaleError(proposal_id, why)

        decision, evidence, announcement = await self._apply_move(
            profile,
            to_value=proposal.to_value,
            expected_from=frozenset({proposal.from_value}),
            actor_id=proposal.created_by,
            actor_role=actor_role,
            reason=proposal.reason,
            risk=proposal.risk_rating,
            approval=_Approval(proposal=proposal, approved_by=actor_id),
        )
        resolution = await self._resolve(
            proposal,
            outcome=ProposalOutcome.APPROVED,
            actor_id=actor_id,
            reason=None,
            decision_id=decision.id,
            source="background_check_service.approve",
        )
        result = ApprovedProposal(
            decision=self._to_view(decision, evidence),
            proposal=proposal_view(proposal, resolution),
        )
        await self._db.commit()
        logger.info(
            "background_check.approved",
            company_id=str(company_id),
            proposal_id=str(proposal_id),
            decision_id=str(decision.id),
            actor_id=actor_id,
        )
        await announce_became_customer(announcement)
        return result

    async def reject(
        self,
        company_id: uuid.UUID,
        proposal_id: uuid.UUID,
        *,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckProposalView:
        """Reject a proposal, with a reason, as someone other than the proposer. The
        gauge does not move. A stale proposal can still be rejected — that is how one
        is cleared away.

        Raises:
            ValidationError: (422) no reason.
            BackgroundCheckSelfApprovalError: (403) the proposer (who may withdraw).
            and the not-found / resolved / role refusals of :meth:`approve`.
        """
        await self._lock_profile(company_id)
        proposal = await self._open_proposal_to_resolve(company_id, proposal_id, actor_role)
        if actor_id == proposal.created_by:
            raise BackgroundCheckSelfApprovalError(proposal_id)
        text = reason.strip() if reason else None
        if not text:
            raise ValidationError("a rejection needs a reason")
        resolution = await self._resolve(
            proposal,
            outcome=ProposalOutcome.REJECTED,
            actor_id=actor_id,
            reason=text,
            decision_id=None,
            source="background_check_service.reject",
        )
        view = proposal_view(proposal, resolution)
        await self._db.commit()
        logger.info(
            "background_check.proposal_rejected",
            company_id=str(company_id),
            proposal_id=str(proposal_id),
            actor_id=actor_id,
        )
        return view

    async def withdraw(
        self,
        company_id: uuid.UUID,
        proposal_id: uuid.UUID,
        *,
        reason: str | None,
        actor_id: str,
        actor_role: UserRole,
    ) -> BackgroundCheckProposalView:
        """Withdraw one's own proposal. Proposer only; the reason is optional.

        Raises:
            BackgroundCheckProposalNotYoursError: (403) not the proposer.
            and the not-found / resolved / role refusals of :meth:`approve`.
        """
        await self._lock_profile(company_id)
        proposal = await self._open_proposal_to_resolve(company_id, proposal_id, actor_role)
        if actor_id != proposal.created_by:
            raise BackgroundCheckProposalNotYoursError(proposal_id)
        text = reason.strip() if reason else None
        resolution = await self._resolve(
            proposal,
            outcome=ProposalOutcome.WITHDRAWN,
            actor_id=actor_id,
            reason=text or None,
            decision_id=None,
            source="background_check_service.withdraw",
        )
        view = proposal_view(proposal, resolution)
        await self._db.commit()
        logger.info(
            "background_check.proposal_withdrawn",
            company_id=str(company_id),
            proposal_id=str(proposal_id),
            actor_id=actor_id,
        )
        return view

    async def open_proposal(
        self, company_id: uuid.UUID
    ) -> tuple[BackgroundCheckProposalView, str | None] | None:
        """The company's proposal awaiting approval, and why it is stale (``None`` while
        it can still be approved) — or ``None`` when nothing awaits. Read-only and
        unlocked, like :meth:`clear_prerequisites`: advisory; :meth:`approve` decides
        again under the lock."""
        proposal = await self._proposals.open_for_company(company_id)
        if proposal is None:
            return None
        profile = await self._db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        if profile is None:
            raise ExporterProfileNotFoundError(company_id)
        return proposal_view(proposal), await self._staleness(profile, proposal)

    async def _refuse_if_awaiting_approval(self, company_id: uuid.UUID) -> None:
        open_proposal = await self._proposals.open_for_company(company_id)
        if open_proposal is not None:
            raise BackgroundCheckProposalOpenError(company_id, open_proposal.id)

    async def _open_proposal_to_resolve(
        self, company_id: uuid.UUID, proposal_id: uuid.UUID, actor_role: UserRole
    ) -> BackgroundCheckProposal:
        if actor_role not in _APPROVER_ROLES:
            raise BackgroundCheckApproverRoleNotAllowedError(actor_role)
        found = await self._proposals.get_for_company(company_id, proposal_id)
        if found is None:
            raise BackgroundCheckProposalNotFoundError(company_id, proposal_id)
        proposal, resolution = found
        if resolution is not None:
            raise BackgroundCheckProposalResolvedError(proposal_id, resolution.outcome)
        return proposal

    async def _staleness(
        self, profile: ExporterProfile, proposal: BackgroundCheckProposal
    ) -> str | None:
        """Why ``proposal`` no longer describes the company, or ``None`` if it still
        does: the gauge, the chain head and the inputs' fingerprint are as proposed."""
        if profile.background_check is not proposal.from_value:
            return f"the check is now {profile.background_check.value}"
        head = await self._decisions.latest_for_company(profile.customer_id)
        if head is None or head.id != proposal.based_on_decision_id:
            return "another decision was recorded since"
        inputs = await self._reader.company_inputs(profile.customer_id)
        evidence = select_evidence(inputs, await self._company_documents(profile.customer_id))
        if inputs_fingerprint(inputs, evidence) != proposal.inputs_fingerprint:
            return "its inputs changed since it was proposed"
        return None

    async def _resolve(
        self,
        proposal: BackgroundCheckProposal,
        *,
        outcome: ProposalOutcome,
        actor_id: str,
        reason: str | None,
        decision_id: uuid.UUID | None,
        source: str,
    ) -> BackgroundCheckProposalResolution:
        """The resolution row and its history row. Flushes only."""
        resolution = await self._proposals.add_resolution(
            BackgroundCheckProposalResolution(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                proposed_by=proposal.created_by,
                outcome=outcome.value,
                reason=reason,
                decision_id=decision_id,
                created_by=actor_id,
                source=source,
                source_ref=None,
            )
        )
        await self._history.record(
            proposal.company_id,
            dimension=BACKGROUND_CHECK_APPROVAL,
            from_value=PROPOSAL_OPEN,
            to_value=outcome.value,
            actor_id=actor_id,
            source=source,
            reason=reason,
            event_type=RESOLVED_EVENTS[outcome],
            details={
                "proposal_id": str(proposal.id),
                "from_value": proposal.from_value.value,
                "to_value": proposal.to_value.value,
                "proposed_by": proposal.created_by,
                "decision_id": str(decision_id) if decision_id else None,
            },
        )
        return resolution

    # ── The one move implementation ──────────────────────────────────────────

    async def _move(
        self,
        company_id: uuid.UUID,
        *,
        to_value: _State,
        expected_from: frozenset[_State],
        actor_id: str,
        actor_role: UserRole,
        reason: str | None,
        risk: BackgroundCheckRisk | None,
        method: str | None = None,
        seen_value: _State | None = None,
    ) -> BackgroundCheckDecisionView:
        """Contract §9's eight steps. Every public move is this function.

        ``expected_from`` is the set of values this move may start from — one for
        most moves, two for a reassessment. Naming it means a company sitting in a
        different state is refused with the move it actually asked for, rather than
        being silently redirected to whatever move happens to be legal from where it
        is.
        """
        # 1 — the company row, locked for the rest of the transaction.
        profile = await self._lock_profile(company_id)
        decision, evidence, announcement = await self._apply_move(
            profile,
            to_value=to_value,
            expected_from=expected_from,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
            risk=risk,
            method=method,
            seen_value=seen_value,
        )

        # 8 — one commit.
        await self._db.commit()
        logger.info(
            "background_check.moved",
            company_id=str(company_id),
            from_value=decision.from_value.value,
            to_value=to_value.value,
            decision_id=str(decision.id),
            actor_id=actor_id,
            evidence_count=evidence.count,
        )
        # After the commit, best effort (architecture §3.6).
        await announce_became_customer(announcement)
        return self._to_view(decision, evidence)

    async def _apply_move(
        self,
        profile: ExporterProfile,
        *,
        to_value: _State,
        expected_from: frozenset[_State],
        actor_id: str,
        actor_role: UserRole,
        reason: str | None,
        risk: BackgroundCheckRisk | None,
        method: str | None = None,
        seen_value: _State | None = None,
        cycle: CheckCycle | None = None,
        decision_id: uuid.UUID | None = None,
        approval: _Approval | None = None,
    ) -> tuple[BackgroundCheckDecision, EvidenceSelection, CustomerAnnouncement | None]:
        """Steps 2–7b on a company row the caller has locked. Flushes; never commits.

        Shared by :meth:`_move`, :meth:`start_cycle` (which records a reopen inside its
        own transaction) and :meth:`approve`. ``cycle`` stamps the decision with that
        cycle instead of the company's current one; ``decision_id`` fixes the new
        decision's id, so a cycle written first can name it.

        **The maker-checker gate is here**, because every decision is written here: a
        move that needs approval (IQ-1) is refused unless ``approval`` comes from
        :meth:`approve`, and while a proposal is open no other move is made.

        Returns ``(decision, evidence, announcement)``; the caller commits and then
        announces.
        """
        company_id = profile.customer_id
        current = profile.background_check

        # 2 — the caller's premise, the move, the role, the text and the risk. Nothing
        #     is assigned yet.
        text, method = self._check_move(
            profile,
            to_value=to_value,
            expected_from=expected_from,
            actor_role=actor_role,
            reason=reason,
            risk=risk,
            seen_value=seen_value,
            method=method,
        )
        # 2b — maker-checker (P3-1b). Only `approve` carries an approval.
        if approval is None:
            if maker_checker_enabled() and (current, to_value) in APPROVAL_MOVES:
                raise BackgroundCheckApprovalRequiredError(current, to_value)
            await self._refuse_if_awaiting_approval(company_id)

        # 3 — the inputs, through the seam, in this session and under this lock. The
        #     seam reads the current cycle's only (v2).
        inputs = await self._reader.company_inputs(company_id)
        evidence = select_evidence(inputs, await self._company_documents(company_id))

        # 4 — CLEAR's prerequisites. Still nothing assigned.
        if to_value is _State.CLEAR:
            self._require_clear_prerequisites(company_id, inputs, risk=risk, evidence=evidence)

        # 5 — the decision and its evidence snapshot, in the current cycle and under the
        #     rules in force (P2-3a, P2-4a).
        cycle = cycle or await self._cycles.current_or_initial(
            company_id,
            actor_id=actor_id,
            source_ref=f"background_check_service.{method}",
            at=clock.now(),
        )
        previous = await self._decisions.latest_for_company(company_id)
        # One server timestamp for a CLEAR's `decided_at` and `expires_at` (P3-3a), and
        # for an approval's `approved_at`. Read after the lock, so `decided_at` still
        # follows the chain; other moves keep the column default.
        stamp = None
        if to_value is _State.CLEAR or approval is not None:
            stamp = await self._db.scalar(select(func.clock_timestamp()))
        expires_at = stamp + clear_validity() if stamp and to_value is _State.CLEAR else None
        decision = BackgroundCheckDecision(
            id=decision_id or uuid.uuid4(),
            company_id=company_id,
            from_value=current,
            to_value=to_value,
            decided_by=actor_id,
            # Always MANUAL in the prototype: the one automatic move (the start on
            # RXIL results) is blocked on D12 and nothing writes AUTOMATED.
            decided_by_kind=BackgroundCheckDecidedByKind.MANUAL,
            source=BackgroundCheckDecisionSource.MANUAL,
            reason=text,
            risk_rating=risk,
            supersedes_decision_id=previous.id if previous else None,
            details={},
            rules_version=CURRENT_CLEAR_RULES,
            cycle_id=cycle.id,
            proposal_id=approval.proposal.id if approval else None,
            approved_by=approval.approved_by if approval else None,
            approved_at=stamp if approval else None,
            expires_at=expires_at,
        )
        if stamp is not None:
            decision.decided_at = stamp
        await self._decisions.record(decision, self._evidence_rows(evidence))

        # 6 — the gauge itself, and the current Clear's expiry (set on CLEAR, cleared on
        #     every move away — P3-3a).
        profile.background_check = to_value
        profile.background_check_expires_at = expires_at

        # 7 — the history row, in the same transaction (history contract §5).
        await self._history.record(
            company_id,
            dimension="background_check",
            from_value=current.value,
            to_value=to_value.value,
            actor_id=actor_id,
            source=f"background_check_service.{method}",
            reason=text,
            details={
                "decision_id": str(decision.id),
                "supersedes_decision_id": (
                    str(previous.id) if previous else None
                ),
                "risk_rating": risk.value if risk else None,
                "evidence_count": evidence.count,
                "cycle_id": str(cycle.id),
                "rules_version": CURRENT_CLEAR_RULES,
                "proposal_id": str(approval.proposal.id) if approval else None,
                "approved_by": approval.approved_by if approval else None,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )

        # 7b — the move to CUSTOMER (decision 2, A1). A PROSPECT whose check has just
        #      become CLEAR becomes a CUSTOMER in this same transaction (U4, taken as
        #      one transaction). Developer 2's method writes the journey; this service
        #      still never does. It flushes only, under the lock taken at step 1.
        announcement = None
        if to_value is _State.CLEAR:
            announcement = await ExporterProfileService(self._db).promote_to_customer_if_ready(
                profile,
                actor_id=actor_id,
                cause="background_check_clear",
                source=f"background_check_service.{method}",
            )
        return decision, evidence, announcement

    def _check_move(
        self,
        profile: ExporterProfile,
        *,
        to_value: _State,
        expected_from: frozenset[_State],
        actor_role: UserRole,
        reason: str | None,
        risk: BackgroundCheckRisk | None,
        seen_value: _State | None = None,
        method: str | None = None,
    ) -> tuple[str | None, str]:
        """Step 2: the caller's premise, the move, the role, the text and the risk —
        for a move and for a proposal alike. Assigns nothing. Returns the stripped text
        and the act's method name (for the history row's source)."""
        company_id = profile.customer_id
        current = profile.background_check
        if seen_value is not None and current is not seen_value:
            raise BackgroundCheckStateChangedError(company_id, seen_value, current)
        if current not in expected_from or (current, to_value) not in _MOVES:
            raise BackgroundCheckMoveNotAllowedError(company_id, current, to_value)
        if actor_role not in _MOVES[(current, to_value)]:
            raise BackgroundCheckRoleNotAllowedError(current, to_value, actor_role)
        # Resolved here rather than by the caller: only now is the starting value
        # known, and a reassessment from `FLAGGED` and one from `ON_HOLD` are the
        # same act under two different origins.
        method = method or _METHOD_FOR_MOVE[(current, to_value)]

        text = reason.strip() if reason else None
        if not text and (current, to_value) not in _NO_TEXT_REQUIRED:
            raise BackgroundCheckReasonRequiredError(current, to_value)
        if to_value in _RISK_REQUIRED and risk is None:
            raise BackgroundCheckRiskRequiredError(company_id)
        if to_value not in _RISK_REQUIRED and risk is not None:
            raise BackgroundCheckRiskNotAllowedError(current, to_value)
        return text, method

    def _require_clear_prerequisites(
        self,
        company_id: uuid.UUID,
        inputs: CompanyComplianceInputs,
        *,
        risk: BackgroundCheckRisk | None,
        evidence: EvidenceSelection,
    ) -> None:
        prerequisites = evaluate_clear_prerequisites(
            inputs,
            risk=risk,
            evidence=evidence,
            policy=self._clear_policy,
        )
        if not prerequisites.met:
            raise BackgroundCheckPrerequisitesUnmetError(company_id, prerequisites.unmet)

    async def _company_documents(self, company_id: uuid.UUID) -> tuple[DocumentInput, ...]:
        """Every document filed against the company, for the evidence rule to sift.

        Developer 3B's ``crm_document`` — there is no second document system
        (contract §6). Read through their repository's ``list_for_owner``, which is the
        only thing Dev4A may call on it (``4a-task.md`` §8).

        **Paged to exhaustion, not to the first page.** ``list_for_owner`` defaults to
        50 and returns the true total; a company with more than that would otherwise
        have a snapshot silently missing whatever fell off the end, and an append-only
        row cannot be corrected afterwards.

        The scan-status rule is D4's and is applied by ``select_evidence``, not here,
        so the decision stays in one pure, testable place.
        """
        page_size = 200
        offset = 0
        collected: list[DocumentInput] = []
        while True:
            rows, total = await self._documents.list_for_owner(
                company_id=company_id, limit=page_size, offset=offset
            )
            collected += [
                DocumentInput(document_id=row.id, scan_status=str(row.scan_status.value))
                for row in rows
            ]
            offset += len(rows)
            if not rows or offset >= total:
                return tuple(collected)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _evidence_rows(selection: EvidenceSelection) -> list[BackgroundCheckEvidence]:
        """The selection as rows. ``decision_id`` is set by the repository."""
        rows = [
            BackgroundCheckEvidence(
                kind=BackgroundCheckEvidenceKind.VERIFICATION_RESULT,
                verification_result_id=result_id,
                verification_review_id=review_id,
            )
            for result_id, review_id in selection.verifications
        ]
        rows += [
            BackgroundCheckEvidence(
                kind=BackgroundCheckEvidenceKind.SCREENING_ITEM,
                screening_review_item_id=item_id,
            )
            for item_id in selection.screening_items
        ]
        rows += [
            BackgroundCheckEvidence(
                kind=BackgroundCheckEvidenceKind.DOCUMENT,
                crm_document_id=document_id,
            )
            for document_id in selection.documents
        ]
        return rows

    @staticmethod
    def _to_view(
        decision: BackgroundCheckDecision, selection: EvidenceSelection
    ) -> BackgroundCheckDecisionView:
        evidence = [
            EvidenceItemView(
                kind=BackgroundCheckEvidenceKind.VERIFICATION_RESULT,
                verification_result_id=result_id,
                verification_review_id=review_id,
            )
            for result_id, review_id in selection.verifications
        ]
        evidence += [
            EvidenceItemView(
                kind=BackgroundCheckEvidenceKind.SCREENING_ITEM,
                screening_review_item_id=item_id,
            )
            for item_id in selection.screening_items
        ]
        evidence += [
            EvidenceItemView(
                kind=BackgroundCheckEvidenceKind.DOCUMENT, crm_document_id=document_id
            )
            for document_id in selection.documents
        ]
        return BackgroundCheckDecisionView(
            id=decision.id,
            company_id=decision.company_id,
            from_value=decision.from_value,
            to_value=decision.to_value,
            decided_by=decision.decided_by,
            decided_by_kind=decision.decided_by_kind,
            source=decision.source,
            decided_at=decision.decided_at,
            reason=decision.reason,
            risk_rating=decision.risk_rating,
            supersedes_decision_id=decision.supersedes_decision_id,
            evidence=tuple(evidence),
            rules_version=decision.rules_version,
            cycle_id=decision.cycle_id,
            proposal_id=decision.proposal_id,
            approved_by=decision.approved_by,
            approved_at=decision.approved_at,
            expires_at=decision.expires_at,
        )

    async def _lock_profile(self, company_id: uuid.UUID) -> ExporterProfile:
        """The company row, locked for the rest of the transaction.

        Exactly ``QualificationService._lock_profile``: two moves on one company
        serialise here, which is what stops a chain fork before the database's
        ``uq_background_check_decision_supersedes`` has to.
        """
        result = await self._db.execute(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ExporterProfileNotFoundError(company_id)
        return profile


__all__ = [
    "PROPOSED_EVENT",
    "RESOLVED_EVENTS",
    "STARTABLE_CYCLE_KINDS",
    "ApprovedProposal",
    "BackgroundCheckService",
    "StartedCycle",
    "proposal_view",
]
