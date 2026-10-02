"""Which paperwork a deal must have before handover — **owner: Developer 2**
(plan P2-5a and P2-5b, allocation tasks 2.2 and 2.3).

Contract: ``docs/contracts/deal-and-buyer.md`` §6.1 condition 3. Table:
``domain/entities/deal_required_document.py``, migration 0030.

Two jobs, deliberately in one file because they are two readings of one table:

* **The setting** — ADMIN adds and removes requirements
  (``GET/POST /settings/deal-required-documents``). Append-only and versioned, so
  a removal is a new version rather than a delete and the history of what was
  required when survives.
* **The policy** — :class:`DealRequiredDocumentsPolicy` answers the handover
  guard's condition 3: which required categories this deal has no document for.
  It satisfies ``handover_conditions.RequiredDocumentsPolicy`` structurally, so
  ``DealService`` injects it without either module importing the other's class.

Only ``AVAILABLE`` documents count (IQ-10's companion answer, IQ-11). A
``PENDING_SCAN`` upload is not evidence yet and a ``QUARANTINED`` or
``SCAN_FAILED`` one never will be — "we have not scanned it" and "it is clean"
must not collapse into the same outcome, the same rule the download route applies.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.deal_required_document import (
    ANY_DOCUMENT_TYPE,
    DealRequiredDocument,
)
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentOwnerKind,
)
from app.modules.onboarding.domain.storage import DocumentScanStatus
from app.modules.onboarding.exceptions import (
    DealRequiredDocumentChangedError,
    DocumentTypeNotAllowedError,
)
from app.modules.onboarding.infrastructure.document_type_loader import is_valid_type
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The scan verdict a document must carry to satisfy a requirement (IQ-11).
_COUNTS = DocumentScanStatus.AVAILABLE


class DealRequiredDocumentsService:
    """Read and change the requirements. One transaction per write, like every
    other service here."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Read ─────────────────────────────────────────────────────────────────

    async def current(self) -> list[DealRequiredDocument]:
        """The requirements as they stand: the highest version of each
        ``(category, document_type)`` key, **including** the ones whose latest
        version is ``active = False``.

        Inactive keys are returned rather than filtered out because the Settings
        screen needs to show that a requirement was removed, not merely that it is
        absent — and :meth:`add` has to know the key's current version to write
        the next one. :meth:`active` is the filtered read the guard uses.
        """
        latest = (
            select(
                DealRequiredDocument.category.label("category"),
                DealRequiredDocument.document_type.label("document_type"),
                func.max(DealRequiredDocument.version).label("version"),
            )
            .group_by(DealRequiredDocument.category, DealRequiredDocument.document_type)
            .subquery()
        )
        rows = await self._db.scalars(
            select(DealRequiredDocument)
            .join(
                latest,
                (DealRequiredDocument.category == latest.c.category)
                & (DealRequiredDocument.document_type == latest.c.document_type)
                & (DealRequiredDocument.version == latest.c.version),
            )
            # A stable order, so two reads of an unchanged setting agree and the
            # guard's message does not reshuffle between them.
            .order_by(DealRequiredDocument.category, DealRequiredDocument.document_type)
        )
        return list(rows)

    async def active(self) -> list[DealRequiredDocument]:
        """Only the requirements in force now."""
        return [row for row in await self.current() if row.active]

    async def history(self) -> list[DealRequiredDocument]:
        """Every version ever written, newest first — what the Settings screen
        shows as the record of changes."""
        rows = await self._db.scalars(
            select(DealRequiredDocument).order_by(
                DealRequiredDocument.category,
                DealRequiredDocument.document_type,
                DealRequiredDocument.version.desc(),
            )
        )
        return list(rows)

    # ── Write ────────────────────────────────────────────────────────────────

    async def set_requirement(
        self,
        *,
        category: DocumentCategory,
        document_type: str | None,
        active: bool,
        actor_id: str | None,
    ) -> DealRequiredDocument:
        """Add a requirement (``active=True``) or stop requiring it
        (``active=False``), as a new version of its key.

        Refused, before anything is written:

        * a category a deal cannot hold (422) — ``ENTITY_KYC`` belongs to a
          company, so requiring it of a deal would be a rule no deal could ever
          satisfy;
        * requiring a ``document_type`` the settings do not configure under that
          category (422 ``DOCUMENT_TYPE_NOT_ALLOWED``, the upload route's own
          refusal) — the upload route refuses that type, so a deal could never
          meet the requirement and every handover would be blocked by a typo.
          Only on the way **in**: stopping a requirement whose type has since left
          the settings must stay possible, or it could never be removed;
        * a change that would not change anything (422), because an append-only
          table should not fill up with versions that say what the previous one
          said. A key that was never required is already "not required".

        Two administrators changing the same key at once both compute the same next
        version; ``uq_deal_required_document_key_version`` lets one in and the
        other gets 409 ``DEAL_REQUIRED_DOCUMENT_CHANGED`` with nothing saved, the
        way a qualification criterion's version race is answered.
        """
        cleaned_type = (document_type or "").strip() or ANY_DOCUMENT_TYPE
        if not category.allows(DocumentOwnerKind.DEAL):
            raise ValidationError(
                f"{category.value} is filed against a company, not a deal, "
                "so a deal cannot be required to have one"
            )
        if (
            active
            and cleaned_type != ANY_DOCUMENT_TYPE
            and not is_valid_type(category, cleaned_type)
        ):
            raise DocumentTypeNotAllowedError(category.value, cleaned_type)

        existing = next(
            (
                row
                for row in await self.current()
                if row.category is category and row.document_type == cleaned_type
            ),
            None,
        )
        currently_required = existing is not None and existing.active
        if currently_required == active:
            raise ValidationError(
                f"{_key_label(category, cleaned_type)} is already "
                f"{'required' if active else 'not required'}"
            )

        version = 1 if existing is None else existing.version + 1
        row = DealRequiredDocument(
            category=category,
            document_type=cleaned_type,
            version=version,
            active=active,
            created_by=actor_id,
            source="settings_api",
        )
        self._db.add(row)
        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            raise DealRequiredDocumentChangedError(
                _key_label(category, cleaned_type), version
            ) from None
        await self._db.refresh(row)

        logger.info(
            "deal_required_document.set.ok",
            category=category.value,
            document_type=cleaned_type or None,
            version=row.version,
            active=active,
            actor_id=actor_id,
        )
        return row


