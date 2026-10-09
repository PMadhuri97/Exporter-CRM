"""``SanctionsScreeningService`` — record screenings, decide their hits, and keep the
company's SANCTIONS check in step.

Recording a run
---------------
A run screens one subject — the company, a director or a beneficial owner — against a
set of lists, and records every possible match (a hit) with a first decision. It must
cover every **active, mandatory** list (as currently versioned), or it is refused. The
run belongs to the company's current check cycle.

Deciding a hit
--------------
Every decision is a new disposition that supersedes the previous one (append-only).
A true match is **proposed** (``TRUE_MATCH_PROPOSED``) and confirmed by a second
officer, or by the head of compliance, per ``CRM_SANCTIONS_TRUE_MATCH_APPROVAL``; with
``SINGLE`` the officer's own decision stands. A rejected proposal returns the hit to
OPEN. A confirmed true match is final for that run: re-screen to revisit it.

The company's SANCTIONS check
-----------------------------
The company's standing is the worst outcome among its subjects' latest runs in the
current cycle (``domain/sanctions.py``). Whenever it changes, a new SANCTIONS
verification result is written for the company through the verification service — so
the Clear rule and the handover guard read sanctions exactly as before. A REVIEW
result this service wrote earlier is concluded with a review (ACCEPTED when the
standing became PASSED, REJECTED when FAILED), so it does not hold the Clear back.

A proposed or confirmed true match also **flags** the company: the header says so and
its deals cannot be handed over while the proposal is open.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

import structlog
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.application.compliance_settings import true_match_approval
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain import sanctions as rules
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationReviewStatus,
    VerificationType,
)
from app.modules.onboarding.domain.entities.sanctions import (
    SanctionsDisposition,
    SanctionsHit,
    SanctionsList,
    SanctionsRun,
    SanctionsRunList,
)
from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.modules.onboarding.domain.entities.verification_result import (
    VerificationResult,
    about_company,
)
from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    SanctionsHitNotFoundError,
    SanctionsRunNotFoundError,
    SanctionsTrueMatchRefusedError,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import in_cycle
from app.shared import clock
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The prefix of the `provider_reference` on every SANCTIONS result this service writes.
RESULT_REFERENCE = "sanctions-screening:"


@dataclass(frozen=True)
class HitInput:
    list_code: str
    matched_name: str
    list_entry_id: str | None = None
    score: Decimal | None = None
    disposition: str = rules.OPEN
    reason: str | None = None


@dataclass(frozen=True)
class Actor:
    id: str
    name: str | None
    permissions: frozenset[str]


@dataclass(frozen=True)
class HitView:
    hit: SanctionsHit
    current: SanctionsDisposition
    decisions: list[SanctionsDisposition]


@dataclass(frozen=True)
class RunView:
    run: SanctionsRun
    lists: list[SanctionsRunList]
    hits: list[HitView]
    outcome: str


@dataclass(frozen=True)
class SubjectCoverage:
    subject_type: str
    subject_name: str
    subject_reference: uuid.UUID | None
    latest: RunView | None
    #: Why this subject needs screening again (empty when it does not).
    rescreen_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompanySanctions:
    company_id: uuid.UUID
    standing: str | None
    #: A true match is proposed or confirmed on one of the latest runs.
    flagged: bool
    subjects: list[SubjectCoverage]


@dataclass(frozen=True)
class RescreenDue:
    company_id: uuid.UUID
    company_name: str | None
    reasons: list[str]


@dataclass(frozen=True)
class PendingTrueMatch:
    company_id: uuid.UUID
    company_name: str | None
    run: SanctionsRun
    hit: SanctionsHit
    proposal: SanctionsDisposition


def actor_from(user: object, permissions: Collection[tuple[str, str]]) -> Actor:
    return Actor(
        id=str(user.id),  # type: ignore[attr-defined]
        name=getattr(user, "full_name", None) or getattr(user, "email", None),
        permissions=frozenset(f"{module}:{action}" for module, action in permissions),
    )


def _subject_key(subject_type: str, reference: uuid.UUID | None, name: str) -> tuple:
    """One subject: the company (whatever it was called when screened), a beneficial
    owner by record, or a director by name."""
    if subject_type == "COMPANY":
        return ("COMPANY",)
    return (subject_type, str(reference) if reference else " ".join(name.lower().split()))


def _run_in_cycle(run: SanctionsRun, cycle: CheckCycle | None) -> bool:
    """``in_cycle``'s rule in Python, for runs already read: a NULL cycle is cycle 1."""
    if cycle is None:
        return True
    if cycle.number == 1:
        return run.cycle_id in (cycle.id, None)
    return run.cycle_id == cycle.id


