"""SLA deadline calculation for compliance cases (ANER-4.3-S1T2).

`SlaCalculationService` is built once, from the parsed GitOps YAML (see
`infrastructure/sla_config_loader.load_sla_config_mapping`), and held in
memory — the same composition-root split
`onboarding.domain.policies.document_requirements_service.
DocumentRequirementsService` uses: file I/O lives in the loader, this module
receives an already-parsed mapping and never touches the filesystem.

Three functions, matching the S1T2 spec exactly:

- `calculate_sla_deadline` is pure — `(case_type, severity, created_at)` plus
  the in-memory config, no database.
- `is_sla_breached` and `calculate_auto_escalate_at` read the one
  `compliance_case` row they are asked about, because both are defined in
  terms of a specific case's `case_id`, not a pair of raw inputs.

**A config redeploy never rewrites an open case's deadline.** `sla_deadline`
is computed once, by `calculate_sla_deadline`, at case-creation time (S2 —
case creation is out of scope here) and stored on `compliance_case.
sla_deadline`. Reloading this service's in-memory mapping (or the
`case_sla_config` table) changes what the *next* case created gets; `
is_sla_breached` and `calculate_auto_escalate_at` both read the deadline/config
percentage that was in force when the case's row was written, not whatever the
service holds now — the former directly, the latter by recomputing from
`created_at` against the target that matched at read time, which is only ever
correct if nobody expects it to reproduce a since-changed policy for an old
case. Retroactive change is a non-goal, not an edge case: it is the explicit
S1T2 acceptance criterion.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import TERMINAL_CASE_STATUSES
from app.modules.cases.exceptions import CaseNotFoundError, SlaTargetNotFoundError


@dataclass(frozen=True, slots=True)
class SlaTarget:
    """SLA hours and auto-escalation threshold for one (case_type, severity) pair."""

    case_type: str
    severity: str
    sla_hours: int
    auto_escalate_at_pct: int


class SlaCalculationService:
    """Computes SLA deadlines and breach/escalation status from a loaded config.

    Args:
        config: `(case_type, severity) -> SlaTarget`, both keys upper-cased —
            exactly what `sla_config_loader.load_sla_config_mapping` returns.
            Case-type and severity are accepted here as plain strings (not the
            `CaseType`/`CaseSeverity` enums) so a caller can pass either an
            enum member's `.value` or a raw string read back from the
            `case_sla_config` table's plain `String` columns without
            converting first.
    """

    __slots__ = ("_config",)

    def __init__(self, config: Mapping[tuple[str, str], SlaTarget]) -> None:
        self._config = dict(config)

    def get_target(self, case_type: str, severity: str) -> SlaTarget:
        """Look up the configured SLA target for a (case_type, severity) pair.

        Raises:
            SlaTargetNotFoundError: no target is configured for this pair.
        """
        key = (case_type.strip().upper(), severity.strip().upper())
        target = self._config.get(key)
        if target is None:
            raise SlaTargetNotFoundError(case_type=case_type, severity=severity)
        return target

    # ── Pure calculation ──────────────────────────────────────────────────────

    def calculate_sla_deadline(
        self, case_type: str, severity: str, created_at: datetime
    ) -> datetime:
        """The timestamp by which a case of this (case_type, severity) must be
        resolved, given when it was created.

        Pure: no I/O, no database. `created_at + sla_hours` for the configured
        pair.
        """
        target = self.get_target(case_type, severity)
        return created_at + timedelta(hours=target.sla_hours)

    # ── Case-backed reads ─────────────────────────────────────────────────────

    async def is_sla_breached(self, session: AsyncSession, case_id: object) -> bool:
        """True if `now` is past the case's stored `sla_deadline` and the case
        has not reached a terminal status.

        A case in `RESOLVED` or `CLOSED_WITHOUT_ACTION`
        (`TERMINAL_CASE_STATUSES`) never reports a breach, no matter how far
        past its deadline it sits: the SLA measures how long it took to reach a
        conclusion, and a concluded case cannot still be running late.

        `sla_deadline` is nullable since ANER-4.3-S2 (an `ONBOARDING_INTAKE`
        case has none — see `cases_0003_intake_sla_null`); a case with no
        deadline cannot be in breach of one, so this returns `False` rather
        than raising or treating `None` as "already breached".

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
        """
        case = await self._get_case(session, case_id)
        if case.case_status in TERMINAL_CASE_STATUSES:
            return False
        if case.sla_deadline is None:
            return False
        return _now() > case.sla_deadline

    async def calculate_auto_escalate_at(self, session: AsyncSession, case_id: object) -> datetime:
        """The timestamp at which this case should be auto-escalated.

        `created_at + (sla_hours * auto_escalate_at_pct / 100)`, using the SLA
        target for the case's own `case_type` / `severity` — not whatever this
        service's config currently holds for a *different* pair, and not
        re-derived from `sla_deadline` (which would silently pick up a config
        change made after the case was created).

        Delegates to `calculate_auto_escalate_at_from_fields` (the pure sibling
        added for ANER-4.3-S5T2's `CaseSlaMonitoringService`, which already has
        a batch of loaded `compliance_case` rows in hand and must not issue a
        second per-row query here just to recompute the same formula).

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            SlaTargetNotFoundError: the case's (case_type, severity) has no
                configured target — possible if the config was redeployed
                without it after the case was created.
        """
        case = await self._get_case(session, case_id)
        return self.calculate_auto_escalate_at_from_fields(
            case.case_type.value, case.severity.value, case.created_at
        )

    def calculate_auto_escalate_at_from_fields(
        self, case_type: str, severity: str, created_at: datetime
    ) -> datetime:
        """Pure sibling of `calculate_sla_deadline`, for the same formula
        `calculate_auto_escalate_at` computes from a database row.

        Added for ANER-4.3-S5T2 (`CaseSlaMonitoringService.
        list_cases_approaching_auto_escalation`): that service already loads
        every non-terminal, non-escalated case with one query and must compute
        this threshold for each of them without a second per-case database
        round trip. No I/O, no database — same contract as
        `calculate_sla_deadline`.

        Raises:
            SlaTargetNotFoundError: no target is configured for this pair.
        """
        target = self.get_target(case_type, severity)
        window = timedelta(hours=target.sla_hours * target.auto_escalate_at_pct / 100)
        return created_at + window

    async def _get_case(self, session: AsyncSession, case_id: object) -> ComplianceCase:
        case = await session.scalar(select(ComplianceCase).where(ComplianceCase.id == case_id))
        if case is None:
            raise CaseNotFoundError(case_id)
        return case


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["SlaCalculationService", "SlaTarget"]
