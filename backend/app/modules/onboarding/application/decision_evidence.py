"""``DecisionEvidenceReader`` — what a background-check decision rested on, readable.

A decision pins **ids** (``background_check_evidence``, contract §6): a verification
result and the review its standing rested on, an exact screening row, a company
document. The decision list serves those ids and nothing more. This resolves each one
into what a reviewer needs to see why the decision was taken — without leaving the
page and without a second system of record:

* a **verification result**: its type, status, risk, provenance, when it was performed
  and who recorded it, its evidence note and references, and the review that was
  pinned (with whether a later review has since superseded it);
* a **screening row**: the item's key and label (a retired item keeps its label, so a
  decision taken under the eight-item rules still reads), its status,
  comment, evidence references, and who answered it when;
* a **document**: its name, category, type, scan status and whether it can be opened.

Everything is read from the rows the ids point at, **as they are** — a pinned row is
append-only or frozen once pinned, so what is shown is what the decision rested on.

**No identifiers.** None of these shapes carries a PAN, GSTIN, IEC, CIN, a buyer's tax
id or a contact detail: a verification result's ``subject_snapshot``, ``raw_result`` and
``normalized_result`` are deliberately not resolved. Free text a person typed (a
comment, a note, a reason) is, which is why the route admits no DEVELOPER.

Read-only: no lock, no flush, no commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.screening_review_service import (
    ITEM_LABELS,
    RETIRED_ITEM_KEYS,
)
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.background_check_views import effective_rules_version
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckEvidenceKind,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle
from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationEntityType
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.modules.onboarding.domain.history_dimensions import VERIFICATION
from app.modules.onboarding.exceptions import BackgroundCheckDecisionNotFoundError
from app.modules.onboarding.infrastructure.repositories.background_check_decision_repository import (  # noqa: E501
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
    resolved_cycle_id,
)


@dataclass(frozen=True)
class PinnedReview:
    id: uuid.UUID
    review_status: str
    reviewed_by: str
    reviewed_at: datetime
    note: str | None


@dataclass(frozen=True)
class VerificationEvidenceDetail:
    verification_result_id: uuid.UUID
    verification_type: str
    status: str
    risk_level: str | None
    provider: str
    provenance: str
    is_placeholder: bool
    performed_at: datetime
    recorded_by: str | None
    evidence_note: str | None
    evidence_refs: tuple[dict[str, str], ...]
    pinned_review: PinnedReview | None
    #: True when a later review has superseded the pinned one since the decision.
    review_superseded: bool
    cycle_id: uuid.UUID | None


@dataclass(frozen=True)
class ScreeningEvidenceDetail:
    screening_review_item_id: uuid.UUID
    item_key: str
    label: str
    retired: bool
    status: str
    comment: str | None
    evidence_refs: tuple[dict[str, str], ...]
    reviewed_by: str | None
    reviewed_at: datetime | None
    cycle_id: uuid.UUID | None


@dataclass(frozen=True)
class DocumentEvidenceDetail:
    crm_document_id: uuid.UUID
    file_name: str
    category: str
    document_type: str
    scan_status: str
    is_downloadable: bool
    uploaded_by: str | None
    uploaded_at: datetime


@dataclass(frozen=True)
class ResolvedEvidenceItem:
    """One pinned id, resolved. Exactly the detail for ``kind`` is set; a pinned row
    that can no longer be found (impossible under the ``RESTRICT`` foreign keys, but not
    assumed) is served with all three ``None`` rather than dropped."""

    kind: BackgroundCheckEvidenceKind
    verification: VerificationEvidenceDetail | None = None
    screening_item: ScreeningEvidenceDetail | None = None
    document: DocumentEvidenceDetail | None = None


@dataclass(frozen=True)
class DecisionEvidenceView:
    decision: BackgroundCheckDecision
    #: The Clear rules the decision was taken under, with the legacy rule applied.
    rules_version: str
    cycle: CheckCycle | None
    items: tuple[ResolvedEvidenceItem, ...]


def _refs(value: Any) -> tuple[dict[str, str], ...]:
    return tuple(ref for ref in (value or ()) if isinstance(ref, dict))


class DecisionEvidenceReader:
    """Resolves one decision's pinned evidence. See the module docstring."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._decisions = BackgroundCheckDecisionRepository(db)
        self._cycles = CheckCycleRepository(db)

    async def for_decision(
        self, company_id: uuid.UUID, decision_id: uuid.UUID
    ) -> DecisionEvidenceView:
        """Raises ``BackgroundCheckDecisionNotFoundError`` (404) unless the decision
        exists **and** belongs to ``company_id``."""
        decision = await self._db.scalar(
            select(BackgroundCheckDecision).where(
                BackgroundCheckDecision.id == decision_id,
                BackgroundCheckDecision.company_id == company_id,
            )
        )
        if decision is None:
            raise BackgroundCheckDecisionNotFoundError(company_id, decision_id)

        pinned = (await self._decisions.evidence_for([decision.id]))[decision.id]
        cycles = await self._cycles.list_for_company(company_id)
        initial = cycles[0] if cycles else None
        cycle_by_id = {cycle.id: cycle for cycle in cycles}

        verifications = await self._verifications(
            company_id,
            [row.verification_result_id for row in pinned if row.verification_result_id],
            initial,
        )
        screening = await self._screening(
            [row.screening_review_item_id for row in pinned if row.screening_review_item_id],
            initial,
        )
        documents = await self._documents(
            [row.crm_document_id for row in pinned if row.crm_document_id]
        )

        items: list[ResolvedEvidenceItem] = []
        for row in pinned:
            kind = BackgroundCheckEvidenceKind(row.kind)
            if kind is BackgroundCheckEvidenceKind.VERIFICATION_RESULT:
                detail = verifications.get(row.verification_result_id)
                items.append(
                    ResolvedEvidenceItem(
                        kind=kind,
                        verification=(
                            _with_pinned_review(detail, row.verification_review_id)
                            if detail is not None
                            else None
                        ),
                    )
                )
            elif kind is BackgroundCheckEvidenceKind.SCREENING_ITEM:
                items.append(
                    ResolvedEvidenceItem(
                        kind=kind, screening_item=screening.get(row.screening_review_item_id)
                    )
                )
            else:
                items.append(
                    ResolvedEvidenceItem(kind=kind, document=documents.get(row.crm_document_id))
                )

        decision_cycle = cycle_by_id.get(resolved_cycle_id(decision.cycle_id, initial))
        return DecisionEvidenceView(
            decision=decision,
            rules_version=effective_rules_version(decision.rules_version),
            cycle=decision_cycle,
            items=tuple(items),
        )

    # ── Per kind ─────────────────────────────────────────────────────────────

    async def _verifications(
        self,
        company_id: uuid.UUID,
        ids: list[uuid.UUID],
        initial: CheckCycle | None,
    ) -> dict[uuid.UUID, _VerificationRow]:
        if not ids:
            return {}
        results = list(
            (
                await self._db.execute(
                    select(VerificationResult).where(VerificationResult.id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        views = await VerificationService(self._db).views_for(results)
        recorded_by = await self._recorders(
            await self._timelines(company_id, results), [result.id for result in results]
        )
        return {
            view.result.id: _VerificationRow(
                result=view.result,
                reviews=view.reviews,
                recorded_by=recorded_by.get(str(view.result.id)),
                cycle_id=resolved_cycle_id(view.result.cycle_id, initial),
            )
            for view in views
        }

    async def _timelines(
        self, company_id: uuid.UUID, results: list[VerificationResult]
    ) -> set[uuid.UUID]:
        """The timelines the results' "recorded" rows are on: the company's, and — for a
        legacy deal-buyer result the deal-buyer migration mapped to this company
        — the seller's, where it was recorded with the deal as context."""
        buyer_ids = [
            result.entity_reference
            for result in results
            if result.entity_type == VerificationEntityType.BUYER
        ]
        if not buyer_ids:
            return {company_id}
        sellers = (
            await self._db.execute(
                select(Deal.company_id)
                .join(DealBuyer, DealBuyer.deal_id == Deal.id)
                .where(DealBuyer.id.in_(buyer_ids))
            )
        ).scalars()
        return {company_id, *sellers}

    async def _recorders(
        self, company_ids: set[uuid.UUID], result_ids: list[uuid.UUID]
    ) -> dict[str, str]:
        """Who recorded each result: the actor of its first ``verification`` history row.

        ``verification_result`` has no "recorded by" column; the history row written in
        the same transaction does (``VerificationService._record_history``). A result
        with no such row — one written before the shared history log — has no recorder
        to show, and none is invented.
        """
        key = ExporterLifecycleHistory.event_metadata["verification_result_id"].astext
        rows = (
            await self._db.execute(
                select(key, ExporterLifecycleHistory.actor_id).where(
                    ExporterLifecycleHistory.customer_id.in_(company_ids),
                    ExporterLifecycleHistory.dimension == VERIFICATION,
                    ExporterLifecycleHistory.event_type == f"{VERIFICATION}_initial",
                    key.in_([str(result_id) for result_id in result_ids]),
                )
            )
        ).all()
        return {result_id: actor for result_id, actor in rows if actor}

    async def _screening(
        self, ids: list[uuid.UUID], initial: CheckCycle | None
    ) -> dict[uuid.UUID, ScreeningEvidenceDetail]:
        if not ids:
            return {}
        rows = (
            await self._db.execute(
                select(ScreeningReviewItem).where(ScreeningReviewItem.id.in_(ids))
            )
        ).scalars()
        return {
            row.id: ScreeningEvidenceDetail(
                screening_review_item_id=row.id,
                item_key=row.item_key,
                label=ITEM_LABELS.get(row.item_key, row.item_key),
                retired=row.item_key in RETIRED_ITEM_KEYS,
                status=row.status,
                comment=row.comment,
                evidence_refs=_refs(row.evidence_refs),
                reviewed_by=row.reviewed_by,
                reviewed_at=row.reviewed_at,
                cycle_id=resolved_cycle_id(row.cycle_id, initial),
            )
            for row in rows
        }

    async def _documents(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, DocumentEvidenceDetail]:
        if not ids:
            return {}
        rows = (
            await self._db.execute(select(CrmDocument).where(CrmDocument.id.in_(ids)))
        ).scalars()
        return {
            row.id: DocumentEvidenceDetail(
                crm_document_id=row.id,
                file_name=row.file_name,
                category=row.category.value,
                document_type=row.document_type,
                scan_status=row.scan_status.value,
                is_downloadable=row.scan_status.is_servable,
                uploaded_by=row.uploaded_by,
                uploaded_at=row.uploaded_at,
            )
            for row in rows
        }


@dataclass(frozen=True)
class _VerificationRow:
    result: VerificationResult
    reviews: tuple[VerificationReview, ...]
    recorded_by: str | None
    cycle_id: uuid.UUID | None


def _with_pinned_review(
    row: _VerificationRow, pinned_review_id: uuid.UUID | None
) -> VerificationEvidenceDetail:
    result = row.result
    pinned = next((review for review in row.reviews if review.id == pinned_review_id), None)
    head = row.reviews[-1] if row.reviews else None
    return VerificationEvidenceDetail(
        verification_result_id=result.id,
        verification_type=result.verification_type.value,
        status=result.status.value,
        risk_level=result.risk_level.value if result.risk_level is not None else None,
        provider=result.provider,
        provenance=result.provenance,
        is_placeholder=result.is_placeholder,
        performed_at=result.performed_at,
        recorded_by=row.recorded_by,
        evidence_note=result.evidence_note,
        evidence_refs=_refs(result.evidence_refs),
        pinned_review=(
            PinnedReview(
                id=pinned.id,
                review_status=pinned.review_status.value,
                reviewed_by=pinned.reviewed_by,
                reviewed_at=pinned.reviewed_at,
                note=pinned.note,
            )
            if pinned is not None
            else None
        ),
        review_superseded=head is not None and head.id != pinned_review_id,
        cycle_id=row.cycle_id,
    )


__all__ = [
    "DecisionEvidenceReader",
    "DecisionEvidenceView",
    "DocumentEvidenceDetail",
    "PinnedReview",
    "ResolvedEvidenceItem",
    "ScreeningEvidenceDetail",
    "VerificationEvidenceDetail",
]
