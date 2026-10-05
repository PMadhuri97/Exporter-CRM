"""``CompanyDirectoryService`` — the implementation of ``CompanyDirectory``.

Interface and the meaning of each answer: ``domain/company_directory.py``.

How ``match`` decides
---------------------
In order, because the degrees of confidence differ:

#. **An exact identifier names the company.** A full PAN, GSTIN or
   ``(country, registration number)`` is an identity, so one company holding it is
   ``MATCHED``. A partial or prefix search is never accepted — see the disclosure
   rule below.
#. **Disagreeing identifiers are a ``CONFLICT``**, never resolved by picking one.
   Two companies holding one GSTIN gives the same answer (GSTINs stay
   warn-only, so this really happens, and the RM chooses between them).
#. **Only then, the name.** Companies in the same country whose names differ just
   in punctuation, spacing, case or legal form are ``POSSIBLE_DUPLICATE`` —
   candidates for a person, never a match (``domain/company_names.py`` explains
   why this is equality after normalisation rather than a similarity score).
#. Nothing at all: ``NEW``.

A name never overrides an identifier: if a PAN named a company, that is the answer,
and a different company with a similar name is not even reported. Mixing the two
would let a near-match on a name cast doubt on an identity.

Identifier disclosure, and why the audit lives here
---------------------------------------------------
A masked role may submit a **full** identifier and be told which company holds it;
the identifiers themselves stay masked in the response (the route's job), and
partial search stays refused (``IdentifierSearchNotPermittedError``, on the list
route). That is a deliberate disclosure, so **every identifier lookup is audited**:
who asked, when, with which kind of identifier, and which company it named.

The audit is written here rather than in the route because this is the only place
that knows an identifier was actually *used* to look something up. It is written
whether or not anything matched — a lookup that found nothing still answers "no
company holds this", which is precisely what a probe would be asking — and it
never carries the identifier's value, since recording a PAN in the table built to
watch who saw PANs would defeat the point.

``create_buyer_company`` writes through ``ExporterProfileService.create_or_get_profile``
rather than inserting a row: that path owns the identifier validation, the GSTIN rules,
the idempotency key and the first history row. The only thing this service adds is what
makes the company a *buyer*: ``source = DEAL_BUYER``,
``pipeline_status = NOT_IN_PIPELINE`` (so it is not a lead), ``created_via``
and ``created_via_deal_id``.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.company_directory import (
    BuyerCompanyDraft,
    MatchKind,
    MatchResult,
)
from app.modules.onboarding.domain.company_identity import CreatedVia
from app.modules.onboarding.domain.company_names import name_key
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.infrastructure.repositories.exporter_profile_repository import (
    ExporterProfileRepository,
)

logger = structlog.get_logger(__name__)

#: How `created_via` records a company the buyer migration or the deal screen made.
#: Kept as a name here because this module is where the value is written; the list
#: of channels lives in `domain/company_identity.py`.
CREATED_VIA_DEAL_BUYER = CreatedVia.DEAL_BUYER.value


class CompanyDirectoryService:
    """Reads and one write, on the caller's session."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._profiles = ExporterProfileRepository(db)

    # ── match ────────────────────────────────────────────────────────────────

    async def match(
        self,
        *,
        name: str,
        country: str,
        pan: str | None = None,
        gstin: str | None = None,
        registration_number: str | None = None,
        actor_role: str | None = None,
        actor_id: str | None = None,
    ) -> MatchResult:
        """Which company this is. Never writes a company; the module docstring has
        the order of confidence and what is audited.

        ``actor_role`` and ``actor_id`` are recorded on the audit row for an
        identifier lookup. They do not change the answer: what a caller may
        be *told* is the route's decision, and narrowing the match itself by role
        would mean two users disagreeing about which company a PAN belongs to.
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
            # One company per `(country, normalised registration number)`, matched
            # through the unique index's own expression so this finds exactly the row
            # an insert would collide with.
            holder = await self._profiles.get_by_registration_number(
                country=country, registration_number=registration_number
            )
            if holder is not None:
                found["registration number"] = {holder.customer_id}

        if pan or gstin or registration_number:
            await self._audit_identifier_lookup(
                kinds=[
                    label
                    for label, given in (
                        ("PAN", pan),
                        ("GSTIN", gstin),
                        ("registration number", registration_number),
                    )
                    if given
                ],
                country=country,
                found=found,
                actor_role=actor_role,
                actor_id=actor_id,
            )

        if not found:
            # No identifier named a company — or none was given. Now, and only now,
            # the name is worth looking at.
            return await self._by_name(name=name, country=country)

        named = {company_id for holders in found.values() for company_id in holders}
        candidates = tuple(sorted(named, key=str))

        if len(named) > 1:
            # Either one identifier is held by two companies, or two identifiers name
            # different companies. Both need a person; picking one would
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

    async def identity_completion(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ExporterProfile], int]:
        """The companies the CRM cannot identify yet: ``identity_type`` is ``NULL``,
        so they hold neither a PAN nor a registration number (the identity completion
        list). Returns ``(companies, total)``.

        Ordered by what the rules require first — a missing country, then a foreign
        company's missing registration number, then an Indian company's missing PAN —
        and oldest first within each, so the list is worked from the top. Ended
        companies are left out. A company leaves the list the moment an edit gives it
        an identifier, because ``update_profile`` recomputes ``identity_type``.
        """
        country = func.upper(func.coalesce(ExporterProfile.country, ""))
        urgency = case(
            (country == "", 0),
            (country != "IN", 1),
            else_=2,
        )
        conditions = (
            ExporterProfile.identity_type.is_(None),
            ExporterProfile.marker != ExporterMarker.ENDED,
        )
        total = int(
            await self._db.scalar(
                select(func.count()).select_from(ExporterProfile).where(*conditions)
            )
            or 0
        )
        rows = await self._db.scalars(
            select(ExporterProfile)
            .where(*conditions)
            .order_by(urgency, ExporterProfile.created_at, ExporterProfile.customer_id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total

    async def _by_name(self, *, name: str, country: str) -> MatchResult:
        """``POSSIBLE_DUPLICATE`` for companies in this country whose name differs
        only in punctuation, spacing, case or legal form; otherwise ``NEW``.

        Compared in Python over the country's companies rather than in SQL: the key
        is a normalisation the database has no index for, and keeping one definition
        of it (``domain/company_names.py``) matters more here than a query plan — a
        SQL expression that normalised differently would make the matcher and the
        reviewer disagree about what they are looking at.

        **Cost, measured.** Two columns for every company in the country, normalised
        in process: 40–250 ms against 4,700 companies (most of them ``IN``) on a
        developer machine, and it grows linearly. Fine now and for a while; past
        roughly 50,000 companies in one country it wants an index, which means
        storing the key — an ``exporter_profile.name_key`` column maintained by the
        same function, or a functional index whose expression is generated from
        ``company_names`` rather than hand-written. Either keeps the one definition;
        a hand-written SQL expression would not, which is the thing to avoid.
        """
        key = name_key(name)
        if not key:
            return MatchResult(MatchKind.NEW)

        rows = await self._db.execute(
            select(ExporterProfile.customer_id, ExporterProfile.name).where(
                ExporterProfile.country == country.strip().upper(),
                ExporterProfile.name.isnot(None),
            )
        )
        similar = sorted(
            (row.customer_id for row in rows if name_key(row.name) == key), key=str
        )
        if not similar:
            return MatchResult(MatchKind.NEW)
        counted = "1 company" if len(similar) == 1 else f"{len(similar)} companies"
        return MatchResult(
            MatchKind.POSSIBLE_DUPLICATE,
            candidates=tuple(similar),
            reason=(
                f"{counted} in {country.strip().upper()} already named this, "
                "ignoring punctuation and legal form"
            ),
        )

    async def _audit_identifier_lookup(
        self,
        *,
        kinds: list[str],
        country: str,
        found: dict[str, set[uuid.UUID]],
        actor_role: str | None,
        actor_id: str | None,
    ) -> None:
        """Record that somebody looked a company up by an identifier.

        Carries which *kind* of identifier was used, never its value: recording a
        PAN in the table built to watch who saw PANs would defeat the point, and the
        companies it named are enough to reconstruct what was learned.

        Written whether or not anything matched, because "no company holds this PAN"
        is also an answer.
        """
        matched = sorted({str(c) for holders in found.values() for c in holders})
        await AuditService(self._db).record(
            "company_directory.identifier_lookup",
            actor_id=_as_uuid(actor_id),
            actor_type=actor_type_for_role(actor_role),
            payload={
                "identifier_kinds": kinds,
                "country": country.strip().upper(),
                "matched_company_ids": matched,
                "matched": bool(matched),
                "actor_role": actor_role,
            },
        )

    # ── create_buyer_company (complete) ─────────────────────────────────────

    async def create_buyer_company(
        self,
        draft: BuyerCompanyDraft,
        *,
        actor_id: str | None,
        history_event_type: str | None = None,
        history_details: dict | None = None,
    ) -> uuid.UUID:
        """Create a company for a buyer, and return its ``customer_id``.

        Written through ``ExporterProfileService`` so the identifier rules, the GSTIN
        checks and the first history row are the ones every other create path gets.
        What makes it a *buyer* is set here: ``DEAL_BUYER``, ``NOT_IN_PIPELINE``, and
        where it came from.

        **Idempotent by the deal it came from.** The key is the deal id when there is
        one, so the buyer migration can be re-run without creating a second company
        for the same buyer ("re-run creates nothing"). A draft with no deal falls
        back to a fresh key, because there is nothing stable to key on.

        **The buyer's contact details become a contact record**, in the same
        transaction as the company: a draft's email and phone
        were otherwise dropped. Not the primary contact: nobody chose a person, and the
        record carries only what the deal's buyer details held (``BUYER_CONTACT_ROLE``).

        ``history_event_type`` and ``history_details`` name the creation row for a
        caller with more to say than "created" — the buyer migration writes §17.2's
        ``company_created_from_deal_buyer`` with its run, its rows and its rule.
        Without them the row is the plain ``pipeline_initial`` it always was.
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
            registration_number=draft.registration_number,
            # The foreign-identity rule's one exception: a migrated buyer may be nothing but a name and
            # a country, so this path asks for the rule to be waived rather than
            # inventing a number to satisfy it.
            allow_missing_registration_number=True,
            # No journey row. Nobody is selling to this company: it
            # exists because it was somebody's buyer. Its journey history begins
            # if and when it is brought into the pipeline, and a
            # `LEAD` row written now would claim a sales process that never
            # started. The `journey` *column* still reads LEAD, because it is
            # NOT NULL and `ck_exporter_profile_not_in_pipeline_start` requires
            # it; that is the column satisfying a constraint, not a history.
            start_journey_history=False,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            history_source="company_directory.create_buyer_company",
        )

        if created:
            # The buyer-specific facts, in the same transaction as the create. Set here
            # rather than passed through `create_or_get_profile`, because they are this
            # path's meaning and not every create path's.
            profile.pipeline_status = CompanyPipelineStatus.NOT_IN_PIPELINE
            profile.created_via_deal_id = draft.created_via_deal_id
            # `created_via`, `registration_number` and `identity_type` are set by
            # `create_or_get_profile` from `history_source` and the identifiers
            # given; only the deal link is this path's alone.
            #
            # The one history row this company starts with, in place of the journey
            # row it does not get: how it came to exist, on the dimension that
            # describes being outside the pipeline.
            details = {"source_ref": draft.source_ref} if draft.source_ref else {}
            details.update(history_details or {})
            await HistoryService(self._db).record(
                profile.customer_id,
                dimension=history_dimensions.PIPELINE,
                to_value=CompanyPipelineStatus.NOT_IN_PIPELINE.value,
                actor_id=actor_id,
                source="company_directory.create_buyer_company",
                deal_id=draft.created_via_deal_id,
                details=details or None,
                event_type=history_event_type,
            )
            if draft.contact_email or draft.contact_phone:
                self._db.add(
                    buyer_contact(
                        profile.customer_id,
                        name=name,
                        email=draft.contact_email,
                        phone=draft.contact_phone,
                    )
                )
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


