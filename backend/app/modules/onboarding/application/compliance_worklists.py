"""Compliance work, as worklists: who is waiting on whom, since when, and how late.

Every list is **computed on read** from the gauge, the reviewer columns, the decision
chain and the open proposals. Nothing is stored and no scheduler runs: "overdue" is
true when someone looks and the deadline has passed. That is also the whole of v1's
notifications — the nav badges and the Home cards are counts and rows of these lists.

**Three clocks**, each in business time (``domain/business_time.py``,
``compliance_settings``):

* **review** — from the reviewer's assignment, allowance ``CRM_SLA_REVIEW``, **paused**
  while information is requested (that time is the information clock's);
* **information** — from the request (the ``MORE_INFO`` decision), ``CRM_SLA_INFO``;
* **approval** — from the proposal, ``CRM_SLA_APPROVAL``.

An unassigned review has no deadline: how long it waited to be picked up is its
``waiting_since``, a separate figure from the review clock.

**Eligible checkers.** A proposal's approvers are the active COMPLIANCE and ADMIN users
other than its proposer, the review's reviewer and the company's RM — and, for a CLEAR
at HIGH or CRITICAL risk, only ADMIN and holders of ``compliance:approve_high_risk``.
When that set is empty the item needs a lead's attention.

No item carries an identifier, and only the information-request list carries text (the
note saying what is needed). A badge is a number.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.compliance_settings import (
    business_calendar,
    due_soon_fraction,
    sla_approval,
    sla_info,
    sla_review,
)
from app.modules.onboarding.domain.assignment import (
    APPROVE_HIGH_RISK,
    ASSIGN_REVIEWS,
    CHECKER_ROLES,
    REVIEWER_ROLES,
    Permission,
    holds,
    needs_senior_checker,
)
from app.modules.onboarding.domain.business_time import (
    BusinessCalendar,
    Deadline,
    deadline,
    elapsed,
)
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.background_check_proposal import (
    BackgroundCheckProposal,
    BackgroundCheckProposalResolution,
    ProposalOutcome,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterJourney,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication import active_staff, staff_members
from app.platform.authentication.models import UserRole
from app.platform.authorization.services import users_holding
from app.shared import clock

Stage = Literal["review", "info", "approval"]
View = Literal["awaiting", "mine", "in_review", "overdue", "needs_attention"]

#: Views only ADMIN and holders of ``compliance:assign`` see.
LEAD_VIEWS: frozenset[str] = frozenset({"in_review", "overdue", "needs_attention"})

#: Rejections on one check after which a lead should look.
REJECTIONS_NEEDING_ATTENTION = 2

_State = BackgroundCheckState


def info_pause(
    chain: Iterable[BackgroundCheckDecision],
    *,
    assigned_at: datetime,
    now: datetime,
    calendar: BusinessCalendar,
) -> timedelta:
    """Business time the check spent in ``MORE_INFO`` since ``assigned_at``: the part
    of the review clock that does not count. ``chain`` is the company's decisions,
    oldest first; those before the assignment only set where it started.

    A reviewer assigned **while** information was requested starts with the clock
    paused: the request was decided before the assignment, so its span is counted from
    the assignment, not dropped.
    """
    total = timedelta()
    opened: datetime | None = None
    first = True
    for decision in chain:
        if decision.decided_at < assigned_at:
            continue
        if first:
            first = False
            if decision.from_value is _State.MORE_INFO:
                opened = assigned_at
        if decision.to_value is _State.MORE_INFO:
            opened = opened or decision.decided_at
        elif opened is not None and decision.from_value is _State.MORE_INFO:
            total += elapsed(opened, decision.decided_at, calendar)
            opened = None
    if opened is not None:
        total += elapsed(opened, now, calendar)
    return total


@dataclass(frozen=True)
class WorkItem:
    """One company's open compliance work, as a list row."""

    company_id: uuid.UUID
    company_name: str | None
    journey: ExporterJourney
    pipeline_status: CompanyPipelineStatus
    background_check: BackgroundCheckState
    stage: Stage
    relationship_manager_id: str | None
    reviewer_id: str | None
    reviewer_assigned_at: datetime | None
    waiting_since: datetime
    due_at: datetime | None
    is_due_soon: bool
    is_overdue: bool
    rejection_count: int
    proposal_id: uuid.UUID | None = None
    proposed_by: str | None = None
    proposal_to_value: BackgroundCheckState | None = None
    risk_rating: BackgroundCheckRisk | None = None
    needs_senior_approval: bool = False
    eligible_checkers: frozenset[str] = field(default_factory=frozenset)
    #: What the information request asked for — on the information-request list only.
    info_note: str | None = None
    reviewer_inactive: bool = False
    relationship_manager_inactive: bool = False

    @property
    def eligible_checker_count(self) -> int | None:
        return len(self.eligible_checkers) if self.stage == "approval" else None

    @property
    def needs_attention(self) -> bool:
        return (
            (self.stage == "approval" and not self.eligible_checkers)
            or self.rejection_count >= REJECTIONS_NEEDING_ATTENTION
            or self.reviewer_inactive
        )