def _latest_by_subject(runs: Iterable[SanctionsRun]) -> dict[tuple, SanctionsRun]:
    """Each subject's first run in ``runs`` (newest first)."""
    latest: dict[tuple, SanctionsRun] = {}
    for run in runs:
        latest.setdefault(_subject_key(run.subject_type, run.subject_reference, run.subject_name), run)
    return latest


def _run_reasons(
    run: SanctionsRun,
    lists: Iterable[SanctionsRunList],
    current_lists: list[SanctionsList],
    *,
    current_name: str | None = None,
) -> list[str]:
    """Why a subject's latest run is out of date: a list it missed or an older version
    of one, or the company's name changed since."""
    covered = {row.code: row.list_version_date for row in lists}
    reasons = []
    for listed in current_lists:
        used = covered.get(listed.code)
        if used is None and listed.mandatory:
            reasons.append(f"not screened against {listed.name}")
        elif used is not None and used < listed.list_version_date:
            reasons.append(
                f"{listed.name} has a newer version ({listed.list_version_date.isoformat()})"
            )
    searched = str(run.search_terms.get("name") or run.subject_name)
    if current_name and " ".join(searched.lower().split()) != " ".join(
        current_name.lower().split()
    ):
        reasons.append(f"the company's name changed (screened as {searched})")
    return reasons


