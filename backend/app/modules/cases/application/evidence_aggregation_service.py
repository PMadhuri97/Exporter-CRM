"""Evidence aggregation for compliance cases — Epic-4-only slice (ANER-4.3-S2T2).

The Jira ticket this implements (ANER-4.3-S2T2) describes a much larger
cross-epic aggregator that pulls evidence from Epics 2.2/2.5/2.6/2.7/2.8/
3.1/3.2/3.3/3.4/4.1/5.3. None of that exists yet — the platform's only real
data source today is RXIL (an Indian invoice/receivables marketplace where
ANER participates as financier), which pushes invoice/counterparty data
directly and already performs its own KYC, AML/CFT screening, invoice
duplication checks, vessel tracking, MLETR bill-of-lading verification, buyer
ratings, and insurance. This module records RXIL's own outputs as evidence on
a case; it does not call out to, and must not import, any module besides
`app.modules.cases` and generic platform infrastructure — there is nothing
else to call yet, and Epics 2.x/3.x/5.x are explicitly out of scope for this
slice.

`EvidenceAggregationService` — naming mirrors `SlaCalculationService`
(`application/sla_service.py`) — has two operations:

- `add_evidence_item` inserts one `case_evidence_item` row. `source_epic` is
  the entity's existing free-text string field, not an enum; for RXIL-sourced
  evidence it will typically be the literal string `"RXIL"`, not an actual
  platform epic name, and this service does not validate it against any
  epic-name list.
- `aggregate_evidence_package` reads every `case_evidence_item` row for a
  case and writes a consolidated JSON structure onto `compliance_case.
  evidence_package`.

**Evidence package shape.** Neither the ticket's data model docstring nor
`compliance_case.evidence_package`'s own docstring specifies a shape beyond
"the aggregated evidence package a reviewer sees" / "the rolled-up view a
case's own row carries", so this module makes an explicit choice: a dict
keyed by `evidence_type` (the plain enum value, e.g. `"BUYER_RATING"`), each
value a list of evidence-item summaries, newest last. A list per key rather
than a single object per key because nothing prevents a case from
accumulating more than one item of the same evidence_type (e.g. RXIL pushing
an updated buyer rating, or two manual attachments) — a dict-of-one-object
would silently drop all but the last. Each summary embeds `evidence_data` in
full: `compliance_case.evidence_package` is already documented (see that
column's docstring) as carrying the same encrypted-at-rest gap
`case_evidence_item.evidence_data` does whenever a PII-bearing evidence type
is embedded, which is precisely what happens here for `BUYER_RATING` /
`INSURANCE_CERTIFICATE` items — this module does not invent a new encryption
mechanism, it reproduces the same already-accepted, documented gap.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.domain.entities.case_evidence_item import CaseEvidenceItem
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import EvidenceType
from app.modules.cases.exceptions import CaseNotFoundError


class EvidenceAggregationService:
    """Records evidence against a case and rolls it up into `evidence_package`."""

    __slots__ = ()

    async def add_evidence_item(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        evidence_type: EvidenceType,
        source_epic: str,
        source_reference_id: uuid.UUID,
        evidence_data: dict,
        added_by: str,
        is_key_evidence: bool = False,
    ) -> CaseEvidenceItem:
        """Insert one `case_evidence_item` row for `case_id`.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id` —
                checked explicitly rather than left to surface as a raw
                foreign-key violation, matching `SlaCalculationService`'s
                convention of a typed, purpose-built error.
        """
        await self._get_case(session, case_id)

        item = CaseEvidenceItem(
            case_id=case_id,
            evidence_type=evidence_type,
            source_epic=source_epic,
            source_reference_id=source_reference_id,
            evidence_data=evidence_data,
            added_by=added_by,
            is_key_evidence=is_key_evidence,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item

    async def aggregate_evidence_package(
        self, session: AsyncSession, case_id: uuid.UUID
    ) -> dict:
        """Roll up every `case_evidence_item` row for `case_id` into a dict
        keyed by `evidence_type`, write it onto `compliance_case.
        evidence_package`, and return it.

        See the module docstring for the exact shape and why it was chosen.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
        """
        case = await self._get_case(session, case_id)

        items = (
            (
                await session.execute(
                    select(CaseEvidenceItem)
                    .where(CaseEvidenceItem.case_id == case_id)
                    .order_by(CaseEvidenceItem.added_at)
                )
            )
            .scalars()
            .all()
        )

        package: dict[str, list[dict]] = {}
        for item in items:
            package.setdefault(item.evidence_type.value, []).append(
                {
                    "id": str(item.id),
                    "source_epic": item.source_epic,
                    "source_reference_id": str(item.source_reference_id),
                    "evidence_data": item.evidence_data,
                    "added_at": item.added_at.isoformat(),
                    "added_by": item.added_by,
                    "is_key_evidence": item.is_key_evidence,
                }
            )

        case.evidence_package = package
        await session.commit()
        return package

    async def _get_case(self, session: AsyncSession, case_id: uuid.UUID) -> ComplianceCase:
        case = await session.scalar(select(ComplianceCase).where(ComplianceCase.id == case_id))
        if case is None:
            raise CaseNotFoundError(case_id)
        return case


__all__ = ["EvidenceAggregationService"]