@dataclass(frozen=True)
class WorklistCounts:
    """The nav badges: a number per list this viewer may see, ``None`` for a list they
    may not."""

    awaiting_review: int | None
    my_reviews: int | None
    awaiting_approval: int | None
    info_requested: int
    overdue: int | None
    needs_attention: int | None


@dataclass(frozen=True)
class RecentDecision:
    """A decision on a company the viewer owns or reviewed: no reason text."""

    company_id: uuid.UUID
    company_name: str | None
    decision_id: uuid.UUID
    to_value: BackgroundCheckState
    risk_rating: BackgroundCheckRisk | None
    decided_at: datetime
    decided_by: str | None
    approved_by: str | None


class ComplianceWorklists:
    """Reads the open compliance work. Read-only; takes no lock."""

    def __init__(self, db: AsyncSession, *, now: datetime | None = None) -> None:
        self._db = db
        self._now = now or clock.now()

    # ── The items ────────────────────────────────────────────────────────────

    async def items(
        self,
        *,
        include_info_notes: bool = False,
        company_ids: Collection[uuid.UUID] | None = None,
    ) -> list[WorkItem]:
        """Every company with open compliance work: under review (``IN_REVIEW`` or
        ``MORE_INFO``), or with a proposal awaiting approval. Oldest wait first.
        ``company_ids`` limits the read to those companies (a page of a list)."""
        if company_ids is not None and not company_ids:
            return []
        open_proposal = (
            select(BackgroundCheckProposal)
            .outerjoin(
                BackgroundCheckProposalResolution,
                BackgroundCheckProposalResolution.proposal_id == BackgroundCheckProposal.id,
            )
            .where(BackgroundCheckProposalResolution.id.is_(None))
            .subquery()
        )
        cols = open_proposal.c
        rows = (
            await self._db.execute(
                select(
                    ExporterProfile,
                    cols.id.label("proposal_id"),
                    cols.created_by.label("proposed_by"),
                    cols.created_at.label("proposed_at"),
                    cols.to_value.label("to_value"),
                    cols.risk_rating.label("risk_rating"),
                )
                .outerjoin(open_proposal, cols.company_id == ExporterProfile.customer_id)
                .where(
                    ExporterProfile.background_check.in_([_State.IN_REVIEW, _State.MORE_INFO])
                    | cols.id.isnot(None),
                    *(
                        [ExporterProfile.customer_id.in_(list(company_ids))]
                        if company_ids is not None
                        else []
                    ),
                )
            )
        ).all()
        if not rows:
            return []
        profiles = {row[0].customer_id: row[0] for row in rows}
        proposals = {row[0].customer_id: row for row in rows if row.proposal_id is not None}
        company_ids = list(profiles)

        heads = await self._latest_decisions(company_ids)
        pauses = await self._info_pauses(profiles)
        rejections = await self._rejections(heads)
        pool, senior = await self._checker_pools()
        people = await staff_members(
            self._db,
            [p.background_check_reviewer_id for p in profiles.values()]
            + [str(p.relationship_manager_user_id) for p in profiles.values() if p.relationship_manager_user_id],
        )

        calendar = business_calendar()
        fraction = due_soon_fraction()
        review_allowance, info_allowance, approval_allowance = (
            sla_review(),
            sla_info(),
            sla_approval(),
        )

        items: list[WorkItem] = []
        for company_id, profile in profiles.items():
            head = heads.get(company_id)
            rm = (
                str(profile.relationship_manager_user_id)
                if profile.relationship_manager_user_id is not None
                else None
            )
            reviewer = profile.background_check_reviewer_id
            base = {
                "company_id": company_id,
                "company_name": profile.name,
                "journey": profile.journey,
                "pipeline_status": profile.pipeline_status,
                "background_check": profile.background_check,
                "relationship_manager_id": rm,
                "reviewer_id": reviewer,
                "reviewer_assigned_at": profile.background_check_reviewer_assigned_at,
                "rejection_count": rejections.get(company_id, 0),
                "reviewer_inactive": reviewer is not None
                and (reviewer not in people or not people[reviewer].is_active),
                "relationship_manager_inactive": rm is not None
                and (rm not in people or not people[rm].is_active),
            }
            proposal = proposals.get(company_id)
            if proposal is not None:
                to_value = BackgroundCheckState(proposal.to_value)
                risk = BackgroundCheckRisk(proposal.risk_rating) if proposal.risk_rating else None
                senior_needed = needs_senior_checker(to_value, risk)
                eligible = (senior if senior_needed else pool) - {
                    proposal.proposed_by,
                    reviewer,
                    rm,
                }
                clock_ = self._deadline(
                    proposal.proposed_at, approval_allowance, calendar, fraction
                )
                items.append(
                    WorkItem(
                        **base,
                        stage="approval",
                        waiting_since=proposal.proposed_at,
                        due_at=clock_.due_at,
                        is_due_soon=clock_.is_due_soon,
                        is_overdue=clock_.is_overdue,
                        proposal_id=proposal.proposal_id,
                        proposed_by=proposal.proposed_by,
                        proposal_to_value=to_value,
                        risk_rating=risk,
                        needs_senior_approval=senior_needed,
                        eligible_checkers=frozenset(e for e in eligible if e),
                    )
                )
                continue
            since = head.decided_at if head is not None else profile.updated_at
            if profile.background_check is _State.MORE_INFO:
                clock_ = self._deadline(since, info_allowance, calendar, fraction)
                items.append(
                    WorkItem(
                        **base,
                        stage="info",
                        waiting_since=since,
                        due_at=clock_.due_at,
                        is_due_soon=clock_.is_due_soon,
                        is_overdue=clock_.is_overdue,
                        info_note=head.reason if include_info_notes and head is not None else None,
                    )
                )
                continue
            assigned_at = profile.background_check_reviewer_assigned_at
            if reviewer is None or assigned_at is None:
                items.append(
                    WorkItem(
                        **base,
                        stage="review",
                        waiting_since=since,
                        due_at=None,
                        is_due_soon=False,
                        is_overdue=False,
                    )
                )
                continue
            clock_ = self._deadline(
                assigned_at,
                review_allowance,
                calendar,
                fraction,
                paused=pauses.get(company_id, timedelta()),
            )
            items.append(
                WorkItem(
                    **base,
                    stage="review",
                    waiting_since=assigned_at,
                    due_at=clock_.due_at,
                    is_due_soon=clock_.is_due_soon,
                    is_overdue=clock_.is_overdue,
                )
            )
        items.sort(key=lambda item: (item.waiting_since, str(item.company_id)))
        return items

    def _deadline(
        self,
        started_at: datetime,
        allowance: timedelta,
        calendar,
        fraction: float,
        *,
        paused: timedelta = timedelta(),
    ) -> Deadline:
        return deadline(
            started_at,
            allowance,
            now=self._now,
            calendar=calendar,
            due_soon_fraction=fraction,
            paused=paused,
        )

    # ── Views ────────────────────────────────────────────────────────────────

    @staticmethod
    def view(items: list[WorkItem], name: View, *, viewer_id: str) -> list[WorkItem]:
        """One named list from the items. Who may see a lead view is the route's rule."""
        if name == "awaiting":
            return [i for i in items if i.stage == "review" and i.reviewer_id is None]
        if name == "mine":
            return [i for i in items if i.reviewer_id == viewer_id]
        if name == "in_review":
            return list(items)
        if name == "overdue":
            return [i for i in items if i.is_overdue]
        return [i for i in items if i.needs_attention]

    @staticmethod
    def may_approve(item: WorkItem, *, viewer_id: str) -> bool:
        return item.stage == "approval" and viewer_id in item.eligible_checkers

    @staticmethod
    def info_requests(
        items: list[WorkItem], *, relationship_manager: str | None, unowned: bool
    ) -> list[WorkItem]:
        """Companies waiting on information: one RM's, or those with no RM (buyer-only
        companies above all), or all."""
        info = [i for i in items if i.stage == "info"]
        if unowned:
            return [i for i in info if i.relationship_manager_id is None]
        if relationship_manager is not None:
            return [i for i in info if i.relationship_manager_id == relationship_manager]
        return info

    def counts(
        self,
        items: list[WorkItem],
        *,
        viewer_id: str,
        viewer_role: UserRole,
        viewer_permissions: frozenset[Permission],
    ) -> WorklistCounts:
        reviewer = viewer_role in REVIEWER_ROLES
        checker = viewer_role in CHECKER_ROLES
        lead = holds(viewer_permissions, ASSIGN_REVIEWS)
        return WorklistCounts(
            awaiting_review=(
                len(self.view(items, "awaiting", viewer_id=viewer_id)) if reviewer else None
            ),
            my_reviews=len(self.view(items, "mine", viewer_id=viewer_id)) if reviewer else None,
            awaiting_approval=(
                sum(1 for i in items if self.may_approve(i, viewer_id=viewer_id))
                if checker
                else None
            ),
            info_requested=len(
                self.info_requests(items, relationship_manager=viewer_id, unowned=False)
            ),
            overdue=len(self.view(items, "overdue", viewer_id=viewer_id)) if lead else None,
            needs_attention=(
                len(self.view(items, "needs_attention", viewer_id=viewer_id)) if lead else None
            ),
        )

    # ── Approval facts for the proposal queue ────────────────────────────────

    async def approval_facts(self, company_ids: list[uuid.UUID]) -> dict[uuid.UUID, WorkItem]:
        """The approval-stage items of these companies, by company."""
        return {
            item.company_id: item
            for item in await self.items(company_ids=set(company_ids))
            if item.stage == "approval"
        }

    async def approvable_by(self, viewer_id: str) -> list[WorkItem]:
        """Every proposal awaiting approval that ``viewer_id`` may approve, longest
        waiting first — the "awaiting me" queue, from the same rule as
        :meth:`may_approve`, with no cap."""
        return sorted(
            (
                item
                for item in await self.items()
                if self.may_approve(item, viewer_id=viewer_id)
            ),
            key=lambda item: (item.waiting_since, str(item.proposal_id)),
        )

    # ── Decisions on my companies ───────────────────────────────────────────

    async def recent_decisions(
        self, *, viewer_id: str, days: int = 14, limit: int = 20
    ) -> list[RecentDecision]:
        """Outcomes (CLEAR, FLAGGED, ON_HOLD) of the last ``days`` on companies the
        viewer is RM of, or that the viewer proposed — newest first."""
        since = self._now - timedelta(days=days)
        try:
            viewer_uuid: uuid.UUID | None = uuid.UUID(viewer_id)
        except ValueError:
            viewer_uuid = None
        mine = BackgroundCheckDecision.decided_by == viewer_id
        if viewer_uuid is not None:
            mine = mine | (ExporterProfile.relationship_manager_user_id == viewer_uuid)
        rows = (
            await self._db.execute(
                select(BackgroundCheckDecision, ExporterProfile.name)
                .join(
                    ExporterProfile,
                    ExporterProfile.customer_id == BackgroundCheckDecision.company_id,
                )
                .where(
                    BackgroundCheckDecision.decided_at >= since,
                    BackgroundCheckDecision.to_value.in_(
                        [_State.CLEAR, _State.FLAGGED, _State.ON_HOLD]
                    ),
                    mine,
                )
                .order_by(BackgroundCheckDecision.decided_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            RecentDecision(
                company_id=d.company_id,
                company_name=name,
                decision_id=d.id,
                to_value=d.to_value,
                risk_rating=d.risk_rating,
                decided_at=d.decided_at,
                decided_by=d.decided_by,
                approved_by=d.approved_by,
            )
            for d, name in rows
        ]

    # ── Reads ────────────────────────────────────────────────────────────────

    async def _latest_decisions(
        self, company_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, BackgroundCheckDecision]:
        rows = await self._db.execute(
            select(BackgroundCheckDecision)
            .where(BackgroundCheckDecision.company_id.in_(company_ids))
            .distinct(BackgroundCheckDecision.company_id)
            .order_by(
                BackgroundCheckDecision.company_id,
                BackgroundCheckDecision.decided_at.desc(),
                BackgroundCheckDecision.id.desc(),
            )
        )
        return {d.company_id: d for d in rows.scalars()}

    async def _info_pauses(
        self, profiles: dict[uuid.UUID, ExporterProfile]
    ) -> dict[uuid.UUID, timedelta]:
        """Business time each review spent waiting on information since its reviewer
        was assigned — the part of the review clock that does not count."""
        assigned = {
            company_id: p.background_check_reviewer_assigned_at
            for company_id, p in profiles.items()
            if p.background_check_reviewer_assigned_at is not None
        }
        if not assigned:
            return {}
        rows = await self._db.execute(
            select(BackgroundCheckDecision)
            .where(
                BackgroundCheckDecision.company_id.in_(list(assigned)),
                BackgroundCheckDecision.decided_at >= min(assigned.values()),
            )
            .order_by(BackgroundCheckDecision.company_id, BackgroundCheckDecision.decided_at)
        )
        chains: dict[uuid.UUID, list[BackgroundCheckDecision]] = defaultdict(list)
        for decision in rows.scalars():
            chains[decision.company_id].append(decision)
        calendar = business_calendar()
        return {
            company_id: info_pause(
                chain, assigned_at=assigned[company_id], now=self._now, calendar=calendar
            )
            for company_id, chain in chains.items()
        }

    async def _rejections(
        self, heads: dict[uuid.UUID, BackgroundCheckDecision]
    ) -> dict[uuid.UUID, int]:
        """Rejected proposals resting on each company's current decision: the returns
        since the check last moved."""
        head_ids = [d.id for d in heads.values()]
        if not head_ids:
            return {}
        rows = await self._db.execute(
            select(BackgroundCheckProposal.company_id, func.count())
            .join(
                BackgroundCheckProposalResolution,
                and_(
                    BackgroundCheckProposalResolution.proposal_id == BackgroundCheckProposal.id,
                    BackgroundCheckProposalResolution.outcome == ProposalOutcome.REJECTED.value,
                ),
            )
            .where(BackgroundCheckProposal.based_on_decision_id.in_(head_ids))
            .group_by(BackgroundCheckProposal.company_id)
        )
        return {company_id: count for company_id, count in rows}

    async def _checker_pools(self) -> tuple[frozenset[str], frozenset[str]]:
        """Every active checker, and the senior ones (COMPLIANCE users holding
        ``compliance:approve_high_risk``)."""
        checkers = await active_staff(self._db, CHECKER_ROLES)
        pool = frozenset(m.id for m in checkers)
        holders = await users_holding(
            self._db, *APPROVE_HIGH_RISK, among_roles=frozenset({UserRole.COMPLIANCE})
        )
        return pool, holders & pool


__all__ = [
    "LEAD_VIEWS",
    "REJECTIONS_NEEDING_ATTENTION",
    "ComplianceWorklists",
    "RecentDecision",
    "WorkItem",
    "WorklistCounts",
    "info_pause",
]