#: Staff roles: what `ActorType.COMPLIANCE_OFFICER` means. Its own definition is "internal
#: staff acting with privileged authority (any role-gated back-office endpoint, incl.
#: OPERATIONS/ADMIN)" — a class of principal, not the user's role, which the audit row
#: records separately (`actor_role`).
_STAFF_ROLES = frozenset({"OPERATIONS", "COMPLIANCE", "ADMIN"})


def actor_type_for_role(role: str | None) -> ActorType:
    """The audit `ActorType` for a caller with this role, by the audit module's own
    definitions: staff are `COMPLIANCE_OFFICER`, an external caller
    (`API_USER`) is `API_CLIENT`, and no role at all is the platform, `SYSTEM`.

    A role outside those (DEVELOPER, which `/companies/match` refuses) is recorded as
    `API_CLIENT`: it acts without privileged authority, and claiming staff authority
    for it would be the wrong way round.
    """
    if role is None:
        return ActorType.SYSTEM
    name = getattr(role, "value", role)
    return ActorType.COMPLIANCE_OFFICER if name in _STAFF_ROLES else ActorType.API_CLIENT


#: The role a contact made from a buyer's details carries: what it is and where it came
#: from, since there is no person's name or title to give it.
BUYER_CONTACT_ROLE = "Buyer contact, from the deal's buyer details"


def buyer_contact(
    company_id: uuid.UUID, *, name: str, email: str | None, phone: str | None
) -> ExporterContact:
    """A non-primary contact holding a buyer's email and phone.

    Named after the company, because a legacy buyer row names no person; read back
    masked for OPERATIONS and DEVELOPER like every other contact. Never primary:
    ``deal-and-buyer.md`` §3.0 — inventing a primary contact would put a name in front
    of people that nobody chose.
    """
    return ExporterContact(
        customer_id=company_id,
        name=name,
        role=BUYER_CONTACT_ROLE,
        email=(email or "").strip() or None,
        phone=(phone or "").strip() or None,
        is_primary_contact=False,
    )


def _as_uuid(value: str | None) -> uuid.UUID | None:
    """The actor id as the audit table wants it. Callers inside the CRM pass a user
    id, but a migration run passes a label (``"migration"``), and an audit row with
    no actor is better than a lookup that fails because of one."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


__all__ = [
    "BUYER_CONTACT_ROLE",
    "CREATED_VIA_DEAL_BUYER",
    "CompanyDirectoryService",
    "actor_type_for_role",
    "buyer_contact",
]
