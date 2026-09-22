"""The one case_type transition in scope right now (ANER-4.3-S2): moving a
case from `ONBOARDING_INTAKE` to `ONBOARDING_REVIEW`.

This is deliberately narrow. Story S3's full case lifecycle / status
transition machinery — arbitrary `case_status` transitions, assignment,
resolution workflows — is separate, larger, unbuilt work and is not attempted
here. `CaseTransitionService` does exactly one thing: the specific,
narrow `case_type` transition RXIL intake completion needs today.

**Why the SLA deadline is computed here, not at case creation.** An
`ONBOARDING_INTAKE` case exists because RXIL data has arrived but required
documents/checks aren't all in yet — a holding state, not yet reviewable.
Nobody internal is accountable for how long RXIL or the counterparty takes to
supply the rest, so `ONBOARDING_INTAKE` is excluded from the SLA policy
entirely (`infrastructure/sla_config_loader.py`'s `EXPECTED_CASE_TYPES`) and
`compliance_case.sla_deadline` stays NULL for the whole time a case sits in
that state (`ck_compliance_case_intake_has_no_sla_deadline` enforces this at
the database level). The case only becomes something a human can actually
decide on once intake is complete, which is exactly when it moves to
`ONBOARDING_REVIEW` — so that is also the first moment an SLA means anything
for it, and `transition_case_to_review` calls
`SlaCalculationService.calculate_sla_deadline` with `created_at` set to *this
transition's own timestamp*, not the case's original `compliance_case.
created_at` (which only ever marked when the RXIL data first arrived, not
when the case became reviewable).

This transition is defined to happen exactly once per case: `case_type` moves
from `ONBOARDING_INTAKE` to `ONBOARDING_REVIEW` and never back, and a second
attempt against an already-transitioned (or never-intake) case is rejected
rather than silently no-op'd — see `InvalidCaseTransitionError`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.application.sla_service import SlaCalculationService
from app.modules.cases.domain.entities.case_timeline_event import CaseTimelineEvent
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import (
    ActorType,
    CaseSeverity,
    CaseType,
    TimelineEventType,
)
from app.modules.cases.exceptions import CaseNotFoundError, InvalidCaseTransitionError


class CaseTransitionService:
    """Moves a case's `case_type` from `ONBOARDING_INTAKE` to
    `ONBOARDING_REVIEW` and sets its SLA deadline for the first time.

    Args:
        sla_service: an `SlaCalculationService` built from the loaded SLA
            config (see `infrastructure/sla_config_loader.
            build_sla_calculation_service`) — the same composition-root split
            `SlaCalculationService` itself uses: this service does not touch
            the filesystem, it is handed an already-built calculator.
    """

    __slots__ = ("_sla_service",)

    def __init__(self, sla_service: SlaCalculationService) -> None:
        self._sla_service = sla_service

    async def transition_case_to_review(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        severity: CaseSeverity,
        actor_id: str,
        actor_type: ActorType = ActorType.SYSTEM,
        note: str | None = None,
    ) -> ComplianceCase:
        """Transition `case_id` from `ONBOARDING_INTAKE` to `ONBOARDING_REVIEW`.

        Sets `case_type`, `severity`, and — for the first time on this case —
        `sla_deadline`, computed from `severity` and *this call's own*
        timestamp, not the case's original `created_at`. Records a
        `case_timeline_event` (`STATUS_CHANGED`) documenting the transition,
        since every state change belongs in the case's audit trail.

        Args:
            severity: the severity to evaluate the case at for SLA purposes
                from this point on. Intake may have started with a different
                (or placeholder) severity; this is the severity the
                `ONBOARDING_REVIEW` SLA target is looked up under and the
                value the case's `severity` column is updated to.
            actor_id / actor_type: who/what performed the transition, recorded
                on the timeline event — typically `ActorType.SYSTEM` when an
                automated intake-completion check triggers it.
            note: optional free-text note recorded on the timeline event.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            InvalidCaseTransitionError: the case's current `case_type` is not
                `ONBOARDING_INTAKE` — this transition happens exactly once per
                case and is not idempotent.
        """
        case = await session.scalar(select(ComplianceCase).where(ComplianceCase.id == case_id))
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.case_type != CaseType.ONBOARDING_INTAKE:
            raise InvalidCaseTransitionError(
                case_id=case_id,
                from_case_type=case.case_type,
                to_case_type=CaseType.ONBOARDING_REVIEW,
            )

        transitioned_at = _now()
        deadline = self._sla_service.calculate_sla_deadline(
            case_type=CaseType.ONBOARDING_REVIEW.value,
            severity=severity.value,
            created_at=transitioned_at,
        )

        from_case_type = case.case_type
        case.case_type = CaseType.ONBOARDING_REVIEW
        case.severity = severity
        case.sla_deadline = deadline
        case.sla_breached = False

        session.add(
            CaseTimelineEvent(
                case_id=case.id,
                event_type=TimelineEventType.STATUS_CHANGED,
                from_status=from_case_type.value,
                to_status=CaseType.ONBOARDING_REVIEW.value,
                actor_id=actor_id,
                actor_type=actor_type,
                note=note,
                payload={
                    "transition": "case_type",
                    "from_case_type": from_case_type.value,
                    "to_case_type": CaseType.ONBOARDING_REVIEW.value,
                    "severity": severity.value,
                    "sla_deadline": deadline.isoformat(),
                },
            )
        )

        await session.commit()
        await session.refresh(case)
        return case


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["CaseTransitionService"]
