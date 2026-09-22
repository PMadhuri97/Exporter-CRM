"""Case query interface — ANER-4.3-S6T1, scoped.

**What the doc actually says (S6T1).** The Jira doc's ANER-4.3-S6T1 section
("Build the case query interface") describes the read interface "used by all
consuming Epics and the compliance team", as operations *beyond* the ones in
its own Story S5T1 (queue management: "get my queue", "get team queue", "get
cases by status/customer/settlement", free-text "search cases", "get case
statistics", "get SLA compliance rate" — none of that is built here; S5T1 is
a different story this task was not asked to build). S6T1 itself lists:

- Get case by ID — the complete `compliance_case` record including the full
  `evidence_package` JSON, with PII-containing evidence restricted to
  compliance-officer callers.
- Get case timeline — every `case_timeline_event` for a case, chronological.
- Get case evidence items — every `case_evidence_item` for a case; evidence
  data decrypted for compliance-officer callers, metadata only
  (`evidence_type`, `source_epic`, `added_at`, `is_key_evidence`) otherwise.
- Get cases requiring SAR consideration — resolved cases whose
  `resolution_note` carries a SAR-consideration flag.
- Get case outcome statistics — resolution_action distribution and
  Epic-5.4-approval percentage, by date range.
- Get open cases count — by severity, for Epic 5.6's dashboard.
- Get case resolution audit — a self-contained structured report of every
  action taken on a case, for a regulator examining the platform.

**What this build implements vs. what it scopes out, and why:**

- Case detail (case + evidence + timeline), case timeline, case evidence
  items, cases-requiring-SAR-consideration, open-cases-count, and case
  resolution audit are all built below — every one of them reads only
  `cases`' own tables, so none of them needs to reach across the module
  boundary.
- **"Get case outcome statistics"** (resolution_action distribution *and* "the
  percentage of each case type that required Epic 5.4 maker-checker
  approval") and **S5T1's "get case statistics" / "get SLA compliance rate"**
  are NOT built here. They are broader analytics/reporting operations this
  task's own scope description does not name (it enumerates case detail,
  listing/search, and pending-approvals as the in-scope query shapes), they
  belong partly to a different story (S5T1) not assigned to this task, and
  "percentage ... required Epic 5.4 ... approval" presumes a real Epic 5.4
  concept (a formal approval *requirement* per case type) this module only
  has a lightweight maker-checker stand-in for (see
  `case_lifecycle_service.py`'s module docstring) — building a statistic
  framed around a system that does not really exist yet would manufacture a
  number with no real backing. Flagged here rather than built silently.
- **ANER-4.3-S6T2** (the regulatory reporting feed for Epic 5.5 — SAR
  candidates from screening_review/on_chain_escalation origins, transaction
  narratives, screening match details) is explicitly out of scope: Epic 5.5
  does not exist, and most of S6T2's fields (screening evidence, settlement
  corridors, customer profile) live in other epics' schemas this module must
  not import from. `get_cases_requiring_sar_consideration` below implements
  only S6T1's narrower, single-criterion version of the same idea (the
  resolution_note flag), which needs none of that.
- **Free-text "search cases"** (S5T1: "searches across case_reference, title,
  customer name, and settlement reference") is out of scope in its full form
  for a boundary reason worth calling out explicitly: `customer name` and
  `settlement reference` are not columns on `compliance_case` — only bare,
  FK-less `customer_id` / `settlement_id` UUIDs (see this module's README,
  "No cross-schema referential integrity on the case subject"). Resolving a
  name or a settlement reference would mean querying `app.modules.customers`
  / `app.modules.settlement`, which this module is not allowed to import
  from. `list_cases` below filters/searches only on `cases`' own columns
  (`case_reference`, `title`, `case_status`, `case_type`, `severity`,
  `assigned_to`) — the doc's own filters that stay inside the schema
  boundary.
- **"Pending approvals"** already has a home: `CaseLifecycleService.
  list_pending_approvals` (S4T2's maker-checker stand-in) is tested and
  working. This module does not re-implement or wrap it — a second name for
  the same query would be pure duplication risk (two places that could drift
  on what "pending" means) for zero benefit, since nothing here needs to
  compose it with another query. A caller who needs both case-detail queries
  and the pending-approvals queue uses `CaseQueryService` and
  `CaseLifecycleService` side by side, exactly as `CaseNoteService` and
  `CaseLifecycleService` already coexist today.

**Efficient reads.** `get_case_detail` uses `selectinload` (not `joinedload`)
on `ComplianceCase.evidence_items` / `.timeline_events` — both viewonly
relationships added in `domain/entities/compliance_case.py` for exactly this.
`selectinload` issues one query per collection (so three total queries for a
case + its evidence + its timeline, independent of how many rows each holds)
rather than either the N+1 pattern a naive per-item loop would produce, or a
single fanned-out `JOIN` that would duplicate every evidence row once per
timeline row (and vice versa) — the two collections have no relationship to
each other, so a join across both is a Cartesian product, not a saving.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.cases.domain.entities.case_evidence_item import CaseEvidenceItem
from app.modules.cases.domain.entities.case_timeline_event import CaseTimelineEvent
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import (
    PII_BEARING_EVIDENCE_TYPES,
    TERMINAL_CASE_STATUSES,
    ActorType,
    CaseSeverity,
    CaseStatus,
    CaseType,
)
from app.modules.cases.exceptions import CaseNotFoundError
from app.shared.exceptions import ValidationError

#: Jira doc, S6T1 acceptance criteria: "Get cases requiring SAR consideration
#: returns only cases with the SAR flag in the resolution note." The doc never
#: defines a structured field or exact literal for that flag anywhere in Epic
#: 4.3 (S7T4's documentation task lists "SAR flagging — when and how to flag a
#: case ... in the resolution note" as prose still to be *written*, not a spec
#: given here) — there is no `resolution_note_flags` column or enum, just free
#: text. This module makes an explicit, documented choice rather than
#: inventing a structured field the doc never asks for: a case-insensitive
#: substring match against the literal phrase compliance officers are shown
#: using throughout the doc's own text ("SAR consideration" appears verbatim
#: at ANER-4.3-S4T3's on_chain_escalation resolution description, in S6T1's
#: own operation name, and in S7T3's examination-readiness scenario). An
#: officer writes this phrase into `resolution_note`; nothing more elaborate
#: is specified.
SAR_CONSIDERATION_MARKER = "sar consideration"

#: Default page size for `list_cases` when the caller does not specify one.
#: The doc does not specify a pagination shape (only that results come back
#: "paginated"), so this stays a plain limit/offset rather than a cursor or an
#: envelope with a total count — a fuller pagination contract is for whichever
#: layer (an eventual `api/`) actually exposes this to a paginated UI.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


@dataclass(frozen=True, slots=True)
class EvidenceItemView:
    """One `case_evidence_item` row, shaped for a specific caller.

    `evidence_data` is `None` when redacted — see `CaseQueryService.
    _evidence_view` for exactly which callers see it and which do not. `None`
    rather than an empty dict: an empty dict would be indistinguishable from a
    real evidence item that happens to carry no data, `None` cannot be.
    """

    id: uuid.UUID
    evidence_type: str
    source_epic: str
    source_reference_id: uuid.UUID
    added_at: datetime
    added_by: str
    is_key_evidence: bool
    evidence_data: dict | None


@dataclass(frozen=True, slots=True)
class CaseDetail:
    """"Get case by ID" (S6T1), assembled with its evidence and timeline.

    `evidence_package` mirrors the same PII redaction `EvidenceItemView`
    applies to individual evidence items — see the module docstring's "Get
    case by ID" summary ("PII-containing evidence restricted to
    compliance-officer callers") and `CaseQueryService._redact_package`.
    """

    case: ComplianceCase
    evidence_items: list[EvidenceItemView]
    timeline_events: list[CaseTimelineEvent]
    evidence_package: dict


@dataclass(frozen=True, slots=True)
class ResolutionAuditEntry:
    """One line of a `get_case_resolution_audit` report — a single
    `case_timeline_event`, flattened to exactly the fields the doc's S6T1
    acceptance criteria asks a regulator-facing report to show: "every
    `case_timeline_event` with actor identity and timestamp"."""

    event_type: str
    from_status: str | None
    to_status: str
    actor_id: str
    actor_type: str
    note: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CaseResolutionAudit:
    """A self-contained structured audit report for one case (S6T1's "Get
    case resolution audit" / S7T3's "show me the complete audit trail for
    this flagged transaction").

    Self-contained means exactly what the doc says it means: every field a
    regulator needs is embedded here, with no id a reader would have to look
    up in another system to make sense of the report — `case_reference` (not
    just `case_id`), and the resolution fields spelled out rather than left
    implicit in the last timeline entry.
    """

    case_id: uuid.UUID
    case_reference: str
    case_type: str
    case_status: str
    created_at: datetime
    resolution_action: str | None
    resolution_note: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    events: list[ResolutionAuditEntry]


