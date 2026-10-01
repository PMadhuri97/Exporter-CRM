"""``ComplianceInputsService`` — the compliance-inputs seam's implementation.
**Owner: Developer 1** (compliance engine, allocation §2.1; built by Developer 4B).

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
* **Verifications (company) — company-keyed (plan P4-5).** The results *about* the
  company (``verification_result.about_company``): ``subject_company_id =
  company_id`` — every company-subject result recorded since P4-5, and a legacy
  deal-buyer result the deal-buyer migration (P4-6) mapped to this company — plus,
  for a row recorded before checks were company-keyed (``subject_company_id IS
  NULL``), ``entity_type = EXPORTER AND entity_reference = company_id``. So a company
  has one set of checks, whether it is a seller, a buyer or both. Newest first
  (``performed_at DESC``, then ``created_at DESC, id DESC`` so ties are
  deterministic). Results on DIRECTOR, INVOICE, VESSEL or SHIPMENT subjects carry no
  company link and are **not** returned. A legacy BUYER result that names no company
  is never returned here (§6.2 invariant 4 still holds for it).
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
* **Cycles (seam v2, plan P2-3b)** — ``company_inputs`` is scoped to the company's
  **current** check cycle (its highest ``check_cycle.number``): the results and the
  latest answer per item *of that cycle*. A row with ``cycle_id IS NULL`` belongs to
  cycle 1 by the legacy rule (``check_cycle_repository.in_cycle``), and is reported
  with cycle 1's id. So a Re-KYC starts with every item unanswered and no results,
  and a placeholder left in an earlier cycle no longer blocks ``CLEAR``. A company
  with no cycle row yet is read whole, exactly as before cycles existed.
  ``buyer_checks`` is unscoped: legacy deal buyers have no cycles.
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
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationEntityType
from app.modules.onboarding.domain.entities.screening_review import ScreeningReviewItem
from app.modules.onboarding.domain.entities.verification_result import (
    VerificationResult,
    about_company,
    is_placeholder_result,
)
from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.modules.onboarding.exceptions import (
    ComplianceInputsBuyerNotFoundError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    in_cycle,
    resolved_cycle_id,
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
    VerificationResult.cycle_id,
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


def _verification_input(
    row: Any, head: Any | None, cycle_id: uuid.UUID | None = None
) -> VerificationInput:
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
        cycle_id=cycle_id,
    )


def _screening_item(
    item_key: str, row: Any | None, initial: Any | None = None
) -> ScreeningItemInput:
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
        cycle_id=resolved_cycle_id(row.cycle_id, initial),
    )


class ComplianceInputsService:
    """Implements ``ComplianceInputsReader``. See the module docstring for the rules."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _verification_inputs(
        self, rows: list[Any], initial: Any | None = None
    ) -> tuple[VerificationInput, ...]:
        """Attach each row's chain head — the review nothing supersedes. Call inside
        ``no_autoflush``; selects columns only. ``initial`` is the company's cycle 1
        (``None`` for legacy buyer checks, which have no cycle)."""
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
        return tuple(
            _verification_input(
                row,
                head_by_result.get(row.id),
                resolved_cycle_id(row.cycle_id, initial) if initial is not None else row.cycle_id,
            )
            for row in rows
        )

    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs:
        """The company's screening items and the verification results about it
        (company-keyed, P4-5), in its current check cycle (seam v2).

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

            # The company's cycles, oldest first: the current one scopes the read, and
            # cycle 1 is what a legacy (NULL) row belongs to.
            cycles = (
                await self._db.execute(
                    select(CheckCycle.id, CheckCycle.number)
                    .where(CheckCycle.company_id == company_id)
                    .order_by(CheckCycle.number.asc())
                )
            ).all()
            current = cycles[-1] if cycles else None
            initial = cycles[0] if cycles else None

            latest_rows = (
                await self._db.execute(
                    select(
                        ScreeningReviewItem.item_key,
                        ScreeningReviewItem.id,
                        ScreeningReviewItem.status,
                        ScreeningReviewItem.reviewed_by,
                        ScreeningReviewItem.reviewed_at,
                        ScreeningReviewItem.cycle_id,
                    )
                    .where(
                        ScreeningReviewItem.customer_id == company_id,
                        in_cycle(ScreeningReviewItem.cycle_id, current),
                    )
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
                        about_company(company_id),
                        in_cycle(VerificationResult.cycle_id, current),
                    )
                    .order_by(
                        VerificationResult.performed_at.desc(),
                        VerificationResult.created_at.desc(),
                        VerificationResult.id.desc(),
                    )
                )
            ).all()
            verifications = await self._verification_inputs(list(verification_rows), initial)

        latest = {row.item_key: row for row in latest_rows}
        screening_items = tuple(
            _screening_item(key, latest.get(key), initial) for key in SCREENING_CATALOGUE
        )
        return CompanyComplianceInputs(
            company_id=company_id,
            screening_catalogue=SCREENING_CATALOGUE,
            screening_items=screening_items,
            verifications=verifications,
            current_cycle_id=current.id if current is not None else None,
        )

    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]:
        """The BUYER verification results recorded against one ``deal_buyer.id``, newest first.

        **Legacy** in seam v2: it serves deals whose buyer is still a ``deal_buyer`` row
        and is replaced by ``company_inputs(buyer_company_id)`` once a deal names a buyer
        company (plan P4-4/P4-5). Unscoped by cycle — legacy buyers have none.

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
