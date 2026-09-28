"""``ComplianceInputsService`` — the 4A ↔ 4B seam's implementation. **Owner: Developer 4B.**

Implements ``domain/compliance_inputs.py::ComplianceInputsReader``
(``docs/dev4/4b-task.md`` §6). Developer 4A reads the inputs to a background-check
decision through this and nothing else; it never queries Dev4B's tables itself.

Reads the tables honestly. 4B-0 read today's tables; 4B-2 switched the latest review
to the superseding-review table and 4B-4 filled the evidence ids — the shape returned
never changed (§6.2 invariant 7).

Read-only in the caller's session
---------------------------------
Dev4A calls this inside its own transaction, holding the company row
``FOR UPDATE``. So this never commits, never flushes and never locks (§6.2
invariant 2):

* every query runs under ``no_autoflush``, so objects the caller has added or
  changed but not flushed stay exactly as they were — the reader sees committed
  and already-flushed state only;
* every query selects columns, not entities, so nothing enters or refreshes the
  caller's identity map;
* nothing here takes a row lock. The caller owns locking. Writers of these inputs
  take ``FOR SHARE`` on the company (``company_input_lock.py``), which is what makes
  a read under Dev4A's ``FOR UPDATE`` a stable one.

What each field means today
---------------------------
* **Screening** — the latest row per catalogue key, by ``created_at DESC, id DESC``
  (the rule ``ScreeningReviewService.list_review_items`` uses). One
  ``ScreeningItemInput`` per catalogue key, in catalogue order; a key never
  recorded has ``screening_review_item_id=None`` and ``status=None``. Rows under a
  key outside the catalogue are not returned.
* **Verifications (company)** — ``entity_type = EXPORTER`` and
  ``entity_reference = company_id`` only, newest first (``performed_at DESC``, then
  ``created_at DESC, id DESC`` so ties are deterministic). Results on DIRECTOR,
  INVOICE, VESSEL or SHIPMENT subjects carry no company link and are **not**
  returned; whether that is acceptable for "no checks pending" is D2, Dev4A's.
  BUYER results are never returned here (§6.2 invariant 4).
* **Latest review** — the head of the result's ``verification_review`` chain: the
  review nothing supersedes (4B-2). The database allows exactly one per reviewed
  result, so it is deterministic. ``latest_review_id``, ``latest_review_status`` and
  ``latest_reviewed_at`` are that review's. A result with no review row but a
  legacy ``review_status`` (written outside the service after migration 0021, which
  copied every earlier one) reports that status with ``None`` id and time, as 4B-0
  did — never an invented id or time.
* **Placeholders** — ``is_placeholder`` is ``verification_result.
  is_placeholder_result``: ``normalized_result.stub`` is ``true`` and no
  ``provider_reference``. Reported, not filtered: whether a placeholder counts as
  pending is Dev4A's D2.
* **Evidence** — ``evidence_document_ids`` are the ``document`` references in the
  result's ``evidence_refs``, in the order recorded (4B-4). ``url`` references are
  not documents and are not reported. The retired ``evidence_reference`` column is
  not read.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.onboarding.application.screening_review_service import SCREENING_CATALOGUE
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ScreeningItemInput,
    VerificationInput,
)
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationEntityType
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.domain.entities.verification_result import (
    VerificationResult,
    is_placeholder_result,
)
from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.modules.onboarding.exceptions import (
    ComplianceInputsBuyerNotFoundError,
    ExporterProfileNotFoundError,
)

_VERIFICATION_COLUMNS = (
    VerificationResult.id,
    VerificationResult.verification_type,
    VerificationResult.entity_type,
    VerificationResult.provider,
    VerificationResult.provider_reference,
    VerificationResult.status,
    VerificationResult.risk_level,
    VerificationResult.performed_at,
    VerificationResult.normalized_result,
    VerificationResult.review_status,
    VerificationResult.evidence_refs,
)


def _document_ids(evidence_refs: Any) -> tuple[uuid.UUID, ...]:
    ids: list[uuid.UUID] = []
    for ref in evidence_refs or ():
        if isinstance(ref, dict) and ref.get("type") == "document":
            try:
                ids.append(uuid.UUID(str(ref.get("ref"))))
            except ValueError:
                continue  # the service never stores one; a raw-SQL row is skipped, not guessed
    return tuple(ids)


def _verification_input(row: Any, head: Any | None) -> VerificationInput:
    if head is not None:
        latest_id, latest_status, latest_at = head.id, head.review_status.value, head.reviewed_at
    else:
        latest_id, latest_at = None, None
        latest_status = row.review_status.value if row.review_status is not None else None
    return VerificationInput(
        verification_result_id=row.id,
        verification_type=row.verification_type.value,
        entity_type=row.entity_type.value,
        provider=row.provider,
        status=row.status.value,
        risk_level=row.risk_level.value if row.risk_level is not None else None,
        performed_at=row.performed_at,
        is_placeholder=is_placeholder_result(row.normalized_result, row.provider_reference),
        latest_review_id=latest_id,
        latest_review_status=latest_status,
        latest_reviewed_at=latest_at,
        evidence_document_ids=_document_ids(row.evidence_refs),
    )


def _screening_item(item_key: str, row: Any | None) -> ScreeningItemInput:
    if row is None:
        return ScreeningItemInput(
            item_key=item_key,
            screening_review_item_id=None,
            status=None,
            reviewed_by=None,
            reviewed_at=None,
        )
    return ScreeningItemInput(
        item_key=item_key,
        screening_review_item_id=row.id,
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
    )


class ComplianceInputsService:
    """Implements ``ComplianceInputsReader``. See the module docstring for the rules."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _verification_inputs(self, rows: list[Any]) -> tuple[VerificationInput, ...]:
        """Attach each row's chain head — the review nothing supersedes. Call inside
        ``no_autoflush``; selects columns only."""
        if not rows:
            return ()
        later = aliased(VerificationReview)
        heads = (
            await self._db.execute(
                select(
                    VerificationReview.verification_result_id,
                    VerificationReview.id,
                    VerificationReview.review_status,
                    VerificationReview.reviewed_at,
                )
                .outerjoin(later, later.supersedes_review_id == VerificationReview.id)
                .where(
                    VerificationReview.verification_result_id.in_([row.id for row in rows]),
                    later.id.is_(None),
                )
            )
        ).all()
        head_by_result = {head.verification_result_id: head for head in heads}
        return tuple(_verification_input(row, head_by_result.get(row.id)) for row in rows)

    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs:
        """The company's eight screening items and its EXPORTER verification results.

        Raises:
            ExporterProfileNotFoundError: no company has this id.
        """
        with self._db.no_autoflush:
            exists = await self._db.scalar(
                select(ExporterProfile.customer_id).where(
                    ExporterProfile.customer_id == company_id
                )
            )
            if exists is None:
                raise ExporterProfileNotFoundError(company_id)

            latest_rows = (
                await self._db.execute(
                    select(
                        ScreeningReviewItem.item_key,
                        ScreeningReviewItem.id,
                        ScreeningReviewItem.status,
                        ScreeningReviewItem.reviewed_by,
                        ScreeningReviewItem.reviewed_at,
                    )
                    .where(ScreeningReviewItem.customer_id == company_id)
                    .distinct(ScreeningReviewItem.item_key)
                    .order_by(
                        ScreeningReviewItem.item_key.asc(),
                        ScreeningReviewItem.created_at.desc(),
                        ScreeningReviewItem.id.desc(),
                    )
                )
            ).all()

            verification_rows = (
                await self._db.execute(
                    select(*_VERIFICATION_COLUMNS)
                    .where(
                        VerificationResult.entity_type == VerificationEntityType.EXPORTER,
                        VerificationResult.entity_reference == company_id,
                    )
                    .order_by(
                        VerificationResult.performed_at.desc(),
                        VerificationResult.created_at.desc(),
                        VerificationResult.id.desc(),
                    )
                )
            ).all()
            verifications = await self._verification_inputs(list(verification_rows))

        latest = {row.item_key: row for row in latest_rows}
        screening_items = tuple(
            _screening_item(key, latest.get(key)) for key in SCREENING_CATALOGUE
        )
        return CompanyComplianceInputs(
            company_id=company_id,
            screening_catalogue=SCREENING_CATALOGUE,
            screening_items=screening_items,
            verifications=verifications,
        )

    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]:
        """The BUYER verification results recorded against one ``deal_buyer.id``, newest first.

        Keyed by the buyer id only, never the deal or the company (§6.2 invariant 4).
        Nothing returned here is ever part of ``company_inputs``.

        Raises:
            ComplianceInputsBuyerNotFoundError: no deal buyer has this id.
        """
        with self._db.no_autoflush:
            exists = await self._db.scalar(
                select(DealBuyer.id).where(DealBuyer.id == deal_buyer_id)
            )
            if exists is None:
                raise ComplianceInputsBuyerNotFoundError(deal_buyer_id)

            rows = (
                await self._db.execute(
                    select(*_VERIFICATION_COLUMNS)
                    .where(
                        VerificationResult.entity_type == VerificationEntityType.BUYER,
                        VerificationResult.entity_reference == deal_buyer_id,
                    )
                    .order_by(
                        VerificationResult.performed_at.desc(),
                        VerificationResult.created_at.desc(),
                        VerificationResult.id.desc(),
                    )
                )
            ).all()
            return await self._verification_inputs(list(rows))


__all__ = ["ComplianceInputsService"]
