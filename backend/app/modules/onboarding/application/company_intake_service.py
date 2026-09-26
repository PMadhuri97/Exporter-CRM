"""``PartnerIntakeService`` — a company handed over by a partner, created or
matched and recorded as qualified by that partner (L2-12). **Owner:
Developer 2.**

Knows nothing about any partner's format. The RXIL adapter
(``infrastructure/rxil/company_package.py``) translates a package into a
``PartnerCompanyIntake``; this service does the same thing for any partner:

1. **Repeated delivery.** When the partner's format carries its own delivery
   id (``external_reference``), it is kept on the outcome's history row, and a
   delivery whose id is already there returns the company it produced and
   changes nothing. (The platform idempotency registry is not used: every key
   type it accepts is built on a UUID v4, and a partner's own id is not one —
   registering it would mean inventing a key.) With or without an id, the
   steps below are themselves repeat-safe: the PAN finds the same company, an
   already-``QUALIFIED`` company is left alone, and the company row is locked
   while a decision is recorded, so two concurrent deliveries cannot both
   record one.
2. **Match** with ``CompanyMatcher`` — the CRM's one matching algorithm.
   ``POSSIBLE_DUPLICATE`` or ``CONFLICT`` is refused (409) with the companies
   involved: the delivery is neither merged into one of them nor created as
   another.
3. **Create or reuse the company.** A new company is created through
   ``ExporterProfileService.create_or_get_profile`` — the same rules as manual
   creation — as a ``LEAD`` with source ``RXIL``. A lost race on the PAN
   re-matches instead of failing.
4. **Record the partner's qualification** with
   ``QualificationService.record_partner_decision``: its results and its
   outcome, exactly as supplied, in one transaction, which moves the ``LEAD``
   to ``PROSPECT``. A company already ``QUALIFIED`` is left as it is — the
   decision is final (A2) and history is never rewritten.

Steps 3 and 4 are two commits, each atomic with its own history rows. The
company in between is a ``LEAD`` with no qualification — a state every
invariant allows — and a repeated delivery finishes the job: it matches the
company by its PAN and records the decision it is missing. No transaction
policy beyond what the services already do is assumed (decision U4 stays
open).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.company_matching import CompanyMatcher
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.domain.company_intake import (
    MatchKind,
    PartnerCompanyIntake,
    Reason,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.qualification_enums import (
    QualificationSource,
    QualificationState,
)
from app.modules.onboarding.exceptions import (
    DuplicatePanError,
    IntakeNeedsReviewError,
    PartnerPackageInvalidError,
    QualificationClosedError,
)
from app.modules.onboarding.infrastructure.repositories.qualification_repository import (
    QualificationRepository,
)

logger = structlog.get_logger(__name__)

#: Which company `source` a partner's companies are created with.
_COMPANY_SOURCE = {QualificationSource.RXIL: ExporterSource.RXIL}


@dataclass(frozen=True)
class IntakeResult:
    customer_id: uuid.UUID
    #: `created` or `matched`.
    company: str
    #: `recorded`, or `already_qualified` when the company was qualified before.
    qualification: str
    #: True when this exact delivery had already been processed.
    replayed: bool = False
    warnings: tuple[Reason, ...] = ()


class PartnerIntakeService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def ingest(self, intake: PartnerCompanyIntake, *, actor_id: str | None) -> IntakeResult:
        partner = intake.source.value
        company_source = _COMPANY_SOURCE.get(intake.source)
        if company_source is None:
            raise PartnerPackageInvalidError(
                partner, [{"code": "UNSUPPORTED_PARTNER", "message": f"no intake for {partner}"}]
            )
        if intake.identity.pan is None and not intake.identity.gstins:
            raise PartnerPackageInvalidError(
                partner,
                [{
                    "code": "MISSING_TAX_IDENTIFIER",
                    "message": "a partner delivery must carry a PAN or at least one GSTIN, "
                    "so a repeated delivery finds the same company",
                }],
            )

        if intake.external_reference is not None:
            earlier = await QualificationRepository(self._db).company_for_partner_reference(
                intake.source.value, intake.external_reference
            )
            if earlier is not None:
                logger.info(
                    "partner_intake.replayed",
                    partner=partner,
                    external_reference=intake.external_reference,
                )
                return IntakeResult(
                    customer_id=earlier,
                    company="matched",
                    qualification="already_qualified",
                    replayed=True,
                )

        customer_id, company, warnings = await self._create_or_match(intake, company_source, actor_id)

        profile = await ExporterProfileService(self._db)._require_profile(customer_id)
        qualification = "already_qualified"
        if profile.qualification is not QualificationState.QUALIFIED:
            try:
                await QualificationService(self._db).record_partner_decision(
                    customer_id,
                    intake.qualification,
                    source=intake.source,
                    actor_id=actor_id,
                    partner_reference=intake.external_reference,
                )
                qualification = "recorded"
            except QualificationClosedError:
                # A concurrent delivery qualified it first; the row lock made
                # us wait and then see it. Nothing more to do.
                await self._db.rollback()

        logger.info(
            "partner_intake.ok",
            partner=partner,
            customer_id=str(customer_id),
            company=company,
            qualification=qualification,
            actor_id=actor_id,
        )
        return IntakeResult(
            customer_id=customer_id,
            company=company,
            qualification=qualification,
            warnings=warnings,
        )

    async def _create_or_match(
        self, intake: PartnerCompanyIntake, company_source: ExporterSource, actor_id: str | None
    ) -> tuple[uuid.UUID, str, tuple[Reason, ...]]:
        for _attempt in range(2):
            match = await CompanyMatcher(self._db).match(intake.identity)
            if match.kind is MatchKind.MATCHED:
                return match.customer_id, "matched", match.warnings  # type: ignore[return-value]
            if match.kind is not MatchKind.NEW:
                raise IntakeNeedsReviewError(
                    [{"code": r.code, "message": r.message} for r in match.reasons],
                    [str(c) for c in match.candidates],
                )
            identity = intake.identity
            try:
                profile, _created = await ExporterProfileService(self._db).create_or_get_profile(
                    uuid.uuid4(),
                    source=company_source,
                    name=identity.name,
                    country=identity.country,
                    pan=identity.pan,
                    gstins=list(identity.gstins),
                    iec=identity.iec,
                    cin=identity.cin,
                    industry=intake.industry,
                    website=intake.website,
                    actor_id=actor_id,
                    history_source=f"partner_intake.{intake.source.value.lower()}",
                )
            except DuplicatePanError:
                # Another delivery created this PAN between our match and our
                # insert: match again, and this time find it.
                continue
            return profile.customer_id, "created", match.warnings
        raise IntakeNeedsReviewError(
            [{"code": "CONCURRENT_INTAKE", "message": "the company changed while being matched"}],
            [],
        )


__all__ = ["IntakeResult", "PartnerIntakeService"]
