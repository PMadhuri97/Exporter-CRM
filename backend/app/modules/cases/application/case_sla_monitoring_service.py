"""SLA monitoring — detection half only (ANER-4.3-S5T2, scoped).

**What the doc actually says.** ANER-4.3-S5T2 ("Implement SLA monitoring and
auto-escalation") describes one job, run every 15 minutes, that for every
case in a non-terminal status:

    Calculate whether the case has reached its auto_escalate_at threshold
    ... If the auto-escalate threshold has been reached and the case is not
    already escalated: Transition case_status to escalated ... Write a
    case_timeline_event ... Emit a case_sla_approaching event for Epic 4.6
    to deliver a notification to the team lead.
    Calculate whether the case has breached its sla_deadline. If sla_deadline
    is in the past and the case is not in a terminal status: Set
    sla_breached: true on the compliance_case record. Emit a
    case_sla_breached event for Epic 4.6 to deliver an urgent notification
    ...

Plus five Prometheus metrics and an idempotency acceptance criterion (a case
already escalated is not re-escalated on the next run).

**What this build implements vs. what it scopes out, and why.** The task
this module answers to is explicit: build only the *detection* half —
answering "which cases need attention" — never the *action* half (actually
transitioning a case, actually emitting an alert). Concretely:

- `list_breached_cases` and `list_cases_approaching_auto_escalation` below
  answer exactly the two "Calculate whether..." questions the doc's job asks
  every 15 minutes. Both are pure reads.
- Neither method calls `CaseLifecycleService.escalate_case`, writes a
  `case_timeline_event`, or touches `case_status` in any way. The doc's own
  auto-escalation transition is a *decision* ("this case should now become
  ESCALATED") layered on top of the detection this module performs — that
  decision, and whoever is authorized to make it (a scheduled job today,
  perhaps a human-reviewed step tomorrow), is explicitly left to whatever
  consumes these two functions.
- Neither method emits `case_sla_approaching` / `case_sla_breached`, and
  neither writes to a metrics registry. Alert delivery is Epic 4.6's domain
  (does not exist), and the Prometheus metrics the doc lists
  (`cases_open_total`, `cases_sla_breached_total`, `cases_auto_escalated_total`,
  `case_resolution_time_hours`, `cases_pending_approval_total`) are an
  observability concern for whatever process actually runs the 15-minute job
  — not something a detection query should emit as a side effect of being
  called.
- The 15-minute scheduled job itself is not built. There is no scheduler
  wired up anywhere in this module or its dependencies; `list_breached_cases`
  / `list_cases_approaching_auto_escalation` are the two building blocks such
  a job would call, not the job.

**The `compliance_case.sla_breached` stored-column question.** The column
exists (`cases_0001_case_management`, `nullable=False`, no default) and is
already read/written in exactly two places in this codebase before this
task: every `case_sql.py` test fixture writes it (always `False`), and
`CaseTransitionService.transition_case_to_review` resets it to `False` the
moment an `ONBOARDING_INTAKE` case gets its first `sla_deadline`. **Nothing
in this codebase has ever set it to `True`** — `SlaCalculationService.
is_sla_breached` (S1T2) computes breach status live from `sla_deadline` and
`case_status` and never writes back to the row, and every test that exercises
breach detection (`test_s1t2_sla_seed_loading.py`) asserts against that live
computation, never against the stored column's value.

This build chooses **(a) — compute and return breach status live, never
writing to the stored column** — for three reasons:

1. The task frames this whole piece as read-only detection. The doc's own
   text bundles "set `sla_breached: true`" together with "emit the breach
   alert" as one atomic job action; doing half of that bundled action (the
   write, without the alert it exists to accompany) would leave a persisted
   fact with no corresponding notification ever having been considered — a
   discrepancy nobody asked this task to introduce.
2. `SlaCalculationService.is_sla_breached` already is the tested, established
   source of truth for "is this case breached", computed live. Introducing a
   second, persisted signal that could disagree with it (if this function ran
   but a later config change altered what "breached" would compute to, or if
   the stored write failed independently of the read) creates exactly the
   drift risk a single source of truth is meant to avoid.
3. It is the only choice that makes the function usable at all: if
   `list_breached_cases` filtered on the *stored* `sla_breached` column
   instead of computing live, it would always return an empty list, since
   nothing has ever written `True` to that column — a query that can only
   ever answer "none" is not a query worth having.

The stored column itself is therefore, as of this task, still write-only
(written only as an explicit `False`) and read by nothing — a real,
pre-existing gap this task surfaces rather than silently working around.
Whoever eventually builds the actual escalation/alerting *action* half of
S5T2 is the natural place to decide whether to start writing `True` to it
(so other, unrelated readers of `compliance_case` rows can see breach status
without recomputing it) — that is an action-layer decision, not a
detection-layer one.

**`onboarding_intake` exclusion.** `ONBOARDING_INTAKE` cases have
`sla_deadline IS NULL` for their entire holding-state lifetime
(`ck_compliance_case_intake_has_no_sla_deadline`, S2). Both methods below
filter on `sla_deadline IS NOT NULL`, so an intake case can never appear in
either result — the same guarantee `SlaCalculationService.is_sla_breached`
already gives per-case ("a case with no deadline cannot be in breach of
one"), applied here as a set filter instead of a per-case check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.application.sla_service import SlaCalculationService
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import TERMINAL_CASE_STATUSES, CaseStatus
from app.modules.cases.exceptions import SlaTargetNotFoundError


@dataclass(frozen=True, slots=True)
class EscalationCandidate:
    """One case past its `auto_escalate_at` threshold without having been
    formally escalated yet — `list_cases_approaching_auto_escalation`'s
    result shape. Carries the computed threshold alongside the case so a
    consumer (a scheduled job, a manual dashboard) can show "how overdue" a
    candidate is without recomputing it."""

    case: ComplianceCase
    auto_escalate_at: datetime


class CaseSlaMonitoringService:
    """Read-only SLA breach and auto-escalation-threshold detection
    (ANER-4.3-S5T2, detection half only — see the module docstring for
    exactly what is and is not built here).

    Args:
        sla_service: an `SlaCalculationService` built from the loaded SLA
            config — same composition-root split `CaseTransitionService`
            already uses; this service does not touch the filesystem.
    """

    __slots__ = ("_sla_service",)

    def __init__(self, sla_service: SlaCalculationService) -> None:
        self._sla_service = sla_service

    async def list_breached_cases(self, session: AsyncSession) -> list[ComplianceCase]:
        """Every case currently in SLA breach: `sla_deadline` is in the past,
        the case is not in a terminal status, and `sla_deadline` is not null
        (which alone excludes every `ONBOARDING_INTAKE` case — see module
        docstring).

        A single query mirroring exactly the rule `SlaCalculationService.
        is_sla_breached` already applies per-case (same terminal-status
        exemption: a `RESOLVED` or `CLOSED_WITHOUT_ACTION` case past its old
        deadline is not "currently breached" — the SLA measured how long it
        took to reach a conclusion, and a concluded case cannot still be
        running late). Computed live, not read from the stored
        `sla_breached` column — see the module docstring's "stored-column
        question" section for why.

        Ordered by `sla_deadline` ascending — the most overdue case first.
        """
        result = await session.execute(
            select(ComplianceCase)
            .where(
                ComplianceCase.sla_deadline.isnot(None),
                ComplianceCase.sla_deadline < _now(),
                ComplianceCase.case_status.notin_(TERMINAL_CASE_STATUSES),
            )
            .order_by(ComplianceCase.sla_deadline.asc())
        )
        return list(result.scalars().all())

    async def list_cases_approaching_auto_escalation(
        self, session: AsyncSession
    ) -> list[EscalationCandidate]:
        """Every case that has passed its `auto_escalate_at` threshold
        (`auto_escalate_at_pct` of its SLA window elapsed — 75% for
        CRITICAL/HIGH, 90% for MEDIUM/LOW per the seeded config) but has not
        been formally escalated via `CaseLifecycleService.escalate_case`.

        "Not already escalated" is read as `case_status != ESCALATED` —
        matching the doc's own idempotency acceptance criterion ("a case
        already escalated is not re-escalated on the next job run"): once a
        case reaches `ESCALATED`, it is no longer a candidate for *this*
        detection, regardless of how much further time passes. Terminal
        cases are excluded for the same reason `list_breached_cases` excludes
        them — a concluded case needs no escalation.

        One query loads every non-terminal, non-escalated, SLA-bearing case;
        the per-case `auto_escalate_at` threshold is then computed in memory
        via `SlaCalculationService.calculate_auto_escalate_at_from_fields`
        (pure, no DB) rather than through `calculate_auto_escalate_at`
        (which re-fetches the row by id) — avoiding an N+1 query pattern
        across however many candidates exist.

        **A case whose `case_type` has no configured SLA target is skipped,
        not raised.** `MANUAL` is the documented example
        (`sla_config_loader.py`'s `EXPECTED_CASE_TYPES` deliberately excludes
        it — see this module's own README, "`case_sla_config` has no target
        for `MANUAL`"): nothing stops a `MANUAL` case from being inserted
        with a non-null `sla_deadline` and a non-terminal status at the
        database level, since only `ONBOARDING_INTAKE` is constrained against
        having a deadline at all. Such a case cannot have its auto-escalation
        threshold computed — there is no `SlaTarget` to compute it from — so
        it is silently excluded from this result rather than crashing the
        whole detection query over one row that predates a real SLA policy.
        This mirrors `calculate_sla_deadline`'s own documented gap for
        `MANUAL` rather than inventing new handling for it.

        Ordered by how far past threshold each case is, most-overdue first.
        """
        result = await session.execute(
            select(ComplianceCase).where(
                ComplianceCase.sla_deadline.isnot(None),
                ComplianceCase.case_status.notin_(TERMINAL_CASE_STATUSES),
                ComplianceCase.case_status != CaseStatus.ESCALATED,
            )
        )
        now = _now()
        candidates: list[EscalationCandidate] = []
        for case in result.scalars().all():
            try:
                auto_escalate_at = self._sla_service.calculate_auto_escalate_at_from_fields(
                    case.case_type.value, case.severity.value, case.created_at
                )
            except SlaTargetNotFoundError:
                continue
            if now >= auto_escalate_at:
                candidates.append(EscalationCandidate(case=case, auto_escalate_at=auto_escalate_at))

        candidates.sort(key=lambda c: c.auto_escalate_at)
        return candidates


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["CaseSlaMonitoringService", "EscalationCandidate"]