class DealRequiredDocumentsPolicy:
    """The handover guard's condition 3 (plan P2-5b).

    Satisfies ``handover_conditions.RequiredDocumentsPolicy`` structurally — it
    does not import that protocol, so the deal lane's guard and this
    implementation stay independently replaceable.

    Holds the same session the guard runs in, so what it reads is what the
    handover's transaction sees.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._requirements = DealRequiredDocumentsService(db)

    async def missing_for_deal(self, deal_id: uuid.UUID) -> tuple[str, ...]:
        """The required categories this deal has no ``AVAILABLE`` document for,
        named as the guard will report them.

        One query for the requirements and one for the deal's categories, rather
        than one per requirement: the number of requirements is small but the
        guard runs on every deal-page load, and a loop of queries there would be
        a cost nobody asked for.

        A requirement naming a specific ``document_type`` is satisfied only by a
        document of that type; one with ``''`` is satisfied by any document in the
        category.
        """
        required = await self._requirements.active()
        if not required:
            # The common case on a database nobody has configured, and the reason
            # `NoRequiredDocuments` stays the right answer rather than being
            # replaced by it: no requirements means no query against the deal.
            return ()

        # `execute`, not `scalars`: this selects a pair per row, and `scalars`
        # would keep only the category.
        rows = await self._db.execute(
            select(CrmDocument.category, CrmDocument.document_type).where(
                CrmDocument.deal_id == deal_id,
                CrmDocument.scan_status == _COUNTS,
            )
        )
        present = {(category, document_type) for category, document_type in rows}
        categories_present = {category for category, _ in present}

        missing = [
            _label(row)
            for row in required
            if (
                row.document_type == ANY_DOCUMENT_TYPE
                and row.category not in categories_present
            )
            or (
                row.document_type != ANY_DOCUMENT_TYPE
                and (row.category, row.document_type) not in present
            )
        ]
        return tuple(missing)


def _label(row: DealRequiredDocument) -> str:
    """How one unmet requirement reads in the guard's message: the category, and
    the type too when the requirement names one."""
    return _key_label(row.category, row.document_type)


def _key_label(category: DocumentCategory, document_type: str) -> str:
    """One requirement key as a person reads it — the same words the guard uses."""
    if document_type == ANY_DOCUMENT_TYPE:
        return category.value
    return f"{category.value} ({document_type})"


__all__ = ["DealRequiredDocumentsPolicy", "DealRequiredDocumentsService"]
