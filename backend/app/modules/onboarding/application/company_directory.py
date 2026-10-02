"""``CompanyDirectoryService`` — the F3 implementation of ``CompanyDirectory`` —
**owner: Developer 3** (allocation F3; plan P4-3, P4-6).

Interface and the meaning of each answer: ``domain/company_directory.py``.

**``create_buyer_company`` is complete; ``match`` is F3's stub.** That split is what
the allocation asks for: Developer 2's buyer migration (2.6) needs a working create,
and the full matcher — name similarity with ``pg_trgm``, the BQ-2 disclosure rule,
auditing every lookup — is task 3.10. The stub matches on **exact identifiers only**
(PAN, GSTIN, registration number) and never guesses from a name, so what it returns is
always defensible: a full identifier naming one company is a real match, and anything
else is ``NEW`` for a person to look at. It will never claim ``POSSIBLE_DUPLICATE``
until 3.10 teaches it name similarity; it *will* report ``CONFLICT``, because
disagreeing identifiers are already detectable and silently picking one would be the
worst outcome.

``create_buyer_company`` writes through ``ExporterProfileService.create_or_get_profile``
rather than inserting a row: that path owns the identifier validation, the GSTIN rules,
the idempotency key and the first history row. The only thing this service adds is what
makes the company a *buyer*: ``source = DEAL_BUYER`` (IQ-6),
``pipeline_status = NOT_IN_PIPELINE`` (so it is not a lead, plan §8), ``created_via``
and ``created_via_deal_id``.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.company_directory import (
    BuyerCompanyDraft,
    MatchKind,
    MatchResult,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyIdentityType,
    CompanyPipelineStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.infrastructure.repositories.exporter_profile_repository import (
    ExporterProfileRepository,
)

logger = structlog.get_logger(__name__)

#: How `created_via` records a company the buyer migration or the deal screen made.
CREATED_VIA_DEAL_BUYER = "deal_buyer"


def _normalised(registration_number: str) -> str:
    """The form `uq_exporter_profile_country_registration_number` compares.

    Mirrors the index's SQL expression deliberately: a lookup that normalised
    differently from the constraint would report NEW for a number the insert then
    refuses as a duplicate.
    """
    return "".join(ch for ch in registration_number if ch.isalnum()).upper()


class CompanyDirectoryService:
    """Reads and one write, on the caller's session."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._profiles = ExporterProfileRepository(db)

    # ── match (F3 stub — exact identifiers only; task 3.10 completes it) ─────

    async def match(
        self,
        *,
        name: str,
        country: str,
        pan: str | None = None,
        gstin: str | None = None,
        registration_number: str | None = None,
        actor_role: str | None = None,
    ) -> MatchResult:
        """Which company this is, on exact identifiers.

        ``name`` and ``country`` are accepted and **not** used for matching yet: task
        3.10 adds similarity. They are in the signature from F3 so the callers Developer
        2 writes now do not change then.
        """
        found: dict[str, set[uuid.UUID]] = {}

        if pan:
            holder = await self._profiles.get_by_pan(pan.strip().upper())
            if holder is not None:
                found["PAN"] = {holder.customer_id}

        if gstin:
            # The same GSTIN on two companies is allowed (decision 4) and is a warning,
            # not a constraint — so this really can return more than one.
            holders = set(
                await self._db.scalars(
                    select(ExporterGstin.customer_id).where(
                        ExporterGstin.gstin == gstin.strip().upper()
                    )
                )
            )
            if holders:
                found["GSTIN"] = holders

        if registration_number:
            holders = set(
                await self._db.scalars(
                    select(ExporterProfile.customer_id).where(
                        ExporterProfile.country == country.strip().upper(),
                        ExporterProfile.registration_number.isnot(None),
                    )
                )
            )
            # Normalised in Python rather than in SQL: the set of companies with any
            # registration number is small, and matching the index's expression here
            # keeps one definition of "the same number" (see `_normalised`).
            matching = {
                row.customer_id
                for row in await self._profiles.get_many(sorted(holders, key=str))
                if row.registration_number
                and _normalised(row.registration_number)
                == _normalised(registration_number)
            }
            if matching:
                found["registration number"] = matching

        if not found:
            return MatchResult(MatchKind.NEW)

        named = {company_id for holders in found.values() for company_id in holders}
        candidates = tuple(sorted(named, key=str))

        if len(named) > 1:
            # Either one identifier is held by two companies, or two identifiers name
            # different companies. Both need a person (IQ-8, IQ-9); picking one would
            # attach a deal to the wrong company silently.
            return MatchResult(
                MatchKind.CONFLICT,
                candidates=candidates,
                reason=(
                    "these identifiers name more than one company on file: "
                    + ", ".join(
                        f"{label} → {len(holders)}" for label, holders in sorted(found.items())
                    )
                ),
            )

        only = next(iter(named))
        return MatchResult(
            MatchKind.MATCHED,
            company_id=only,
            candidates=candidates,
            reason=f"a company on file holds this {', '.join(sorted(found))}",
        )

    # ── create_buyer_company (complete) ─────────────────────────────────────

    async def create_buyer_company(
        self, draft: BuyerCompanyDraft, *, actor_id: str | None
    ) -> uuid.UUID:
        """Create a company for a buyer, and return its ``customer_id``.

        Written through ``ExporterProfileService`` so the identifier rules, the GSTIN
        checks and the first history row are the ones every other create path gets.
        What makes it a *buyer* is set here: ``DEAL_BUYER``, ``NOT_IN_PIPELINE``, and
        where it came from.

        **Idempotent by the deal it came from.** The key is the deal id when there is
        one, so Developer 2's migration can be re-run without creating a second company
        for the same buyer (P4-6: "re-run creates nothing"). A draft with no deal falls
        back to a fresh key, because there is nothing stable to key on.
        """
        from app.modules.onboarding.application.exporter_profile_service import (
            ExporterProfileService,
        )

        name = (draft.name or "").strip()
        country = (draft.country or "").strip().upper()
        if not name:
            raise ValueError("a buyer company needs a name")
        if len(country) != 2 or not country.isalpha():
            raise ValueError("a buyer company needs a two-letter ISO-3166-1 country")

        # The deal's own id, which is a `gen_random_uuid()` v4 — the key must be a
        # valid UUID v4 (`validate_customer_key`), so a readable "deal-buyer:<id>"
        # string is refused. Safe to reuse the deal id because `register_key` scopes
        # every key by `scope_id` and `operation_type`, so this cannot collide with
        # another operation keyed on the same deal.
        #
        # A draft with no deal gets a fresh key: there is nothing stable to key on, so
        # the caller is responsible for not calling twice.
        idempotency_key = str(draft.created_via_deal_id or uuid.uuid4())

        profile, created = await ExporterProfileService(self._db).create_or_get_profile(
            uuid.uuid4(),
            source=ExporterSource.DEAL_BUYER,
            name=name,
            country=country,
            pan=draft.pan,
            gstins=list(draft.gstins) or None,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            history_source="company_directory.create_buyer_company",
        )

        if created:
            # The buyer-specific facts, in the same transaction as the create. Set here
            # rather than passed through `create_or_get_profile`, because they are this
            # path's meaning and not every create path's.
            profile.pipeline_status = CompanyPipelineStatus.NOT_IN_PIPELINE
            profile.created_via = CREATED_VIA_DEAL_BUYER
            profile.created_via_deal_id = draft.created_via_deal_id
            profile.registration_number = (draft.registration_number or "").strip() or None
            # A buyer with a PAN is an Indian company however it reached us; one with
            # a registration number is foreign. With neither, the question stays open
            # rather than being guessed (IQ-7 excuses migrated buyers).
            if draft.pan:
                profile.identity_type = CompanyIdentityType.IN_PAN
            elif profile.registration_number:
                profile.identity_type = CompanyIdentityType.FOREIGN_REG
            await self._db.commit()
            await self._db.refresh(profile)

        logger.info(
            "company_directory.create_buyer_company",
            company_id=str(profile.customer_id),
            created=created,
            deal_id=str(draft.created_via_deal_id) if draft.created_via_deal_id else None,
            source_ref=draft.source_ref,
            actor_id=actor_id,
        )
        return profile.customer_id


__all__ = ["CREATED_VIA_DEAL_BUYER", "CompanyDirectoryService"]
