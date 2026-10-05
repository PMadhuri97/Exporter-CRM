"""The document rule for evidence.

One rule, used wherever a compliance record carries ``{type, ref}`` evidence: a
verification result and a
screening answer. Moved here out of ``VerificationService`` so the two cannot drift.

A ``document`` reference must name a ``crm_document`` that exists, belongs to the
subject — the company, or for a legacy deal buyer the buyer's deal or its company —
and is ``AVAILABLE`` (scanned clean). Anything else is refused (422). The shape rule
(known types, http(s) links only) is ``domain.verification_evidence.check_evidence_shape``
and is applied first.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.verification_evidence import (
    VerificationEvidence,
    check_evidence_shape,
)
from app.modules.onboarding.infrastructure.repositories.crm_document_repository import (
    CrmDocumentRepository,
)
from app.shared.exceptions import ValidationError


async def check_evidence_documents(
    db: AsyncSession,
    evidence: VerificationEvidence | None,
    *,
    company_id: uuid.UUID | None,
    deal_id: uuid.UUID | None = None,
    subject_label: str,
) -> None:
    """Refuse evidence whose shape is wrong or whose documents are foreign or unservable.

    ``company_id`` / ``deal_id`` say what the evidence may come from; ``None`` company
    means the subject owns no documents (a director, an invoice …), so any document
    reference is refused. ``subject_label`` names the subject in the messages.

    Raises:
        ValidationError: (422) see the module docstring.
    """
    check_evidence_shape(evidence)
    if evidence is None:
        return
    document_ids = evidence.document_ids()
    if not document_ids:
        return
    if company_id is None:
        raise ValidationError(
            f"document evidence cannot be attached to a {subject_label} subject: "
            "only a company (EXPORTER) or a deal buyer (BUYER) owns documents"
        )
    documents = CrmDocumentRepository(db)
    for document_id in document_ids:
        document = await documents.get_by_id(document_id)
        if document is None:
            raise ValidationError(f"evidence document {document_id} does not exist")
        owned = document.company_id == company_id or (
            deal_id is not None and document.deal_id == deal_id
        )
        if not owned:
            raise ValidationError(
                f"evidence document {document_id} does not belong to this {subject_label} subject"
            )
        # Only a document that can be opened can be evidence: PENDING_SCAN,
        # QUARANTINED and SCAN_FAILED are refused to everyone
        # (storage-and-documents.md §4), and evidence is frozen once written, so a
        # document still being scanned cannot be named now and "become" evidence
        # later. Checked after ownership, so a foreign document's scan state is never
        # disclosed.
        if not document.scan_status.is_servable:
            raise ValidationError(
                f"evidence document {document_id} is {document.scan_status.value}: "
                "only an AVAILABLE (scanned clean) document can be evidence"
            )


__all__ = ["check_evidence_documents"]
