"""``ComplianceInputsService`` — the 4A ↔ 4B seam's implementation. **Owner: Developer 4B.**

Implements ``domain/compliance_inputs.py::ComplianceInputsReader``
(``docs/dev4/4b-task.md`` §6). Developer 4A reads the inputs to a background-check
decision through this and nothing else; it never queries Dev4B's tables itself.

Reads **today's** tables honestly (4B-0). Later Dev4B phases change how the values
are found — the superseding-review table (4B-2), evidence on results (4B-4) — but
never the shape returned (§6.2 invariant 7).

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
* **Latest review** — today a result has at most one review, held in its frozen
  ``review_status`` column. ``latest_review_status`` is that value.
  ``latest_review_id`` and ``latest_reviewed_at`` are ``None`` even on a reviewed
  result, because today's storage records neither a review id nor a review time;
  inventing one (the result's own id, or its ``updated_at``, which polling also
  moves) would be a false fact. 4B-2's review table fills both.
* **Placeholders** — ``is_placeholder`` is true for a row whose
  ``normalized_result.stub`` is ``true`` and that has no ``provider_reference``:
  the same rule ``VerificationSection.tsx`` labels as "Placeholder · no provider
  integration". Reported, not filtered: whether a placeholder counts as pending
  is Dev4A's D2.
* **Evidence** — ``evidence_document_ids`` is always ``()`` until 4B-4 adds
  evidence to results. ``verification_result.evidence_reference`` is a free-text
  column no code path writes, not a document id, so it is not reported here.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
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
)


def _is_placeholder(normalized_result: Any, provider_reference: str | None) -> bool:
    return (
        isinstance(normalized_result, dict)
        and normalized_result.get("stub") is True
        and not provider_reference
    )


def _verification_input(row: Any) -> VerificationInput:
    return VerificationInput(
        verification_result_id=row.id,
        verification_type=row.verification_type.value,
        entity_type=row.entity_type.value,
        provider=row.provider,
        status=row.status.value,
        risk_level=row.risk_level.value if row.risk_level is not None else None,
        performed_at=row.performed_at,
        is_placeholder=_is_placeholder(row.normalized_result, row.provider_reference),
        latest_review_id=None,
        latest_review_status=row.review_status.value if row.review_status is not None else None,
        latest_reviewed_at=None,
        evidence_document_ids=(),
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

        latest = {row.item_key: row for row in latest_rows}
        screening_items = tuple(
            _screening_item(key, latest.get(key)) for key in SCREENING_CATALOGUE
        )
        return CompanyComplianceInputs(
            company_id=company_id,
            screening_catalogue=SCREENING_CATALOGUE,
            screening_items=screening_items,
            verifications=tuple(_verification_input(row) for row in verification_rows),
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
        return tuple(_verification_input(row) for row in rows)


__all__ = ["ComplianceInputsService"]
