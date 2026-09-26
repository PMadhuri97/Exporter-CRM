"""``QualificationService`` — criteria, results, outcomes and re-review
(L2-09, L2-10). **Owner: Developer 2.**

Qualification answers *did this company meet our requirements?* It is its own
gauge (``docs/contracts/criterion-result.md``), with nothing borrowed from the
screening checklist, the background check or ``verification_result``.

**Criteria are settings.** Each change an ADMIN makes adds the next version of
the criterion as a new, immutable row; the old version is never touched, so a
result keeps meaning exactly what it meant when it was recorded.

**Results are evidence; the outcome is a decision.** Recording results never
moves the gauge. The server works out a *suggestion* from them — ``QUALIFIED``
when every active, required criterion's latest result is ``PASS`` against its
current version — but a person records the outcome, which may differ from the
suggestion. Both are stored, side by side, on the outcome.

**One transaction per operation.** Every write here goes through the session
the service was given; the shared ``HistoryService`` flushes and never
commits; each public method commits once at its end. Recording an outcome
locks the company row first, so two reviewers cannot fork the outcome chain.
Nothing here crosses into another developer's service, so decision U4 does not
arise.

**The journey.** A ``QUALIFIED`` outcome on a ``LEAD`` moves the journey to
``PROSPECT`` in the same transaction. It never makes a company a ``CUSTOMER``:
that needs a ``CLEAR`` background check, which is L2-11's hand-off with
Developer 4.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.company_intake import PartnerQualification
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    LIFECYCLE_TRANSITION_EVENT,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification import (
    QualificationCriterion,
    QualificationOutcome,
    QualificationReasonCode,
    QualificationResult,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
    QualificationState,
)
from app.modules.onboarding.domain.qualification_views import (
    CriterionDefinition,
    CriterionStanding,
    QualificationView,
    ResultEntry,
)
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    QualificationClosedError,
    QualificationCriterionExistsError,
    QualificationCriterionNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories.qualification_repository import (
    QualificationRepository,
)
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: History dimensions and event types (history contract §2; criterion-result
#: contract §6).
HISTORY_DIMENSION_QUALIFICATION = "qualification"
HISTORY_DIMENSION_JOURNEY = "journey"
QUALIFICATION_RESULT_EVENT = "qualification_result"
#: The journey keeps the event type its rows have always had (history
#: contract §3).
JOURNEY_TRANSITION_EVENT = LIFECYCLE_TRANSITION_EVENT

#: `partner_reference` is a partner's own reference for its evidence; only the
#: platform's partner intake uses it — the API accepts the other three.
_EVIDENCE_TYPES = frozenset({"document", "verification_result", "url", "partner_reference"})


class QualificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = QualificationRepository(db)
        self._history = HistoryService(db)

    # ── Criteria (ADMIN) ────────────────────────────────────────────────────

    async def list_criteria(self) -> list[QualificationCriterion]:
        """The current version of every criterion, active or not."""
        return await self._repo.current_criteria()

    async def list_versions(self, key: str) -> list[QualificationCriterion]:
        versions = await self._repo.versions(key)
        if not versions:
            raise QualificationCriterionNotFoundError(key)
        return versions

    async def create_criterion(
        self, key: str, definition: CriterionDefinition, *, actor_id: str | None
    ) -> QualificationCriterion:
        """Add a new criterion as version 1."""
        key = _check_key(key)
        _check_definition(definition)
        if await self._repo.latest_version(key) is not None:
            raise QualificationCriterionExistsError(key)
        criterion = _criterion_row(key, 1, definition, actor_id)
        await self._repo.add(criterion)
        await self._db.commit()
        logger.info("qualification.criterion.created", key=key, actor_id=actor_id)
        return criterion

    async def add_version(
        self, key: str, definition: CriterionDefinition, *, actor_id: str | None
    ) -> QualificationCriterion:
        """Change a criterion by adding its next version. The previous
        versions stay exactly as they were, and results recorded against them
        keep pointing at them. Deactivating is a version with `active=False`."""
        _check_definition(definition)
        latest = await self._repo.latest_version(key)
        if latest is None:
            raise QualificationCriterionNotFoundError(key)
        criterion = _criterion_row(key, latest.version + 1, definition, actor_id)
        await self._repo.add(criterion)
        await self._db.commit()
        logger.info(
            "qualification.criterion.versioned",
            key=key,
            version=criterion.version,
            actor_id=actor_id,
        )
        return criterion

    async def list_reason_codes(self) -> list[QualificationReasonCode]:
        return await self._repo.reason_codes()

    # ── Results ─────────────────────────────────────────────────────────────

    async def record_results(
        self,
        customer_id: uuid.UUID,
        entries: Sequence[ResultEntry],
        *,
        actor_id: str | None,
        source: QualificationSource = QualificationSource.MANUAL,
        decided_by_kind: DecidedByKind = DecidedByKind.MANUAL,
    ) -> list[QualificationResult]:
        """Record one or more criterion results for a company, all or none.

        Each result is pinned to its criterion's **current** version, which
        must be active. `PASS` and `FAIL` need evidence (a note or at least
        one reference). A confidence is only for an automated result, between
        0 and 1. Results never move the gauge.

        `source` and `decided_by_kind` are for the platform's own callers
        (import, RXIL, automation). The API never lets a caller choose them:
        a result entered through it is always `MANUAL`, by a person.

        Each result writes one `qualification` history row
        (`event_type = "qualification_result"`), committed with it.
        """
        profile = await self._lock_profile(customer_id)
        if profile.qualification is QualificationState.QUALIFIED:
            raise QualificationClosedError(customer_id)
        rows = await self._write_results(
            customer_id, entries, actor_id=actor_id, source=source, decided_by_kind=decided_by_kind
        )
        await self._db.commit()
        logger.info(
            "qualification.results.recorded",
            customer_id=str(customer_id),
            keys=[entry.criterion_key for entry in entries],
            actor_id=actor_id,
        )
        return rows

    # ── Outcome ─────────────────────────────────────────────────────────────

    async def record_outcome(
        self,
        customer_id: uuid.UUID,
        outcome: QualificationOutcomeValue,
        *,
        reason_codes: Sequence[str] = (),
        note: str | None = None,
        actor_id: str | None,
        source: QualificationSource = QualificationSource.MANUAL,
        decided_by_kind: DecidedByKind = DecidedByKind.MANUAL,
    ) -> QualificationOutcome:
        """Record a reviewer's decision, and move the gauge — and, for a
        `QUALIFIED` lead, the journey — to match. All in one transaction.

        Allowed from `NOT_YET_REVIEWED` and, as a re-review, from
        `NOT_QUALIFIED`; `QUALIFIED` is final (assumption A2). A re-review is a
        new outcome that supersedes the previous one; the previous one, and
        every result, stay exactly as they were.

        `NOT_QUALIFIED` needs at least one reason code; a code marked
        `requires_note` (`other`) needs a note. Every code must be a known,
        active one.

        The outcome stores what the server suggested at that moment
        (`suggested_outcome`) and which results it rested on (`result_ids`),
        so the person's decision and the evidence-based suggestion stay
        distinguishable afterwards — including when they differ.

        Writes a `qualification` history row (from the previous gauge value
        to the outcome, with the note as its reason) and, when the journey
        moves, a `journey` history row. Never makes a company a `CUSTOMER`.
        """
        profile = await self._lock_profile(customer_id)
        if profile.qualification is QualificationState.QUALIFIED:
            raise QualificationClosedError(customer_id)
        codes = list(dict.fromkeys(code.strip() for code in reason_codes if code.strip()))
        cleaned_note = _clean(note)
        await self._check_reason_codes(outcome, codes, cleaned_note)
        suggested, result_ids = await self._suggestion(customer_id)

        row = await self._write_outcome(
            profile,
            outcome,
            reason_codes=codes,
            note=cleaned_note,
            suggested=suggested,
            result_ids=result_ids,
            source=source,
            decided_by_kind=decided_by_kind,
            decided_by=actor_id,
            actor_id=actor_id,
        )
        await self._db.commit()
        await self._db.refresh(row)
        return row

    # ── A partner's decision (RXIL intake) ──────────────────────────────────

    async def record_partner_decision(
        self,
        customer_id: uuid.UUID,
        qualification: PartnerQualification,
        *,
        source: QualificationSource,
        actor_id: str | None,
        partner_reference: str | None = None,
    ) -> QualificationOutcome:
        """Record a partner's qualification exactly as it was handed over:
        its criterion results and its outcome, in one transaction.

        **Nothing is recomputed.** The partner's results are stored as given —
        each with `source` set to the partner and the partner's own
        `decided_by_kind`, evidence, reason and confidence — and the outcome
        is the partner's outcome. The CRM's criteria are not evaluated: the
        outcome's `suggested_outcome` is the partner's own decision and its
        `result_ids` are the partner's results, not a local suggestion. The
        same tables, rules and history rows as a local review are used; this
        is not a second qualification model.

        `decided_by` is empty (the partner decided, not a user); `actor_id`,
        the signed-in user who submitted the delivery, is recorded as
        `recorded_by` on the results and as the actor on the history rows.

        Only a `QUALIFIED` outcome is accepted: a partner hands over exporters
        it has already filtered in (architecture decision 7). Refused, like any
        outcome, on a company already `QUALIFIED`.
        """
        _check_partner_outcome(qualification, source)
        profile = await self._lock_profile(customer_id)
        if profile.qualification is QualificationState.QUALIFIED:
            raise QualificationClosedError(customer_id)

        rows = await self._write_results(
            customer_id,
            qualification.results,
            actor_id=actor_id,
            source=source,
            decided_by_kind=qualification.decided_by_kind,
        ) if qualification.results else []
        row = await self._write_outcome(
            profile,
            qualification.outcome,
            reason_codes=[],
            note=_clean(qualification.note),
            suggested=qualification.outcome,
            result_ids=[r.id for r in rows],
            source=source,
            decided_by_kind=qualification.decided_by_kind,
            decided_by=None,
            actor_id=actor_id,
            extra_details={"partner_reference": partner_reference},
        )
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def check_partner_decision(
        self, qualification: PartnerQualification, *, source: QualificationSource
    ) -> None:
        """Refuse a partner's decision exactly as `record_partner_decision`
        would, without writing anything.

        Partner intake creates a new company in its own commit before it
        records the decision; checking first means a decision that would be
        refused never leaves that company behind as a bare `LEAD`. The one
        thing this cannot check is the company itself (already `QUALIFIED`),
        because the company may not exist yet.
        """
        _check_partner_outcome(qualification, source)
        if qualification.results:
            await self._check_results(qualification.results, qualification.decided_by_kind)

    # ── Writers (flush only; the public methods commit) ─────────────────────

    async def _check_results(
        self, entries: Sequence[ResultEntry], decided_by_kind: DecidedByKind
    ) -> dict[str, QualificationCriterion]:
        """Every rule a set of results must meet, checked before anything is
        written. Returns the current version of every criterion by key."""
        if not entries:
            raise ValidationError("record at least one result")
        keys = [entry.criterion_key for entry in entries]
        if len(set(keys)) != len(keys):
            raise ValidationError("each criterion may appear once per recording")

        current = {c.key: c for c in await self._repo.current_criteria()}
        unknown = sorted(set(keys) - set(current))
        if unknown:
            raise ValidationError(f"unknown qualification criteria: {unknown}")
        inactive = sorted(key for key in keys if not current[key].active)
        if inactive:
            raise ValidationError(f"inactive qualification criteria: {inactive}")
        for entry in entries:
            _check_entry(entry, entry.decided_by_kind or decided_by_kind)
        return current

    async def _write_results(
        self,
        customer_id: uuid.UUID,
        entries: Sequence[ResultEntry],
        *,
        actor_id: str | None,
        source: QualificationSource,
        decided_by_kind: DecidedByKind,
    ) -> list[QualificationResult]:
        current = await self._check_results(entries, decided_by_kind)

        rows: list[QualificationResult] = []
        for entry in entries:
            criterion = current[entry.criterion_key]
            kind = entry.decided_by_kind or decided_by_kind
            row = QualificationResult(
                customer_id=customer_id,
                criterion_id=criterion.id,
                result=entry.result,
                observed_value=_clean(entry.observed_value),
                source=source,
                decided_by_kind=kind,
                evidence_note=_clean(entry.evidence_note),
                evidence_refs=[{"type": ref.type, "ref": ref.ref} for ref in entry.evidence_refs],
                reason=_clean(entry.reason),
                confidence=entry.confidence,
                recorded_by=actor_id,
            )
            row.criterion = criterion
            await self._repo.add(row)
            await self._history.record(
                customer_id,
                dimension=HISTORY_DIMENSION_QUALIFICATION,
                to_value=entry.result.value,
                actor_id=actor_id,
                reason=row.reason,
                source="qualification_service.record_results",
                event_type=QUALIFICATION_RESULT_EVENT,
                details={
                    "result_id": str(row.id),
                    "criterion_key": criterion.key,
                    "criterion_version": criterion.version,
                    "source": source.value,
                    "decided_by_kind": kind.value,
                },
            )
            rows.append(row)
        return rows

    async def _write_outcome(
        self,
        profile: ExporterProfile,
        outcome: QualificationOutcomeValue,
        *,
        reason_codes: list[str],
        note: str | None,
        suggested: QualificationOutcomeValue,
        result_ids: Sequence[uuid.UUID],
        source: QualificationSource,
        decided_by_kind: DecidedByKind,
        decided_by: str | None,
        actor_id: str | None,
        extra_details: dict | None = None,
    ) -> QualificationOutcome:
        customer_id = profile.customer_id
        from_state = profile.qualification
        previous = await self._repo.latest_outcome(customer_id)
        row = QualificationOutcome(
            customer_id=customer_id,
            outcome=outcome,
            reason_codes=reason_codes,
            note=note,
            suggested_outcome=suggested,
            result_ids=[str(result_id) for result_id in result_ids],
            source=source,
            decided_by_kind=decided_by_kind,
            supersedes_outcome_id=previous.id if previous is not None else None,
            decided_by=decided_by,
        )
        await self._repo.add(row)

        to_state = QualificationState(outcome.value)
        profile.qualification = to_state
        await self._history.record(
            customer_id,
            dimension=HISTORY_DIMENSION_QUALIFICATION,
            from_value=from_state.value,
            to_value=to_state.value,
            actor_id=actor_id,
            reason=note,
            source="qualification_service.record_outcome",
            details={
                "outcome_id": str(row.id),
                "reason_codes": reason_codes,
                "suggested_outcome": suggested.value,
                "re_review": previous is not None,
                "supersedes_outcome_id": str(previous.id) if previous is not None else None,
                "source": source.value,
                "decided_by_kind": decided_by_kind.value,
                **(extra_details or {}),
            },
        )

        if outcome is QualificationOutcomeValue.QUALIFIED and profile.journey is ExporterJourney.LEAD:
            profile.journey = ExporterJourney.PROSPECT
            await self._history.record(
                customer_id,
                dimension=HISTORY_DIMENSION_JOURNEY,
                from_value=ExporterJourney.LEAD.value,
                to_value=ExporterJourney.PROSPECT.value,
                actor_id=actor_id,
                source="qualification_service.record_outcome",
                event_type=JOURNEY_TRANSITION_EVENT,
                details={
                    "cause": "qualification_outcome",
                    "outcome_id": str(row.id),
                    "terminal": False,  # CUSTOMER is the terminal value; never from here
                },
            )

        logger.info(
            "qualification.outcome.recorded",
            customer_id=str(customer_id),
            outcome=outcome.value,
            suggested=suggested.value,
            source=source.value,
            re_review=previous is not None,
            actor_id=actor_id,
        )
        return row

    # ── Read ────────────────────────────────────────────────────────────────

    async def get_qualification(self, customer_id: uuid.UUID) -> QualificationView:
        profile = await self._require_profile(customer_id)
        standings = await self._standings(customer_id)
        suggested = _suggest(standings)
        return QualificationView(
            state=profile.qualification,
            journey=profile.journey,
            suggested_outcome=suggested,
            standings=tuple(standings),
            results=tuple(await self._repo.results_for(customer_id)),
            outcomes=tuple(await self._repo.outcomes_for(customer_id)),
        )

    # ── Internals ───────────────────────────────────────────────────────────

    async def _standings(self, customer_id: uuid.UUID) -> list[CriterionStanding]:
        """For every current criterion, the latest result for its key and
        whether that result counts (was judged against the current version)."""
        latest_by_key: dict[str, QualificationResult] = {}
        for result in await self._repo.results_for(customer_id):  # newest first
            latest_by_key.setdefault(result.criterion.key, result)
        return [
            CriterionStanding(
                criterion=criterion,
                latest_result=latest_by_key.get(criterion.key),
                counts=(
                    criterion.key in latest_by_key
                    and latest_by_key[criterion.key].criterion_id == criterion.id
                ),
            )
            for criterion in await self._repo.current_criteria()
        ]

    async def _suggestion(
        self, customer_id: uuid.UUID
    ) -> tuple[QualificationOutcomeValue, list[uuid.UUID]]:
        standings = await self._standings(customer_id)
        result_ids = [
            s.latest_result.id
            for s in standings
            if s.criterion.active and s.latest_result is not None
        ]
        return _suggest(standings), result_ids

    async def _check_reason_codes(
        self, outcome: QualificationOutcomeValue, codes: list[str], note: str | None
    ) -> None:
        if outcome is QualificationOutcomeValue.NOT_QUALIFIED and not codes:
            raise ValidationError("NOT_QUALIFIED needs at least one reason code")
        if not codes:
            return
        known = {code.code: code for code in await self._repo.reason_codes() if code.active}
        unknown = sorted(set(codes) - set(known))
        if unknown:
            raise ValidationError(f"unknown reason codes: {unknown}")
        needing_note = sorted(code for code in codes if known[code].requires_note)
        if needing_note and note is None:
            raise ValidationError(f"reason codes {needing_note} need a note explaining them")

    async def _lock_profile(self, customer_id: uuid.UUID) -> ExporterProfile:
        """The company row, locked for the rest of the transaction."""
        result = await self._db.execute(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile

    async def _require_profile(self, customer_id: uuid.UUID) -> ExporterProfile:
        result = await self._db.execute(
            select(ExporterProfile).where(ExporterProfile.customer_id == customer_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile


# ── Pure helpers ─────────────────────────────────────────────────────────────


def _suggest(standings: Sequence[CriterionStanding]) -> QualificationOutcomeValue:
    """`QUALIFIED` exactly when every active, required criterion has a
    latest result of `PASS` against its current version."""
    required = [s for s in standings if s.criterion.active and s.criterion.required]
    if required and all(
        s.counts
        and s.latest_result is not None
        and s.latest_result.result is CriterionResultValue.PASS
        for s in required
    ):
        return QualificationOutcomeValue.QUALIFIED
    return QualificationOutcomeValue.NOT_QUALIFIED


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _check_key(key: str) -> str:
    cleaned = key.strip()
    if not cleaned or len(cleaned) > 64 or not (
        cleaned[0].isascii() and cleaned[0].islower()
        and all(ch.isascii() and (ch.islower() or ch.isdigit() or ch == "_") for ch in cleaned)
    ):
        raise ValidationError(
            "criterion key must be lower snake case (letters, digits, underscores), "
            "starting with a letter, at most 64 characters"
        )
    return cleaned


def _check_definition(definition: CriterionDefinition) -> None:
    """The kind decides which of comparison, threshold and allowed values a
    version must carry (the database checks the same shape)."""
    if not definition.label.strip():
        raise ValidationError("criterion label must not be blank")
    numeric = (definition.comparison, definition.threshold)
    if definition.kind is CriterionKind.NUMBER_THRESHOLD:
        if None in numeric or definition.allowed_values is not None:
            raise ValidationError(
                "a NUMBER_THRESHOLD criterion needs a comparison and a threshold, "
                "and no allowed values"
            )
    elif definition.kind is CriterionKind.YES_NO:
        if numeric != (None, None) or definition.allowed_values is not None:
            raise ValidationError(
                "a YES_NO criterion takes no comparison, threshold or allowed values"
            )
    else:
        values = definition.allowed_values or ()
        if numeric != (None, None) or not values:
            raise ValidationError(
                "an ALLOWED_VALUES criterion needs at least one allowed value, "
                "and no comparison or threshold"
            )
        if any(not v.strip() for v in values) or len(set(values)) != len(values):
            raise ValidationError("allowed values must be distinct and not blank")


def _criterion_row(
    key: str, version: int, definition: CriterionDefinition, actor_id: str | None
) -> QualificationCriterion:
    return QualificationCriterion(
        key=key,
        version=version,
        label=definition.label.strip(),
        kind=definition.kind,
        comparison=definition.comparison,
        threshold=definition.threshold,
        unit=_clean(definition.unit),
        allowed_values=(
            list(definition.allowed_values) if definition.allowed_values is not None else None
        ),
        required=definition.required,
        active=definition.active,
        created_by=actor_id,
    )


def _check_partner_outcome(
    qualification: PartnerQualification, source: QualificationSource
) -> None:
    """A partner hands over exporters it has already filtered in (decision 7)."""
    if qualification.outcome is not QualificationOutcomeValue.QUALIFIED:
        raise ValidationError(
            f"a {source.value} delivery must carry a QUALIFIED outcome; "
            f"got {qualification.outcome.value}"
        )


def _check_entry(entry: ResultEntry, decided_by_kind: DecidedByKind) -> None:
    if entry.result is not CriterionResultValue.UNKNOWN and not (
        _clean(entry.evidence_note) or entry.evidence_refs
    ):
        raise ValidationError(
            f"{entry.criterion_key}: a {entry.result.value} result needs evidence "
            "(a note or at least one reference)"
        )
    for ref in entry.evidence_refs:
        if ref.type not in _EVIDENCE_TYPES or not ref.ref.strip():
            raise ValidationError(
                f"{entry.criterion_key}: evidence references need a type "
                f"({sorted(_EVIDENCE_TYPES)}) and a non-blank ref"
            )
    if entry.confidence is not None:
        if decided_by_kind is not DecidedByKind.AUTOMATED:
            raise ValidationError(
                f"{entry.criterion_key}: only an automated result carries a confidence"
            )
        if not Decimal(0) <= entry.confidence <= Decimal(1):
            raise ValidationError(f"{entry.criterion_key}: confidence must be between 0 and 1")


__all__ = [
    "HISTORY_DIMENSION_QUALIFICATION",
    "JOURNEY_TRANSITION_EVENT",
    "QUALIFICATION_RESULT_EVENT",
    "QualificationService",
]
