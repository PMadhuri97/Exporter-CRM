"""Enums for documents.

Contract: ``docs/contracts/storage-and-documents.md`` §5.3. Architecture §3.4.

``DocumentScanStatus`` is deliberately **not** here: it lives in
``domain/storage.py``, because the scanner port returns it and a port must not
import an entity module — the dependency runs the other way. This file imports it
so that ``crm_document.py`` and every caller have one place to look.

Document **types** are not an enum at all. They are seeded settings
(``deployments/gitops/reference-data/crm/documents/document-types.yaml``), so a new
type needs no code change and no migration — architecture §3.4. Only the ten
categories are fixed, because the server has to know which owner each belongs to.
"""

import enum

from app.modules.onboarding.domain.storage import DocumentScanStatus

__all__ = [
    "DocumentCategory",
    "DocumentOwnerKind",
    "DocumentScanStatus",
    "DocumentSource",
]


class DocumentOwnerKind(str, enum.Enum):
    """What a category may be filed against.

    Architecture §3.4's "Belongs to" column, as a value the server can check. A
    category with ``BOTH`` is legal on either owner; the others are legal on one.
    """

    COMPANY = "COMPANY"
    DEAL = "DEAL"
    BOTH = "BOTH"


class DocumentCategory(str, enum.Enum):
    """The ten fixed categories — architecture §3.4, checked by the server.

    Fixed, unlike types, because each one carries a rule: which owner it may be
    filed against. A free-text category could not answer that, and "stops people
    filing in the wrong category" is the stated reason ``OTHER`` exists at all.
    """

    #: Company: incorporation certificate, PAN, GSTIN, IEC, board resolution,
    #: owner declaration, director ID.
    ENTITY_KYC = "ENTITY_KYC"
    #: Company: sanctions, politically-exposed-person and adverse-media evidence.
    COMPLIANCE_SCREENING = "COMPLIANCE_SCREENING"
    #: Company: generated analysis. Nothing writes into it in the prototype
    #: — the category exists so the later generator has a home.
    COMPANY_MARKET_REVIEW = "COMPANY_MARKET_REVIEW"
    #: Deal: proforma invoice, purchase order, sales contract, letter of credit.
    PRE_SHIPMENT = "PRE_SHIPMENT"
    #: Deal: bill of lading or e-bill of lading, packing list, vessel report.
    SHIPPING = "SHIPPING"
    #: Deal: shipping bill, customs declaration, GST returns, tax residency.
    CUSTOMS_AND_REGULATORY = "CUSTOMS_AND_REGULATORY"
    #: Deal: buyer rating report, buyer KYC.
    BUYER = "BUYER"
    #: Both: company bank statements, and per-deal FIRC and e-BRC.
    BANKING = "BANKING"
    #: Both: annual policy, and per-shipment marine certificate.
    INSURANCE = "INSURANCE"
    #: Both: anything else.
    OTHER = "OTHER"

    @property
    def owner_kind(self) -> DocumentOwnerKind:
        return _OWNER_KINDS[self]

    def allows(self, owner: DocumentOwnerKind) -> bool:
        """Whether this category may be filed against ``owner``.

        ``BOTH`` categories allow either; the rest allow exactly one. Asked by the
        service before a row is written, and by the catalogue route so a screen can
        offer only the categories valid where the user is.
        """
        return self.owner_kind in (DocumentOwnerKind.BOTH, owner)


_OWNER_KINDS: dict[DocumentCategory, DocumentOwnerKind] = {
    DocumentCategory.ENTITY_KYC: DocumentOwnerKind.COMPANY,
    DocumentCategory.COMPLIANCE_SCREENING: DocumentOwnerKind.COMPANY,
    DocumentCategory.COMPANY_MARKET_REVIEW: DocumentOwnerKind.COMPANY,
    DocumentCategory.PRE_SHIPMENT: DocumentOwnerKind.DEAL,
    DocumentCategory.SHIPPING: DocumentOwnerKind.DEAL,
    DocumentCategory.CUSTOMS_AND_REGULATORY: DocumentOwnerKind.DEAL,
    DocumentCategory.BUYER: DocumentOwnerKind.DEAL,
    DocumentCategory.BANKING: DocumentOwnerKind.BOTH,
    DocumentCategory.INSURANCE: DocumentOwnerKind.BOTH,
    DocumentCategory.OTHER: DocumentOwnerKind.BOTH,
}


class DocumentSource(str, enum.Enum):
    """Where a document came from — architecture §3.4.

    Stored as given, and never rewritten: the same guarantee the verification
    provider has ("a result recorded with provider RXIL is never observable as
    Internal"). The storage key's fourth segment is this value, lowercased.
    """

    #: Arrived in an RXIL package.
    RXIL = "RXIL"
    #: Sent by the exporter, uploaded by staff.
    EXPORTER_UPLOAD = "EXPORTER_UPLOAD"
    #: Produced inside ANER by a person.
    INTERNAL = "INTERNAL"
    #: Generated. Nothing generates in the prototype.
    SYSTEM = "SYSTEM"
