"""``BackgroundCheckService`` — the background-check gauge — **owner: Developer 4A**
(L4-03, L4-04, L4-06, L4-08; ``docs/contracts/background-check.md``).

The gauge answers "is it safe and lawful to work with them?" (architecture §3.3). It
is **not** the journey and not the qualification: this service never writes
``exporter_profile.journey`` and never touches another gauge's column, so a company
that is reopened, flagged or put on hold stays exactly as far along its journey as it
was (company-record §3.1, A5).

**Every move is one transaction** (contract §9), in this order:

1. lock the company row ``FOR UPDATE``;
2. check the move, the role and the text — nothing is assigned yet;
3. read the inputs through the 4A ↔ 4B seam in the same session;
4. (``CLEAR`` only) evaluate A3's prerequisites, still assigning nothing;
5. insert the decision and its evidence rows;
6. assign ``exporter_profile.background_check``;
7. write the history row through Developer 1's service (flush only);
8. commit once.

A refusal at step 2 or 4 leaves nothing behind because nothing has been written; a
failure after step 5 rolls the value, the decision, its evidence and the history row
back together, because they are one transaction.

**Roles are enforced per move, not per route** (contract §3). A route-level check
alone would let an OPERATIONS user flag a company, since the route that serves move 1
is the route that serves move 5.

**The 4A ↔ 4B seam is the only way in to screening and verification.** This module
imports ``ComplianceInputsReader``/``ComplianceInputsService`` and nothing else of
Developer 4B's: no ``screening_review_item``, no ``verification_result``, no review
tables (``4a-task.md`` §6.4). The reader is injectable so a unit test can pass a fake
without a database.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_POLICY,
    BackgroundCheckDecisionView,
    BackgroundCheckMove,
    ClearPolicy,
    DocumentInput,
    EvidenceItemView,
    EvidenceSelection,
    evaluate_clear_prerequisites,
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
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    BackgroundCheckMoveNotAllowedError,
    BackgroundCheckPrerequisitesUnmetError,
    BackgroundCheckReasonRequiredError,
    BackgroundCheckRiskRequiredError,
    BackgroundCheckRoleNotAllowedError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.infrastructure.repositories.crm_document_repository import (
    CrmDocumentRepository,
)
from app.platform.authentication.models import UserRole

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

#: Risk is required on `CLEAR` and on nothing else. Whether it is *allowed* on other
#: outcomes is D5 — open — so the service neither requires nor refuses it there.
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

    # ── The rules as data ────────────────────────────────────────────────────

    @staticmethod
    def allowed_moves(current: _State, role: UserRole) -> list[BackgroundCheckMove]:
        """Every move ``role`` may make from ``current``, with what each needs.

        A ``staticmethod`` because it is the rule table and touches no session — the
        same shape as ``ConversationService.allowed_moves`` and
        ``DealService.allowed_stage_moves``, so a reader comparing the three finds one
        pattern. Empty for DEVELOPER and API_USER, who make no move.

        This does **not** take ``CLEAR``'s prerequisites into account: whether they are
        met needs the seam and the company row, so a caller that wants an honest
        ``CLEAR`` button asks :meth:`clear_prerequisites`. Keeping the table pure is
        what lets it be unit-tested without a database.
        """
        return [
            BackgroundCheckMove(
                to=to_value,
                reason_required=(current, to_value) not in _NO_TEXT_REQUIRED,
                risk_required=to_value in _RISK_REQUIRED,
            )
            for (from_value, to_value), roles in _MOVES.items()
            if from_value is current and role in roles
        ]

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
        )

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
        current = profile.background_check

        # 2 — the move, the role and the text. Nothing is assigned yet.
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

        # 3 — the inputs, through the seam, in this session and under this lock.
        inputs = await self._reader.company_inputs(company_id)
        evidence = select_evidence(inputs, await self._company_documents(company_id))

        # 4 — CLEAR's prerequisites. Still nothing assigned.
        if to_value is _State.CLEAR:
            self._require_clear_prerequisites(company_id, inputs, risk=risk, evidence=evidence)

        # 5 — the decision and its evidence snapshot.
        previous = await self._decisions.latest_for_company(company_id)
        decision = BackgroundCheckDecision(
            id=uuid.uuid4(),
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
        )
        await self._decisions.record(decision, self._evidence_rows(evidence))

        # 6 — the gauge itself.
        profile.background_check = to_value

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
            },
        )

        # 8 — one commit.
        await self._db.commit()
        logger.info(
            "background_check.moved",
            company_id=str(company_id),
            from_value=current.value,
            to_value=to_value.value,
            decision_id=str(decision.id),
            actor_id=actor_id,
            evidence_count=evidence.count,
        )
        return self._to_view(decision, evidence)

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


__all__ = ["BackgroundCheckService"]