class SanctionsScreeningService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    # ── Record a run ─────────────────────────────────────────────────────────

    async def record_run(
        self,
        company_id: uuid.UUID,
        *,
        subject_type: str,
        subject_name: str | None,
        subject_reference: uuid.UUID | None,
        list_codes: Iterable[str],
        hits: Iterable[HitInput],
        search_terms: Mapping[str, object] | None,
        provider: str,
        provider_reference: str | None,
        note: str | None,
        actor: Actor,
    ) -> RunView:
        company = await self._db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        if company is None:
            raise ExporterProfileNotFoundError(company_id)
        name = await self._subject_name(company, subject_type, subject_name, subject_reference)

        current_lists = {row.code: row for row in await self._current_lists()}
        wanted = {code.strip().upper() for code in list_codes}
        unknown = sorted(code for code in wanted if code not in current_lists or not current_lists[code].active)
        if unknown:
            raise ValidationError(f"Not an active sanctions list: {', '.join(unknown)}")
        missing = sorted(
            row.name
            for code, row in current_lists.items()
            if row.active and row.mandatory and code not in wanted
        )
        if missing:
            raise ValidationError(
                "A screening must cover every mandatory list; missing: " + ", ".join(missing)
            )
        hit_inputs = list(hits)
        for hit in hit_inputs:
            if hit.list_code.strip().upper() not in wanted:
                raise ValidationError(f"A hit on {hit.list_code} names a list this run did not cover")
            self._check_disposition(hit.disposition, hit.reason)

        now = clock.now()
        run = SanctionsRun(
            company_id=company_id,
            subject_type=subject_type,
            subject_name=name,
            subject_reference=subject_reference,
            cycle_id=await self._current_cycle_id(company_id),
            performed_by=actor.id,
            performed_at=now,
            provider=provider or "MANUAL",
            provider_reference=provider_reference,
            search_terms=dict(search_terms or {"name": name}),
            note=(note or "").strip() or None,
        )
        self._db.add(run)
        await self._db.flush()
        for code in sorted(wanted):
            listed = current_lists[code]
            self._db.add(
                SanctionsRunList(
                    run_id=run.id,
                    list_id=listed.id,
                    code=code,
                    list_version_date=listed.list_version_date,
                )
            )
        mode = true_match_approval()
        for hit_input in hit_inputs:
            hit = SanctionsHit(
                run_id=run.id,
                list_code=hit_input.list_code.strip().upper(),
                matched_name=hit_input.matched_name.strip(),
                list_entry_id=(hit_input.list_entry_id or "").strip() or None,
                score=hit_input.score,
            )
            self._db.add(hit)
            await self._db.flush()
            self._db.add(
                SanctionsDisposition(
                    hit_id=hit.id,
                    disposition=self._as_recorded(hit_input.disposition, mode),
                    reason=(hit_input.reason or "").strip() or None,
                    decided_by=actor.id,
                    decided_at=now,
                    approved_by=actor.id
                    if hit_input.disposition == rules.TRUE_MATCH and mode is rules.TrueMatchApproval.SINGLE
                    else None,
                )
            )
        await self._db.flush()
        view = await self.run_view(run.id)
        await self._history.record(
            company_id,
            dimension=history_dimensions.SANCTIONS,
            event_type="sanctions_run_recorded",
            to_value=view.outcome,
            actor_id=actor.id,
            source="sanctions_screening_service.record_run",
            details={
                "run_id": str(run.id),
                "subject_type": subject_type,
                "subject_name": name,
                "lists": [f"{row.code} ({row.list_version_date.isoformat()})" for row in view.lists],
                "hits": len(view.hits),
            },
        )
        await self._audit("crm.sanctions.run_recorded", run, actor, {"outcome": view.outcome})
        await self._db.commit()
        await self._sync_company_result(company_id, actor)
        logger.info(
            "sanctions.run_recorded",
            company_id=str(company_id),
            run_id=str(run.id),
            outcome=view.outcome,
        )
        return await self.run_view(run.id)

    # ── Decide a hit ─────────────────────────────────────────────────────────

    async def decide(
        self, hit_id: uuid.UUID, *, disposition: str, reason: str | None, actor: Actor
    ) -> RunView:
        hit, run, current = await self._locked_hit(hit_id)
        self._check_disposition(disposition, reason)
        if current.disposition == rules.TRUE_MATCH:
            raise ValidationError("A confirmed true match is final; record a new screening instead")
        if current.disposition == rules.TRUE_MATCH_PROPOSED:
            raise ValidationError("This true match is awaiting confirmation; confirm or reject it")
        mode = true_match_approval()
        recorded = self._as_recorded(disposition, mode)
        if recorded == current.disposition and recorded != rules.OPEN:
            raise ValidationError("That is already the decision on this match")
        row = SanctionsDisposition(
            hit_id=hit.id,
            disposition=recorded,
            reason=(reason or "").strip() or None,
            decided_by=actor.id,
            decided_at=clock.now(),
            approved_by=actor.id if recorded == rules.TRUE_MATCH else None,
            supersedes_id=current.id,
        )
        return await self._write_decision(run, hit, row, actor, "sanctions_hit_decided")

    async def confirm_true_match(self, hit_id: uuid.UUID, *, actor: Actor) -> RunView:
        hit, run, current = await self._locked_hit(hit_id)
        if current.disposition != rules.TRUE_MATCH_PROPOSED:
            raise ValidationError("There is no proposed true match on this hit to confirm")
        refusal = rules.true_match_refusal(
            true_match_approval(),
            proposer_id=current.decided_by,
            approver_id=actor.id,
            approver_permissions=actor.permissions,
        )
        if refusal is not None:
            raise SanctionsTrueMatchRefusedError(refusal)
        row = SanctionsDisposition(
            hit_id=hit.id,
            disposition=rules.TRUE_MATCH,
            reason=current.reason,
            decided_by=current.decided_by,
            decided_at=clock.now(),
            approved_by=actor.id,
            supersedes_id=current.id,
        )
        return await self._write_decision(run, hit, row, actor, "sanctions_true_match_confirmed")

    async def reject_true_match(self, hit_id: uuid.UUID, *, reason: str, actor: Actor) -> RunView:
        hit, run, current = await self._locked_hit(hit_id)
        if current.disposition != rules.TRUE_MATCH_PROPOSED:
            raise ValidationError("There is no proposed true match on this hit to reject")
        refusal = rules.true_match_refusal(
            true_match_approval(),
            proposer_id=current.decided_by,
            approver_id=actor.id,
            approver_permissions=actor.permissions,
        )
        if refusal is not None:
            raise SanctionsTrueMatchRefusedError(refusal)
        if not (reason or "").strip():
            raise ValidationError("Say why the true match is not confirmed")
        row = SanctionsDisposition(
            hit_id=hit.id,
            disposition=rules.OPEN,
            reason=f"True match not confirmed: {reason.strip()}",
            decided_by=actor.id,
            decided_at=clock.now(),
            supersedes_id=current.id,
        )
        return await self._write_decision(run, hit, row, actor, "sanctions_true_match_rejected")

    # ── Reads ────────────────────────────────────────────────────────────────

    async def run_view(self, run_id: uuid.UUID) -> RunView:
        run = await self._db.get(SanctionsRun, run_id)
        if run is None:
            raise SanctionsRunNotFoundError(run_id)
        return (await self._views([run]))[0]

    async def runs_for(self, company_id: uuid.UUID) -> list[RunView]:
        runs = list(
            await self._db.scalars(
                select(SanctionsRun)
                .where(SanctionsRun.company_id == company_id)
                .order_by(SanctionsRun.performed_at.desc(), SanctionsRun.created_at.desc())
            )
        )
        return await self._views(runs)

    async def company(self, company_id: uuid.UUID) -> CompanySanctions:
        """Every subject with its latest run in the current cycle, what needs
        re-screening, the standing and whether the company is flagged.

        The standing and the coverage are the current cycle's: a new cycle screens
        afresh. The **flag** is not: it reads each subject's latest run in any cycle, so
        a true match proposed or confirmed before a re-check started keeps the company
        flagged — and its deals held — until that subject is screened again."""
        company = await self._db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        if company is None:
            raise ExporterProfileNotFoundError(company_id)
        cycle = await self._current_cycle(company_id)
        every_run = list(
            await self._db.scalars(
                select(SanctionsRun)
                .where(SanctionsRun.company_id == company_id)
                .order_by(SanctionsRun.performed_at.desc(), SanctionsRun.created_at.desc())
            )
        )
        latest = _latest_by_subject(run for run in every_run if _run_in_cycle(run, cycle))
        latest_ever = _latest_by_subject(every_run)
        all_views = {
            view.run.id: view
            for view in await self._views(
                list({run.id: run for run in [*latest.values(), *latest_ever.values()]}.values())
            )
        }
        views = {key: all_views[run.id] for key, run in latest.items()}

        subjects: list[SubjectCoverage] = []
        current_lists = [row for row in await self._current_lists() if row.active]
        company_key = _subject_key("COMPANY", None, "")
        company_view = views.get(company_key)
        subjects.append(
            SubjectCoverage(
                "COMPANY",
                company.name or "",
                None,
                company_view,
                self._reasons(company_view, current_lists, current_name=company.name),
            )
        )
        seen = {company_key}
        for ubo in await self._ubos_of(company_id):
            key = _subject_key("UBO", ubo.id, "")
            seen.add(key)
            view = views.get(key)
            subjects.append(
                SubjectCoverage(
                    "UBO",
                    f"{ubo.first_name} {ubo.last_name}".strip(),
                    ubo.id,
                    view,
                    self._reasons(view, current_lists),
                )
            )
        for key, view in views.items():
            if key in seen:
                continue
            subjects.append(
                SubjectCoverage(
                    view.run.subject_type,
                    view.run.subject_name,
                    view.run.subject_reference,
                    view,
                    self._reasons(view, current_lists),
                )
            )

        outcomes = {str(key): view.outcome for key, view in views.items()}
        flagged = any(
            hit.current.disposition in rules.FLAGGING
            for run in latest_ever.values()
            for hit in all_views[run.id].hits
        )
        return CompanySanctions(
            company_id=company_id,
            standing=rules.company_standing(outcomes, company_screened=company_view is not None),
            flagged=flagged,
            subjects=subjects,
        )

    async def rescreen_due(self, *, limit: int = 200) -> list[RescreenDue]:
        """Companies screened before whose latest screening is now out of date: a list
        has a newer version or became mandatory, the company's name changed, or a
        beneficial owner has never been screened.

        A fixed number of reads, whatever the number of companies: every run, cycle,
        list version and beneficial owner is read once, and the same subjects and
        reasons as :meth:`company` are worked out from them."""
        runs = list(
            await self._db.scalars(
                select(SanctionsRun).order_by(
                    SanctionsRun.performed_at.desc(), SanctionsRun.created_at.desc()
                )
            )
        )
        if not runs:
            return []
        company_ids = {run.company_id for run in runs}
        cycles: dict[uuid.UUID, CheckCycle] = {}
        for cycle in await self._db.scalars(
            select(CheckCycle)
            .where(CheckCycle.company_id.in_(company_ids))
            .order_by(CheckCycle.number.desc())
        ):
            cycles.setdefault(cycle.company_id, cycle)
        by_company: dict[uuid.UUID, list[SanctionsRun]] = defaultdict(list)
        for run in runs:
            if _run_in_cycle(run, cycles.get(run.company_id)):
                by_company[run.company_id].append(run)
        latest = {company_id: _latest_by_subject(rows) for company_id, rows in by_company.items()}
        run_lists: dict[uuid.UUID, list[SanctionsRunList]] = defaultdict(list)
        latest_ids = [run.id for subjects in latest.values() for run in subjects.values()]
        if latest_ids:
            for row in await self._db.scalars(
                select(SanctionsRunList)
                .where(SanctionsRunList.run_id.in_(latest_ids))
                .order_by(SanctionsRunList.code)
            ):
                run_lists[row.run_id].append(row)
        names = dict(
            (
                await self._db.execute(
                    select(ExporterProfile.customer_id, ExporterProfile.name).where(
                        ExporterProfile.customer_id.in_(company_ids)
                    )
                )
            ).all()
        )
        ubos: dict[uuid.UUID, list[UboRecord]] = defaultdict(list)
        for ubo, owner in await self._db.execute(
            select(UboRecord, OnboardingRequest.customer_id)
            .join(OnboardingRequest, OnboardingRequest.id == UboRecord.onboarding_request_id)
            .where(OnboardingRequest.customer_id.in_(company_ids))
            .order_by(UboRecord.last_name, UboRecord.first_name)
        ):
            ubos[owner].append(ubo)
        current_lists = [row for row in await self._current_lists() if row.active]

        def reasons_for(run: SanctionsRun | None, *, current_name: str | None = None):
            if run is None:
                return ["never screened"]
            return _run_reasons(run, run_lists[run.id], current_lists, current_name=current_name)

        due: list[RescreenDue] = []
        for company_id in company_ids:
            if company_id not in names:
                continue
            subjects = latest.get(company_id, {})
            name = names[company_id]
            company_key = _subject_key("COMPANY", None, "")
            found = [
                (name or "", reasons_for(subjects.get(company_key), current_name=name))
            ]
            seen = {company_key}
            for ubo in ubos[company_id]:
                key = _subject_key("UBO", ubo.id, "")
                seen.add(key)
                found.append(
                    (f"{ubo.first_name} {ubo.last_name}".strip(), reasons_for(subjects.get(key)))
                )
            for key, run in subjects.items():
                if key not in seen:
                    found.append((run.subject_name, reasons_for(run)))
            reasons = [
                f"{subject or 'The company'}: {reason}"
                for subject, subject_reasons in found
                for reason in subject_reasons
            ]
            if reasons:
                due.append(RescreenDue(company_id, name, reasons))
        due.sort(key=lambda row: (row.company_name or "").lower())
        return due[:limit]

    async def pending_true_matches(self) -> list[PendingTrueMatch]:
        """Every proposed true match awaiting confirmation, oldest first."""
        later = aliased(SanctionsDisposition)
        rows = await self._db.execute(
            select(SanctionsDisposition, SanctionsHit, SanctionsRun, ExporterProfile.name)
            .join(SanctionsHit, SanctionsHit.id == SanctionsDisposition.hit_id)
            .join(SanctionsRun, SanctionsRun.id == SanctionsHit.run_id)
            .join(ExporterProfile, ExporterProfile.customer_id == SanctionsRun.company_id)
            .where(
                SanctionsDisposition.disposition == rules.TRUE_MATCH_PROPOSED,
                ~exists().where(later.supersedes_id == SanctionsDisposition.id),
            )
            .order_by(SanctionsDisposition.decided_at)
        )
        return [
            PendingTrueMatch(run.company_id, name, run, hit, proposal)
            for proposal, hit, run, name in rows
        ]

    async def is_flagged(self, company_id: uuid.UUID) -> bool:
        """Whether a true match is proposed or confirmed on a subject's latest run, in
        whichever cycle that run was."""
        return (await self.company(company_id)).flagged

    # ── Internals ────────────────────────────────────────────────────────────

    def _reasons(
        self,
        view: RunView | None,
        current_lists: list[SanctionsList],
        *,
        current_name: str | None = None,
    ) -> list[str]:
        if view is None:
            return ["never screened"]
        return _run_reasons(view.run, view.lists, current_lists, current_name=current_name)

    async def _write_decision(
        self,
        run: SanctionsRun,
        hit: SanctionsHit,
        row: SanctionsDisposition,
        actor: Actor,
        event: str,
    ) -> RunView:
        self._db.add(row)
        await self._db.flush()
        view = await self.run_view(run.id)
        await self._history.record(
            run.company_id,
            dimension=history_dimensions.SANCTIONS,
            event_type=event,
            to_value=row.disposition,
            reason=row.reason,
            actor_id=actor.id,
            source="sanctions_screening_service",
            details={
                "run_id": str(run.id),
                "hit_id": str(hit.id),
                "matched_name": hit.matched_name,
                "list_code": hit.list_code,
                "subject_name": run.subject_name,
                "run_outcome": view.outcome,
            },
        )
        await self._audit(
            f"crm.sanctions.{event.removeprefix('sanctions_')}",
            run,
            actor,
            {"hit_id": str(hit.id), "disposition": row.disposition, "reason": row.reason},
        )
        await self._db.commit()
        await self._sync_company_result(run.company_id, actor)
        return await self.run_view(run.id)

    async def _views(self, runs: list[SanctionsRun]) -> list[RunView]:
        if not runs:
            return []
        ids = [run.id for run in runs]
        lists: dict[uuid.UUID, list[SanctionsRunList]] = defaultdict(list)
        for row in await self._db.scalars(
            select(SanctionsRunList).where(SanctionsRunList.run_id.in_(ids)).order_by(SanctionsRunList.code)
        ):
            lists[row.run_id].append(row)
        hits: dict[uuid.UUID, list[SanctionsHit]] = defaultdict(list)
        all_hits = list(
            await self._db.scalars(
                select(SanctionsHit).where(SanctionsHit.run_id.in_(ids)).order_by(SanctionsHit.created_at)
            )
        )
        for hit in all_hits:
            hits[hit.run_id].append(hit)
        decisions: dict[uuid.UUID, list[SanctionsDisposition]] = defaultdict(list)
        if all_hits:
            for row in await self._db.scalars(
                select(SanctionsDisposition)
                .where(SanctionsDisposition.hit_id.in_([h.id for h in all_hits]))
                .order_by(SanctionsDisposition.decided_at, SanctionsDisposition.created_at)
            ):
                decisions[row.hit_id].append(row)
        views = []
        for run in runs:
            hit_views = []
            for hit in hits[run.id]:
                chain = decisions[hit.id]
                superseded = {row.supersedes_id for row in chain if row.supersedes_id}
                current = next(row for row in reversed(chain) if row.id not in superseded)
                hit_views.append(HitView(hit, current, chain))
            views.append(
                RunView(
                    run,
                    lists[run.id],
                    hit_views,
                    rules.run_outcome(h.current.disposition for h in hit_views),
                )
            )
        return views

    async def _locked_hit(
        self, hit_id: uuid.UUID
    ) -> tuple[SanctionsHit, SanctionsRun, SanctionsDisposition]:
        hit = await self._db.get(SanctionsHit, hit_id)
        if hit is None:
            raise SanctionsHitNotFoundError(hit_id)
        run = await self._db.get(SanctionsRun, hit.run_id)
        # The company row serialises decisions on its screenings.
        await self._db.scalar(
            select(ExporterProfile.customer_id)
            .where(ExporterProfile.customer_id == run.company_id)
            .with_for_update()
        )
        chain = list(
            await self._db.scalars(
                select(SanctionsDisposition).where(SanctionsDisposition.hit_id == hit_id)
            )
        )
        superseded = {row.supersedes_id for row in chain if row.supersedes_id}
        current = next(row for row in chain if row.id not in superseded)
        return hit, run, current

    @staticmethod
    def _check_disposition(disposition: str, reason: str | None) -> None:
        if disposition not in rules.RECORDABLE:
            raise ValidationError(f"Unknown decision {disposition!r}")
        if disposition != rules.OPEN and not (reason or "").strip():
            raise ValidationError("Say why: a decision on a possible match needs a reason")

    @staticmethod
    def _as_recorded(disposition: str, mode: rules.TrueMatchApproval) -> str:
        if disposition == rules.TRUE_MATCH and mode is not rules.TrueMatchApproval.SINGLE:
            return rules.TRUE_MATCH_PROPOSED
        return disposition

    async def _subject_name(
        self,
        company: ExporterProfile,
        subject_type: str,
        subject_name: str | None,
        subject_reference: uuid.UUID | None,
    ) -> str:
        name = (subject_name or "").strip()
        if subject_type == "COMPANY":
            return name or (company.name or "")
        if subject_type == "UBO":
            if subject_reference is None:
                raise ValidationError("Choose which beneficial owner was screened")
            ubo = next((u for u in await self._ubos_of(company.customer_id) if u.id == subject_reference), None)
            if ubo is None:
                raise ValidationError("That beneficial owner is not recorded for this company")
            return name or f"{ubo.first_name} {ubo.last_name}".strip()
        if subject_type == "DIRECTOR":
            if not name:
                raise ValidationError("Give the director's name")
            return name
        raise ValidationError(f"Unknown subject {subject_type!r}")

    async def _ubos_of(self, company_id: uuid.UUID) -> list[UboRecord]:
        return list(
            await self._db.scalars(
                select(UboRecord)
                .join(OnboardingRequest, OnboardingRequest.id == UboRecord.onboarding_request_id)
                .where(OnboardingRequest.customer_id == company_id)
                .order_by(UboRecord.last_name, UboRecord.first_name)
            )
        )

    async def _current_lists(self) -> list[SanctionsList]:
        return list(
            await self._db.scalars(select(SanctionsList).where(SanctionsList.is_current.is_(True)))
        )

    async def _current_cycle(self, company_id: uuid.UUID) -> CheckCycle | None:
        return await self._db.scalar(
            select(CheckCycle)
            .where(CheckCycle.company_id == company_id)
            .order_by(CheckCycle.number.desc())
            .limit(1)
        )

    async def _current_cycle_id(self, company_id: uuid.UUID) -> uuid.UUID | None:
        cycle = await self._current_cycle(company_id)
        return cycle.id if cycle is not None else None

    async def _audit(
        self, event: str, run: SanctionsRun, actor: Actor, extra: Mapping[str, object]
    ) -> None:
        await AuditService(self._db).record(
            event,
            actor_id=uuid.UUID(actor.id),
            actor_type=ActorType.COMPLIANCE_OFFICER,
            payload={
                "subject_type": "sanctions_run",
                "subject_id": str(run.id),
                "company_id": str(run.company_id),
                "screened_subject": run.subject_name,
                "actor_name": actor.name,
                **extra,
            },
        )

    async def _sync_company_result(self, company_id: uuid.UUID, actor: Actor) -> None:
        """Write a SANCTIONS result for the company when its standing changed, and
        conclude a REVIEW result this service wrote before."""
        from app.modules.onboarding.application.verification_service import VerificationService

        standing = (await self.company(company_id)).standing
        if standing is None:
            return
        cycle = await self._current_cycle(company_id)
        latest = await self._db.scalar(
            select(VerificationResult)
            .where(
                about_company(company_id),
                VerificationResult.verification_type == VerificationType.SANCTIONS,
                VerificationResult.provider_reference.like(f"{RESULT_REFERENCE}%"),
                in_cycle(VerificationResult.cycle_id, cycle),
            )
            .order_by(VerificationResult.performed_at.desc(), VerificationResult.created_at.desc())
            .limit(1)
        )
        reviewed = latest is not None and bool(
            await self._db.scalar(
                select(exists().where(VerificationReview.verification_result_id == latest.id))
            )
        )
        if latest is not None and latest.status.value == standing and not reviewed:
            return
        service = VerificationService(self._db)
        if (
            latest is not None
            and latest.status is VerificationResultStatus.REVIEW
            and not reviewed
            and standing != rules.REVIEW
        ):
            await service.record_review(
                latest.id,
                reviewed_by=actor.id,
                review_status=(
                    VerificationReviewStatus.ACCEPTED
                    if standing == rules.PASSED
                    else VerificationReviewStatus.REJECTED
                ),
                note="Concluded by the sanctions screening",
            )
        summary = await self._summary(company_id)
        await service.trigger_verification(
            VerificationType.SANCTIONS,
            VerificationEntityType.EXPORTER,
            company_id,
            provider="manual",
            payload={
                "status": standing,
                "provider_reference": f"{RESULT_REFERENCE}{company_id}:{clock.now().isoformat()}",
                "normalized_result": {"source": "sanctions_screening", "subjects": summary},
            },
            actor_id=actor.id,
            evidence=VerificationEvidence(
                note="Structured sanctions screening: "
                + "; ".join(f"{s['name']} {s['outcome']} ({', '.join(s['lists'])})" for s in summary)
            ),
        )

    async def _summary(self, company_id: uuid.UUID) -> list[dict]:
        return [
            {
                "subject_type": subject.subject_type,
                "name": subject.subject_name,
                "outcome": subject.latest.outcome,
                "run_id": str(subject.latest.run.id),
                "lists": [f"{row.code} {row.list_version_date.isoformat()}" for row in subject.latest.lists],
            }
            for subject in (await self.company(company_id)).subjects
            if subject.latest is not None
        ]


__all__ = [
    "Actor",
    "CompanySanctions",
    "HitInput",
    "PendingTrueMatch",
    "RescreenDue",
    "RunView",
    "SanctionsScreeningService",
    "SubjectCoverage",
    "actor_from",
]