class CaseQueryService:
    """Read-only queries over `cases`' own tables (ANER-4.3-S6T1, scoped —
    see the module docstring for exactly what "scoped" excludes and why).

    Every method here is read-only: none commits, none mutates a row. That is
    not merely a convention — the doc's own S6T1 text states "All operations
    are read-only" for this story.
    """

    __slots__ = ()

    # ── Get case by ID ───────────────────────────────────────────────────────

    async def get_case_detail(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        *,
        caller_actor_type: ActorType,
    ) -> CaseDetail:
        """The complete case, its evidence items, and its timeline, assembled
        in one call — S6T1's "Get case by ID" plus the doc's related "Get case
        timeline" / "Get case evidence items" operations, combined here for
        the common "open this case" read a console screen needs in one round
        trip rather than three separate ones.

        Args:
            caller_actor_type: `ActorType.COMPLIANCE_OFFICER` sees the full,
                undedacted `evidence_package` and evidence item payloads. Any
                other caller (`OPERATIONS_OFFICER`, `SYSTEM`,
                `EXTERNAL_APPROVER`) gets PII-bearing evidence items with
                `evidence_data=None` — see `_evidence_view` /
                `_redact_package`. Matches the doc's own words: "For
                PII-containing evidence, access is restricted to compliance
                officer callers."

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
        """
        case = await session.scalar(
            select(ComplianceCase)
            .where(ComplianceCase.id == case_id)
            .options(
                selectinload(ComplianceCase.evidence_items),
                selectinload(ComplianceCase.timeline_events),
            )
        )
        if case is None:
            raise CaseNotFoundError(case_id)

        is_compliance_officer = caller_actor_type == ActorType.COMPLIANCE_OFFICER
        evidence_items = [
            self._evidence_view(item, is_compliance_officer=is_compliance_officer)
            for item in case.evidence_items
        ]
        evidence_package = self._redact_package(
            case.evidence_package, is_compliance_officer=is_compliance_officer
        )

        return CaseDetail(
            case=case,
            evidence_items=evidence_items,
            timeline_events=list(case.timeline_events),
            evidence_package=evidence_package,
        )

    # ── Get case timeline ────────────────────────────────────────────────────

    async def get_case_timeline(
        self, session: AsyncSession, case_id: uuid.UUID
    ) -> list[CaseTimelineEvent]:
        """Every `case_timeline_event` for `case_id`, chronological
        (`occurred_at` ascending) — the doc's own words for this operation:
        "the complete audit trail for a single case."

        No PII redaction: unlike evidence, the doc does not restrict timeline
        access by caller type anywhere in S6T1's text.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
        """
        await self._require_case_exists(session, case_id)
        result = await session.execute(
            select(CaseTimelineEvent)
            .where(CaseTimelineEvent.case_id == case_id)
            .order_by(CaseTimelineEvent.occurred_at)
        )
        return list(result.scalars().all())

    # ── Get case evidence items ──────────────────────────────────────────────

    async def get_case_evidence_items(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        *,
        caller_actor_type: ActorType,
    ) -> list[EvidenceItemView]:
        """Every `case_evidence_item` for `case_id`, oldest first, shaped per
        caller — see `get_case_detail`'s `caller_actor_type` doc for the
        redaction rule.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
        """
        await self._require_case_exists(session, case_id)
        result = await session.execute(
            select(CaseEvidenceItem)
            .where(CaseEvidenceItem.case_id == case_id)
            .order_by(CaseEvidenceItem.added_at)
        )
        is_compliance_officer = caller_actor_type == ActorType.COMPLIANCE_OFFICER
        return [
            self._evidence_view(item, is_compliance_officer=is_compliance_officer)
            for item in result.scalars().all()
        ]

    # ── Listing / filtering (the schema-bounded slice of S5T1 this task names) ─

    async def list_cases(
        self,
        session: AsyncSession,
        *,
        status: CaseStatus | list[CaseStatus] | None = None,
        case_type: CaseType | None = None,
        severity: CaseSeverity | None = None,
        assigned_to: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[ComplianceCase]:
        """List/filter cases by status (one or more — S5T1's "accepts one or
        more case_status values"), case_type, severity, and/or assignee.

        Ordered newest-first (`created_at` descending) — the doc does not
        specify an ordering for this general filter shape (only "get my
        queue" / "get team queue", a different, out-of-scope operation,
        specify priority/SLA ordering), so this uses the same "most recent
        first" default the doc states explicitly for "get cases by customer".

        Args:
            limit: capped at `MAX_LIST_LIMIT` (200) to keep this a bounded
                read regardless of caller input — not a pagination envelope
                (see module docstring), just a floor against an unbounded
                table scan.

        Raises:
            ValidationError: `limit` is not positive, exceeds `MAX_LIST_LIMIT`,
                or `offset` is negative.
        """
        if limit <= 0 or limit > MAX_LIST_LIMIT:
            raise ValidationError(f"limit must be between 1 and {MAX_LIST_LIMIT}, got {limit}")
        if offset < 0:
            raise ValidationError(f"offset must not be negative, got {offset}")

        query = select(ComplianceCase)
        if status is not None:
            statuses = status if isinstance(status, list) else [status]
            query = query.where(ComplianceCase.case_status.in_(statuses))
        if case_type is not None:
            query = query.where(ComplianceCase.case_type == case_type)
        if severity is not None:
            query = query.where(ComplianceCase.severity == severity)
        if assigned_to is not None:
            query = query.where(ComplianceCase.assigned_to == assigned_to)

        query = query.order_by(ComplianceCase.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(query)
        return list(result.scalars().all())

    # ── Get open cases count ─────────────────────────────────────────────────

    async def get_open_cases_count(
        self, session: AsyncSession
    ) -> dict[CaseSeverity, int]:
        """Current count of open cases by severity (S6T1: "Used by Epic 5.6
        for the real-time compliance monitoring dashboard").

        **Interpretation of "open".** The doc does not say whether "open"
        means literally `case_status == 'OPEN'` (a case nobody has even
        picked up yet) or "not yet closed" (any non-terminal status). A
        real-time dashboard counting only the narrow `OPEN` status would
        undercount every case currently `ASSIGNED`/`UNDER_INVESTIGATION`/
        `ESCALATED`/etc. — i.e. every case actually being worked — which
        defeats the stated purpose ("real-time compliance monitoring"). This
        method uses the broader, dashboard-useful reading: any case not yet
        in a terminal status (`TERMINAL_CASE_STATUSES`), mirroring the same
        non-terminal-vs-terminal distinction `SlaCalculationService.
        is_sla_breached` already uses throughout this module.

        Severities with zero open cases are omitted (not present with a `0`
        value) — a plain `GROUP BY` result, not a completeness guarantee over
        `CaseSeverity`'s members.
        """
        result = await session.execute(
            select(ComplianceCase.severity, func.count())
            .where(ComplianceCase.case_status.notin_(TERMINAL_CASE_STATUSES))
            .group_by(ComplianceCase.severity)
        )
        return {severity: count for severity, count in result.all()}

    # ── Get cases requiring SAR consideration ────────────────────────────────

    async def get_cases_requiring_sar_consideration(
        self, session: AsyncSession
    ) -> list[ComplianceCase]:
        """Resolved cases whose `resolution_note` carries the SAR-consideration
        flag — see `SAR_CONSIDERATION_MARKER`'s docstring for what counts as
        "flagged" and why.

        S6T1's version only, not S6T2's broader multi-criterion "SAR
        candidates" feed (screening_review high-severity approvals,
        on_chain_escalation manual resolutions) — see the module docstring for
        why that is out of scope. Ordered newest-resolved-first.
        """
        result = await session.execute(
            select(ComplianceCase)
            .where(
                ComplianceCase.case_status == CaseStatus.RESOLVED,
                ComplianceCase.resolution_note.isnot(None),
                ComplianceCase.resolution_note.ilike(f"%{SAR_CONSIDERATION_MARKER}%"),
            )
            .order_by(ComplianceCase.resolved_at.desc())
        )
        return list(result.scalars().all())

    # ── Get case resolution audit ─────────────────────────────────────────────

    async def get_case_resolution_audit(
        self, session: AsyncSession, case_id: uuid.UUID
    ) -> CaseResolutionAudit:
        """A self-contained, regulator-facing audit report for `case_id` — see
        `CaseResolutionAudit`'s docstring for what "self-contained" means
        here, and S7T3's "show me the complete audit trail for this flagged
        transaction" for the scenario this exists to answer.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
        """
        case = await self._require_case_exists(session, case_id)
        events = await self.get_case_timeline(session, case_id)

        return CaseResolutionAudit(
            case_id=case.id,
            case_reference=case.case_reference,
            case_type=case.case_type.value,
            case_status=case.case_status.value,
            created_at=case.created_at,
            resolution_action=case.resolution_action.value if case.resolution_action else None,
            resolution_note=case.resolution_note,
            resolved_by=case.resolved_by,
            resolved_at=case.resolved_at,
            events=[
                ResolutionAuditEntry(
                    event_type=event.event_type.value,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    actor_id=event.actor_id,
                    actor_type=event.actor_type.value,
                    note=event.note,
                    occurred_at=event.occurred_at,
                )
                for event in events
            ],
        )

    # ── shared machinery ─────────────────────────────────────────────────────

    async def _require_case_exists(
        self, session: AsyncSession, case_id: uuid.UUID
    ) -> ComplianceCase:
        case = await session.get(ComplianceCase, case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        return case

    def _evidence_view(
        self, item: CaseEvidenceItem, *, is_compliance_officer: bool
    ) -> EvidenceItemView:
        """Redact `evidence_data` unless the caller is a compliance officer
        AND the evidence type actually carries PII — a non-PII item (e.g.
        `DUPLICATION_CHECK`, `VESSEL_TRACKING`) is not withheld from anyone,
        matching `enums.PII_BEARING_EVIDENCE_TYPES`'s own per-type judgment
        rather than redacting everything for every non-compliance caller
        indiscriminately."""
        withhold = item.evidence_type in PII_BEARING_EVIDENCE_TYPES and not is_compliance_officer
        return EvidenceItemView(
            id=item.id,
            evidence_type=item.evidence_type.value,
            source_epic=item.source_epic,
            source_reference_id=item.source_reference_id,
            added_at=item.added_at,
            added_by=item.added_by,
            is_key_evidence=item.is_key_evidence,
            evidence_data=None if withhold else item.evidence_data,
        )

    def _redact_package(self, package: dict, *, is_compliance_officer: bool) -> dict:
        """Apply the same per-evidence-type PII rule `_evidence_view` uses to
        `compliance_case.evidence_package` (keyed by evidence_type, per
        `EvidenceAggregationService`'s documented shape — see that module's
        docstring). Each PII-bearing evidence-type's item summaries keep every
        field except `evidence_data` for a non-compliance-officer caller;
        non-PII evidence types pass through unchanged."""
        if is_compliance_officer:
            return package
        redacted: dict = {}
        for evidence_type, summaries in package.items():
            if evidence_type in {t.value for t in PII_BEARING_EVIDENCE_TYPES}:
                redacted[evidence_type] = [
                    {k: v for k, v in summary.items() if k != "evidence_data"}
                    for summary in summaries
                ]
            else:
                redacted[evidence_type] = summaries
        return redacted


__all__ = [
    "CaseDetail",
    "CaseQueryService",
    "CaseResolutionAudit",
    "EvidenceItemView",
    "ResolutionAuditEntry",
    "SAR_CONSIDERATION_MARKER",
]
