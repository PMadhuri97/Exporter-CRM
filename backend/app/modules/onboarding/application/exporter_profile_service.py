"""``ExporterProfileService`` — the company record's service, mirroring
``OnboardingRequestService``'s method-per-operation style.

**Idempotency (a judgment call, asked for explicitly).**
``create_or_get_profile`` accepts an *optional* ``idempotency_key``. When the
caller supplies one, this follows ``OnboardingRequestService.
initiate_onboarding``'s exact pattern: an imperative ``register_key`` /
``complete_key`` pair from ``app.platform.idempotency.services``, with a
hand-rolled duplicate-lookup-by-cached-id, plus a savepoint + ``IntegrityError``
fallback that re-resolves the existing row via
``uq_exporter_profile_customer_id`` — two independent defences, because (as
with ``onboarding_request``) both an idempotency-key registry *and* a DB-level
uniqueness constraint exist. When the caller supplies no key, the method skips
the idempotency-registry round trip entirely and relies on the second
defence alone (the savepoint/``IntegrityError`` catch against
``uq_exporter_profile_customer_id``): ``customer_id`` uniqueness is enough to
make a same-customer retry safe, and paying for an idempotency-record insert
on every trusted, non-retrying caller (e.g. an internal Sales-entry UI) would
be pure overhead for no benefit.

The lean is toward keeping idempotency-key *support* in the method's
signature now rather than retrofitting it later: the plan names RXIL
ingestion as an untrusted, retrying caller of this exact
operation, and adding a caller-facing parameter to an already-shipped,
already-called method is a breaking signature change every existing caller
would need to be revisited for — cheaper to add the parameter once, unused by
today's trusted callers, than to widen the signature under time pressure once
RXIL lands.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.masking import mask_identifier
from app.modules.onboarding.application.background_check_reader import BackgroundCheckReader
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.company_identity import (
    CreatedVia,
    created_via_for_history_source,
    decide_identity_type,
    normalise_registration_number,
    require_foreign_registration_number,
)
from app.modules.onboarding.domain.engagement_views import (
    ExporterActivityView,
    ExporterContactView,
)
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterJourney,
    ExporterMarker,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    HISTORY_DIMENSION_JOURNEY,
    LIFECYCLE_INITIAL_EVENT,
    LIFECYCLE_TRANSITION_EVENT,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.qualification_enums import QualificationState
from app.modules.onboarding.domain.exporter_profile_views import (
    CustomerAnnouncement,
    DuplicateGstinWarning,
    ExporterProfileDetail,
    ExporterProfileListItem,
)
from app.modules.onboarding.domain.gst_states import state_code_of, state_name_of
from app.modules.onboarding.domain.tax_identifiers import (
    check_gstins_match_pan,
    normalise_cin,
    normalise_country,
    normalise_gstins,
    normalise_iec,
    normalise_name,
    normalise_pan,
)
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.modules.onboarding.exceptions import (
    CompanyAlreadyInPipelineError,
    DuplicatePanError,
    DuplicateRegistrationNumberError,
    ExporterProfileNotFoundError,
    ExporterSourceImmutableError,
    InvalidMarkerTransitionError,
)
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    ExporterContactRepository,
    ExporterProfileRepository,
)
from app.platform.idempotency.models import IdempotencyKeyType, RegistrationResultType
from app.platform.idempotency.services import complete_key, register_key
from app.shared import clock
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: Scope identifier for every idempotency record this service creates.
_SCOPE = "exporter_profile"
_OP_CREATE = "create_or_get_profile"

#: Fields ``update_profile`` refuses to touch, each for its own reason:
#: ``source`` is immutable (audit-relevant provenance — see
#: ``ExporterSourceImmutableError``); ``customer_id``/``id``/``date_added`` are
#: identity/immutable columns; the journey, the qualification gauge and the
#: marker each have their own governed write path and are never set as a
#: bare field.
_UPDATE_FORBIDDEN_FIELDS = frozenset(
    {
        "source",
        "customer_id",
        "id",
        "date_added",
        "journey",
        "qualification",
        "marker",
        "marker_reason",
        "created_at",
        "updated_at",
    }
)

#: The company fields staff may edit through `update_profile`, with
#: every change recorded in the history log. Each may be cleared except those
#: in `_NOT_CLEARABLE`.
_EDITABLE_FIELDS = frozenset(
    {
        "name",
        "country",
        "cin",
        "pan",
        "iec",
        "relationship_manager",
        "industry",
        "export_markets",
        "products",
        "year_established",
        "registration_number",
    }
)

#: A named company keeps its name and country: they can be corrected, never
#: emptied (company-record contract §2.1).
_NOT_CLEARABLE = frozenset({"name", "country"})

#: Identifiers written to the history log masked. The history read route
#: shows a row's details to every CRM reader, including roles that only ever
#: see these masked on the company itself, so a full value in the log would
#: undo the company route's masking (company-record contract §6).
#: `registration_number` joined later: masked like a CIN on the company, it had
#: been written to history in full.
_MASKED_IN_HISTORY = frozenset({"gstins", "pan", "iec", "cin", "registration_number"})

#: History dimensions and event types this service writes
#: (`docs/contracts/company-record.md` §6).
HISTORY_DIMENSION_PROFILE = "profile"
#: A company entering the sales pipeline. Taken from the one
#: list of dimensions rather than restated, so the read route's DEVELOPER rule and this
#: writer cannot disagree about the spelling.
HISTORY_DIMENSION_PIPELINE = history_dimensions.PIPELINE
PROFILE_EDIT_EVENT = "profile_transition"
HISTORY_DIMENSION_MARKER = "marker"

#: The marker moves the company-record contract allows (§3.3). `True` means a
#: reason is required. Anything absent — `ENDED` -> `PAUSED`, or a move to the
#: current value — is refused.
_MARKER_MOVES: dict[tuple[ExporterMarker, ExporterMarker], bool] = {
    (ExporterMarker.NONE, ExporterMarker.PAUSED): True,
    (ExporterMarker.NONE, ExporterMarker.ENDED): True,
    (ExporterMarker.PAUSED, ExporterMarker.ENDED): True,
    (ExporterMarker.PAUSED, ExporterMarker.NONE): False,
    (ExporterMarker.ENDED, ExporterMarker.NONE): False,
}

class ExporterProfileService:
    """Read/write access to `exporter_profile` and its detail projection."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._profiles = ExporterProfileRepository(db)
        self._contacts = ExporterContactRepository(db)
        self._activities = ExporterActivityRepository(db)
        # The shared history writer, not a repository: every history row this
        # service writes goes through the one writer all four developers use.
        self._history = HistoryService(db)

    # ── Create a named company ("Add Exporter") ─────────────────────────────

    async def create_lead(
        self,
        *,
        name: str,
        country: str,
        idempotency_key: str,
        source: ExporterSource,
        customer_id: uuid.UUID | None = None,
        cin: str | None = None,
        pan: str | None = None,
        gstins: list[str] | None = None,
        iec: str | None = None,
        relationship_manager: str | None = None,
        industry: str | None = None,
        export_markets: list[str] | None = None,
        products: list[str] | None = None,
        year_established: int | None = None,
        registration_number: str | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
    ) -> tuple[ExporterProfile, bool]:
        """Create a named company as a `LEAD`: its identity — name and
        country — is written on the company record itself (migration 0014).

        `idempotency_key` is required here: a replay returns the company the
        first call created, with `created=False`, and creates nothing.

        Returns `(profile, created)`.
        """
        return await self.create_or_get_profile(
            customer_id or uuid.uuid4(),
            source=source,
            name=name,
            country=country,
            cin=cin,
            pan=pan,
            gstins=gstins,
            iec=iec,
            relationship_manager=relationship_manager,
            industry=industry,
            export_markets=export_markets,
            products=products,
            year_established=year_established,
            registration_number=registration_number,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            actor_id=actor_id,
            history_source="exporter_profile_service.create_lead",
        )

    # ── Create ────────────────────────────────────────────────────────────

    async def create_or_get_profile(
        self,
        customer_id: uuid.UUID,
        *,
        source: ExporterSource,
        name: str | None = None,
        country: str | None = None,
        cin: str | None = None,
        pan: str | None = None,
        gstins: list[str] | None = None,
        iec: str | None = None,
        relationship_manager: str | None = None,
        industry: str | None = None,
        export_markets: list[str] | None = None,
        products: list[str] | None = None,
        year_established: int | None = None,
        registration_number: str | None = None,
        allow_missing_registration_number: bool = False,
        start_journey_history: bool = True,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
        history_source: str = "exporter_profile_service.create_or_get_profile",
    ) -> tuple[ExporterProfile, bool]:
        """Create an exporter_profile, or return the one already on file.

        Returns ``(profile, created)``; ``created`` is False on an idempotent
        replay or when a profile for this ``customer_id`` already existed.
        See the module docstring for when the ``idempotency_key`` round trip
        runs versus when this relies on ``uq_exporter_profile_customer_id``
        alone.

        Tax identifiers are normalised and checked before anything is written
        (`domain/tax_identifiers.py`): a malformed PAN, GSTIN or CIN, or a
        GSTIN that does not carry the PAN, is a 422. A PAN another company
        already holds is refused with `DuplicatePanError` (409) — never
        merged. A GSTIN another company holds is allowed and reported by
        `duplicate_gstin_warnings`.

        Every company starts as a ``LEAD`` with a ``journey`` history row;
        the journey moves only through qualification (and, later, the
        background check), never by a field a caller sets.
        """
        name = normalise_name(name)
        country = normalise_country(country)
        pan = normalise_pan(pan)
        cin = normalise_cin(cin)
        iec = normalise_iec(iec)
        registration_number = normalise_registration_number(registration_number)
        gstin_values = normalise_gstins(gstins)
        check_gstins_match_pan(pan, gstin_values)
        # A foreign company's registration number, on every create path at once
        # rather than once per caller.
        require_foreign_registration_number(
            country=country,
            pan=pan,
            registration_number=registration_number,
            allow_missing=allow_missing_registration_number,
        )

        if idempotency_key is not None:
            reg_result = await register_key(
                session=self._db,
                key_value=idempotency_key,
                key_type=IdempotencyKeyType.CUSTOMER_KEY,
                scope_id=_SCOPE,
                operation_type=_OP_CREATE,
                correlation_id=correlation_id,
                created_by=actor_id,
            )
            if reg_result.result == RegistrationResultType.DUPLICATE:
                cached = (
                    reg_result.record.response_cache
                    if reg_result.record is not None
                    else None
                )
                if cached and cached.get("customer_id"):
                    existing = await self._profiles.get_by_customer_id(
                        uuid.UUID(cached["customer_id"])
                    )
                    if existing is not None:
                        logger.info(
                            "exporter_profile.create.idempotent_replay",
                            customer_id=str(existing.customer_id),
                            idempotency_key=idempotency_key,
                        )
                        return existing, False
                # Cache miss: fall back to the row itself, if it landed.
                existing_by_customer = await self._profiles.get_by_customer_id(customer_id)
                if existing_by_customer is not None:
                    return existing_by_customer, False

        existing = await self._profiles.get_by_customer_id(customer_id)
        if existing is not None:
            return existing, False

        await self._refuse_duplicate_pan(pan, customer_id)
        await self._refuse_duplicate_registration_number(
            registration_number, country, customer_id
        )

        profile = ExporterProfile(
            customer_id=customer_id,
            source=source,
            name=name,
            country=country,
            cin=cin,
            pan=pan,
            iec=iec,
            relationship_manager=relationship_manager,
            industry=industry,
            export_markets=export_markets,
            products=products,
            year_established=year_established,
            registration_number=registration_number,
            identity_type=decide_identity_type(
                pan=pan, registration_number=registration_number
            ),
            # The channel, derived from the one string that already names it, so this
            # and migration 0033's backfill cannot disagree.
            created_via=created_via_for_history_source(history_source),
            # The state comes from the GSTIN, here as well as on the
            # `gst-registrations` route: a registration created on this path and one
            # created there must be the same kind of row, or the branch flag reader
            # has no state to name in "the invoicing branch Maharashtra is flagged"
            # and the company page shows "Unknown state".
            gstin_rows=[
                ExporterGstin(
                    customer_id=customer_id,
                    gstin=g,
                    state_code=state_code_of(g),
                    state_name=state_name_of(g),
                )
                for g in gstin_values
            ],
        )

        try:
            async with self._db.begin_nested():
                self._db.add(profile)
                await self._db.flush()
        except IntegrityError:
            # Mirrors OnboardingRequestService.initiate_onboarding's lost-race
            # branch exactly: the losing writer's idempotency record (if any)
            # is left uncompleted rather than force-completed with someone
            # else's result — the same accepted edge case that pattern
            # already carries. A concurrent writer may instead have taken the
            # PAN (`uq_exporter_profile_pan`); that is a refusal, not a race.
            winner = await self._profiles.get_by_customer_id(customer_id)
            if winner is None:
                await self._refuse_duplicate_pan(pan, customer_id)
                await self._refuse_duplicate_registration_number(
                    registration_number, country, customer_id
                )
                raise
            logger.info(
                "exporter_profile.create.lost_race", customer_id=str(customer_id)
            )
            return winner, False

        if start_journey_history:
            await self._record_journey_start(
                customer_id, actor_id=actor_id, source=history_source
            )

        if idempotency_key is not None:
            await complete_key(
                session=self._db,
                key_value=idempotency_key,
                scope_id=_SCOPE,
                terminal_status="completed",
                response_payload={"customer_id": str(profile.customer_id)},
            )
        await self._db.commit()
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.create.ok",
            customer_id=str(profile.customer_id),
            source=source.value,
        )
        return profile, True

    # ── Update ────────────────────────────────────────────────────────────

    async def update_profile(
        self,
        customer_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        actor_id: str | None,
    ) -> ExporterProfile:
        """Edit company fields, recording every change in the history log.

        `changes` holds only the fields the caller supplied. **A field that is
        absent is left alone; a field present with `None` — or an empty string
        or empty list — is cleared** (except `name` and `country`, which can be
        corrected but not emptied). The router builds `changes` from the
        request with `exclude_unset=True`, which is what keeps the two apart.

        Identifiers are checked on the company's state *after* the edit: a new
        PAN must fit the GSTINs the company holds.

        **`gstins` is not editable here**. It used to replace the whole
        list, which deleted the row of every GSTIN dropped — and a GST registration is
        a branch the company traded through, named by any deal that invoiced from it
        (`deal.seller_gst_registration_id`). `GstRegistrationService` adds one,
        deactivates one and flags one, each as its own decision with its own history
        row. Sending `gstins` here is a 422 at the API boundary, because
        `UpdateExporterProfileRequest` no longer has the field and forbids extras.

        Each field whose value actually changes writes one `profile` history
        row through the shared `HistoryService`: `to_value` names the field,
        and `details` carries `field`, `from`, `to`, and an `edit_id` shared by
        every row of the same edit. A supplied value equal to the current one
        writes nothing. The values live in `details` rather than in
        `from_value`/`to_value` because those columns hold 64 characters and
        refuse an empty value (company-record contract §6).

        The column writes and the history rows are committed together, once,
        at the end — the writer flushes and never commits — so a company can
        never show an edit with no record of it. Everything is validated before
        the first assignment, so a refused edit leaves nothing behind.

        `actor_id` is the signed-in user, from the session. It is a separate
        keyword, never one of `changes`.

        Never touches `source` (immutable — see `ExporterSourceImmutableError`),
        the journey or the
        marker (owned by `set_marker`), nor the journey or the qualification
        gauge (owned by `QualificationService`).
        """
        if "source" in changes:
            raise ExporterSourceImmutableError(customer_id)
        forbidden = _UPDATE_FORBIDDEN_FIELDS.intersection(changes)
        if forbidden:
            raise ValidationError(
                f"update_profile cannot set {sorted(forbidden)}: use the dedicated "
                f"write path for each (qualification moves the journey; set_marker "
                f"for the marker; none for identity/immutable columns)"
            )
        unknown = set(changes) - _EDITABLE_FIELDS
        if unknown:
            raise ValidationError(
                f"update_profile cannot set {sorted(unknown)}: not an editable company field"
            )

        # Locked, so a concurrent edit waits and then sees this one: every
        # history row's `from` is the value the edit actually replaced.
        profile = await self._lock_profile(customer_id)
        wanted = {field: _cleared_to_none(value) for field, value in changes.items()}
        for field in _NOT_CLEARABLE.intersection(wanted):
            if wanted[field] is None:
                raise ValidationError(f"{field} cannot be cleared, only corrected")
        if wanted.get("name") is not None:
            wanted["name"] = normalise_name(wanted["name"])  # type: ignore[arg-type]
        if wanted.get("country") is not None:
            wanted["country"] = normalise_country(wanted["country"])  # type: ignore[arg-type]
        if "pan" in wanted:
            wanted["pan"] = normalise_pan(wanted["pan"])  # type: ignore[arg-type]
        if "cin" in wanted:
            wanted["cin"] = normalise_cin(wanted["cin"])  # type: ignore[arg-type]
        if "iec" in wanted:
            wanted["iec"] = normalise_iec(wanted["iec"])  # type: ignore[arg-type]
        if "registration_number" in wanted:
            wanted["registration_number"] = normalise_registration_number(
                wanted["registration_number"]  # type: ignore[arg-type]
            )
        check_gstins_match_pan(
            wanted.get("pan", profile.pan),  # type: ignore[arg-type]
            wanted.get("gstins", profile.gstins) or [],  # type: ignore[arg-type]
        )
        if wanted.get("pan") is not None and wanted["pan"] != profile.pan:
            await self._refuse_duplicate_pan(wanted["pan"], customer_id)  # type: ignore[arg-type]
        if (
            wanted.get("registration_number") is not None
            and wanted["registration_number"] != profile.registration_number
        ):
            await self._refuse_duplicate_registration_number(
                wanted["registration_number"],  # type: ignore[arg-type]
                wanted.get("country") or profile.country,  # type: ignore[arg-type]
                customer_id,
            )
        # The foreign-identity rule on the company as it will be, whenever the edit
        # touches what identifies it: moving a company abroad, clearing a foreign
        # company's number, or clearing the PAN that made it Indian must leave it
        # identifiable. A company the buyer migration created without a number keeps
        # the rule's exception until
        # one is added — an edit cannot meet the rule retroactively either.
        identity_fields = {"country", "pan", "registration_number"}
        if any(
            field in wanted and wanted[field] != getattr(profile, field)
            for field in identity_fields
        ):
            require_foreign_registration_number(
                country=wanted.get("country", profile.country),  # type: ignore[arg-type]
                pan=wanted.get("pan", profile.pan),  # type: ignore[arg-type]
                registration_number=wanted.get(  # type: ignore[arg-type]
                    "registration_number", profile.registration_number
                ),
                allow_missing=(
                    profile.created_via == CreatedVia.DEAL_BUYER.value
                    and profile.registration_number is None
                ),
            )

        edits: dict[str, tuple[object, object]] = {}
        for field in sorted(wanted):
            if field == "gstins":
                old_value: object = profile.gstins or None
                # A list in a different order is the same set of registrations.
                if set(wanted[field] or []) == set(profile.gstins):  # type: ignore[arg-type]
                    continue
            else:
                old_value = getattr(profile, field)
                if wanted[field] == old_value:
                    continue
            edits[field] = (old_value, wanted[field])

        edit_id = str(uuid.uuid4())
        for field, (old_value, new_value) in edits.items():
            setattr(profile, field, new_value)
            await self._history.record(
                customer_id,
                dimension=HISTORY_DIMENSION_PROFILE,
                to_value=field,
                actor_id=actor_id,
                source="exporter_profile_service.update_profile",
                event_type=PROFILE_EDIT_EVENT,
                details={
                    "field": field,
                    "from": _history_value(field, old_value),
                    "to": _history_value(field, new_value),
                    "edit_id": edit_id,
                },
            )
        # Derived from what the company holds, so it moves with the PAN and the
        # registration number. It was set on create only, and went stale on
        # exactly the edit the identity completion flow makes.
        if {"pan", "registration_number"} & set(edits):
            profile.identity_type = decide_identity_type(
                pan=profile.pan, registration_number=profile.registration_number
            )

        try:
            await self._db.commit()
        except IntegrityError:
            # A concurrent writer took the PAN or the registration number between
            # the check and the commit.
            await self._db.rollback()
            if "pan" in edits:
                await self._refuse_duplicate_pan(wanted["pan"], customer_id)  # type: ignore[arg-type]
            if "registration_number" in edits:
                await self._refuse_duplicate_registration_number(
                    wanted["registration_number"],  # type: ignore[arg-type]
                    wanted.get("country") or profile.country,  # type: ignore[arg-type]
                    customer_id,
                )
            raise
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.update.ok",
            customer_id=str(customer_id),
            changed=sorted(edits),
            actor_id=actor_id,
        )
        return profile

    # ── Marker ──────────────────────────────────────────────────────────────

    async def set_marker(
        self,
        customer_id: uuid.UUID,
        marker: ExporterMarker,
        *,
        reason: str | None,
        actor_id: str | None,
    ) -> ExporterProfile:
        """Set or clear the company's `PAUSED`/`ENDED` marker.

        The marker is a commercial state beside the journey, never a journey
        stage: this changes the marker and nothing else — not
        the journey, not any gauge (decision 3). Allowed moves and
        which of them need a reason are `_MARKER_MOVES` (company-record
        contract §3.3); anything else is `InvalidMarkerTransitionError` (409).
        Setting `PAUSED` or `ENDED` without a reason is a 422, and the
        database refuses it too (`ck_exporter_profile_marker_reason`).

        The marker, its current reason and one `marker` history row — from,
        to, reason, the signed-in user — commit together.
        """
        # Locked, so two concurrent moves are judged one after the other and
        # the second sees the first: the history never shows two moves from
        # the same marker.
        profile = await self._lock_profile(customer_id)
        from_marker = profile.marker
        needs_reason = _MARKER_MOVES.get((from_marker, marker))
        if needs_reason is None:
            raise InvalidMarkerTransitionError(customer_id, from_marker.value, marker.value)
        cleaned_reason = (reason or "").strip() or None
        if needs_reason and cleaned_reason is None:
            raise ValidationError(f"a reason is required to set the marker to {marker.value}")

        profile.marker = marker
        profile.marker_reason = cleaned_reason if marker is not ExporterMarker.NONE else None
        await self._history.record(
            customer_id,
            dimension=HISTORY_DIMENSION_MARKER,
            from_value=from_marker.value,
            to_value=marker.value,
            actor_id=actor_id,
            reason=cleaned_reason,
            source="exporter_profile_service.set_marker",
        )
        await self._db.commit()
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.set_marker.ok",
            customer_id=str(customer_id),
            from_marker=from_marker.value,
            to_marker=marker.value,
            actor_id=actor_id,
        )
        return profile

    # ── Duplicate GSTINs (warning, never refusal) ───────────────────────────

    async def duplicate_gstin_warnings(
        self, customer_id: uuid.UUID, gstins: Iterable[str]
    ) -> list[DuplicateGstinWarning]:
        """One warning per GSTIN of this company that another company also
        holds (decision 4: warn, never block). Empty when there are none."""
        holders = await self._profiles.other_holders_of_gstins(list(gstins), customer_id)
        return [
            DuplicateGstinWarning(gstin=gstin, other_customer_ids=tuple(ids))
            for gstin, ids in holders.items()
        ]

    # ── Search ────────────────────────────────────────────────────────────

    async def search_profiles(
        self,
        *,
        gstin: str | None = None,
        pan: str | None = None,
        iec: str | None = None,
        name_contains: str | None = None,
        source: ExporterSource | None = None,
        journey: ExporterJourney | None = None,
        qualification: QualificationState | None = None,
        marker: ExporterMarker | None = None,
        pipeline_status: CompanyPipelineStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfileListItem]:
        """Filtered company search.

        `name_contains` is a case-insensitive partial match on the company's
        name. `gstin` matches any of a company's GSTINs; `pan`, `gstin` and
        `iec` are normalised first, so case and surrounding spaces do not
        matter.

        **`ENDED` companies are left out of the default working list and stay
        searchable**: with no `marker` filter and no search
        term (`name_contains`, `pan`, `gstin`, `iec`), `ENDED` companies are
        excluded; any search term includes them; `marker=ENDED` lists only
        them. `source`, `journey` and `qualification` are list filters, not search
        terms, and do not bring `ENDED` companies back.

        **`NOT_IN_PIPELINE` companies follow the same rule**.
        A company that exists only because it was somebody's buyer is not a lead:
        it must not appear in the working list, or in any count drawn from it, or
        creating a buyer would silently raise this month's lead numbers. It is
        still a full company record, so a search term finds it — a person who
        types a buyer's name is looking for that buyer — and `pipeline_status=`
        lists them deliberately, which is what the identity completion list needs.

        The two exclusions are deliberately separate: `marker=ENDED` must not
        drag buyer-only companies into its list, and `pipeline_status=` must not
        resurrect `ENDED` ones.
        """
        pan = _normalise_term(pan)
        gstin = _normalise_term(gstin)
        iec = _normalise_term(iec)
        # A blank name is no search at all: it must not bring ENDED back.
        name_contains = (name_contains or "").strip() or None
        searching = any(term is not None for term in (name_contains, pan, gstin, iec))

        profiles = await self._profiles.search(
            gstin=gstin,
            pan=pan,
            iec=iec,
            name_contains=name_contains,
            source=source,
            journey=journey,
            qualification=qualification,
            marker=marker,
            pipeline_status=pipeline_status,
            exclude_ended=marker is None and not searching,
            exclude_not_in_pipeline=pipeline_status is None and not searching,
            limit=limit,
            offset=offset,
        )
        return [
            ExporterProfileListItem(
                customer_id=profile.customer_id,
                name=profile.name,
                country=profile.country,
                cin=profile.cin,
                gstins=tuple(profile.gstins),
                pan=profile.pan,
                iec=profile.iec,
                source=profile.source,
                relationship_manager=profile.relationship_manager,
                relationship_manager_user_id=profile.relationship_manager_user_id,
                journey=profile.journey,
                qualification=profile.qualification,
                marker=profile.marker,
                marker_reason=profile.marker_reason,
                industry=profile.industry,
                year_established=profile.year_established,
                registration_number=profile.registration_number,
                identity_type=profile.identity_type,
                pipeline_status=profile.pipeline_status,
                date_added=profile.date_added,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
            for profile in profiles
        ]

    # ── Journey ───────────────────────────────────────────────────────────

    async def _record_journey_start(
        self, customer_id: uuid.UUID, *, actor_id: str | None, source: str
    ) -> None:
        """The creation row of the journey dimension: `NULL` -> `LEAD`.

        Flushed, not committed — written in the creating transaction. The event
        type stays `lifecycle_initial`, the name the journey's rows have always
        had and a downstream consumer (ANER-4.2-S1T2) polls for (history
        contract §3); the values are now the three-stage journey's. `terminal`
        marks a row that reaches `CUSTOMER` — the new model's "onboarding
        completed" (architecture §5.6: `ONBOARDED` is now a `CLEAR` check and
        so `CUSTOMER`) — and is false at creation.
        """
        await self._history.record(
            customer_id,
            dimension=HISTORY_DIMENSION_JOURNEY,
            to_value=ExporterJourney.LEAD.value,
            actor_id=actor_id,
            source=source,
            event_type=LIFECYCLE_INITIAL_EVENT,
            details={"terminal": False},
        )

    # ── Into the sales pipeline ──────────────────────────────────────────────

    async def bring_into_pipeline(
        self, customer_id: uuid.UUID, *, actor_id: str | None, reason: str | None = None
    ) -> ExporterProfile:
        """Move a buyer-only company into the sales pipeline: the one way in.

        A company created as somebody's buyer is `NOT_IN_PIPELINE` and has no
        journey history — nobody was selling to it. If we decide to,
        this is what starts that: `pipeline_status` becomes `IN_PIPELINE` and the
        journey history begins at `LEAD`, exactly as it would for a company
        entered by hand. From here on it is an ordinary lead, so qualification and
        the conversation gauge stop refusing it (`CompanyNotInPipelineError`).

        Two history rows, because two different things happened: a `pipeline` row
        for the decision, and the journey's own creation row. Writing only the
        first would leave a company in the pipeline whose journey history started
        nowhere; writing only the second would lose who decided and why.

        The move is deliberately one-way here. Taking a company *out* of the
        pipeline is not its mirror image — the journey, qualification and
        conversation it has accumulated would have to go somewhere, and
        `ck_exporter_profile_not_in_pipeline_start` refuses the row until they
        do — so it needs its own decision rather than a flag flip.

        Returns the updated company.

        Raises:
            ExporterProfileNotFoundError: no such company.
            CompanyAlreadyInPipelineError: it is already in the pipeline.
        """
        profile = await self._lock_profile(customer_id)
        if profile.pipeline_status is CompanyPipelineStatus.IN_PIPELINE:
            raise CompanyAlreadyInPipelineError(customer_id)

        profile.pipeline_status = CompanyPipelineStatus.IN_PIPELINE
        await self._history.record(
            customer_id,
            dimension=HISTORY_DIMENSION_PIPELINE,
            from_value=CompanyPipelineStatus.NOT_IN_PIPELINE.value,
            to_value=CompanyPipelineStatus.IN_PIPELINE.value,
            actor_id=actor_id,
            source="exporter_profile_service.bring_into_pipeline",
            reason=reason,
        )
        # The journey starts now, not when the buyer record was created.
        await self._record_journey_start(
            customer_id,
            actor_id=actor_id,
            source="exporter_profile_service.bring_into_pipeline",
        )
        await self._db.commit()
        await self._db.refresh(profile)
        logger.info(
            "exporter_profile.brought_into_pipeline",
            customer_id=str(customer_id),
            actor_id=actor_id,
        )
        return profile

    # ── The move to CUSTOMER ─────────────────────────────────────────────────

    async def promote_to_customer_if_ready(
        self,
        profile: ExporterProfile,
        *,
        actor_id: str | None,
        cause: str,
        source: str,
    ) -> CustomerAnnouncement | None:
        """Make the company a ``CUSTOMER`` if it is a ``PROSPECT`` whose background
        check is ``CLEAR`` — whichever of the two became true second (company-record
        contract §3.2).

        **Called by the move that completes the condition, in that move's
        transaction**: the background check's
        ``CLEAR`` and qualification's ``QUALIFIED`` outcome each call this after their
        own write and before their one commit. So the company can never be seen
        ``PROSPECT`` and ``CLEAR`` at once, and a failure anywhere rolls the whole
        move back — there is no half-finished promotion to retry.

        The caller must hold the company row ``FOR UPDATE``: both callers take it
        before anything else, which is what serialises a ``CLEAR`` and a
        ``QUALIFIED`` landing on the same company at the same moment — the second
        one sees the first's result and makes the move exactly once.

        Flushes and never commits, like seam S1. Idempotent: a company already
        ``CUSTOMER`` (or not yet a ``PROSPECT``, or not ``CLEAR``) is left alone,
        and ``None`` comes back — no history row, nothing to announce. The
        background check is read through the compliance engine's published
        readers, never from its tables.

        **The Clear must be current**: the condition is
        ``ComplianceFactsReader.for_company(...).is_clear_current`` at the injectable
        clock's ``now``. A ``PROSPECT`` whose Clear has expired stays a ``PROSPECT``
        until a new Clear promotes it.

        Returns what ``company.became_customer`` should carry. The caller publishes
        it with :func:`announce_became_customer` **after** its commit.
        """
        if profile.journey is not ExporterJourney.PROSPECT:
            return None
        facts = await ComplianceFactsService(self._db).for_company(
            profile.customer_id, clock.now()
        )
        if not facts.is_clear_current:
            if facts.is_clear:
                logger.info(
                    "exporter_profile.promotion_refused_expired_clear",
                    customer_id=str(profile.customer_id),
                    clear_expires_at=(
                        facts.clear_expires_at.isoformat() if facts.clear_expires_at else None
                    ),
                )
            return None
        standing = await BackgroundCheckReader(self._db).standing(profile.customer_id)
        if standing.clearing_decision_id is None or standing.risk_rating is None:
            # Impossible by the database's own rules: a CLEAR decision carries a
            # risk (`ck_background_check_decision_clear_risk`) and is the chain head.
            # Refusing beats announcing a customer the payload cannot describe.
            raise RuntimeError(
                f"company {profile.customer_id} reads CLEAR with no clearing decision or risk"
            )

        profile.journey = ExporterJourney.CUSTOMER
        await self._history.record(
            profile.customer_id,
            dimension=HISTORY_DIMENSION_JOURNEY,
            from_value=ExporterJourney.PROSPECT.value,
            to_value=ExporterJourney.CUSTOMER.value,
            actor_id=actor_id,
            source=source,
            event_type=LIFECYCLE_TRANSITION_EVENT,
            details={
                "cause": cause,
                "clearing_decision_id": str(standing.clearing_decision_id),
                "risk_rating": standing.risk_rating,
                # CUSTOMER is the journey's end: the row a completion consumer
                # (ANER-4.2-S1T2) watches for.
                "terminal": True,
            },
        )
        logger.info(
            "exporter_profile.became_customer",
            customer_id=str(profile.customer_id),
            cause=cause,
            clearing_decision_id=str(standing.clearing_decision_id),
            actor_id=actor_id,
        )
        return CustomerAnnouncement(
            company_id=profile.customer_id,
            name=profile.name,
            country=profile.country,
            pan=profile.pan,
            gstins=tuple(profile.gstins),
            risk_rating=standing.risk_rating,
            clearing_decision_id=standing.clearing_decision_id,
            actor_id=actor_id,
        )

    # ── Allowed moves (served, never copied by the frontend) ────────────────

    @staticmethod
    def allowed_marker_moves(current: ExporterMarker) -> list[tuple[ExporterMarker, bool]]:
        """The marker moves the contract allows from `current`, each with
        whether it needs a reason — the same table `set_marker` enforces, so a
        screen asks the server instead of keeping its own copy."""
        return [
            (to_marker, needs_reason)
            for (from_marker, to_marker), needs_reason in _MARKER_MOVES.items()
            if from_marker is current
        ]

    # ── Detail ────────────────────────────────────────────────────────────

    async def get_profile_detail(
        self, customer_id: uuid.UUID, *, recent_activities_limit: int = 20
    ) -> ExporterProfileDetail:
        """The company record, its contacts and recent activities, and a
        warning for each of its GSTINs another company also holds — all
        queried by `customer_id` alone."""
        profile = await self._require_profile(customer_id)
        contacts = await self._contacts.list_by_customer(customer_id)
        activities = await self._activities.list_by_customer(
            customer_id, limit=recent_activities_limit
        )
        warnings = await self.duplicate_gstin_warnings(customer_id, profile.gstins)

        return ExporterProfileDetail(
            customer_id=profile.customer_id,
            name=profile.name,
            country=profile.country,
            cin=profile.cin,
            gstins=tuple(profile.gstins),
            pan=profile.pan,
            iec=profile.iec,
            source=profile.source,
            relationship_manager=profile.relationship_manager,
            relationship_manager_user_id=profile.relationship_manager_user_id,
            journey=profile.journey,
            qualification=profile.qualification,
            marker=profile.marker,
            marker_reason=profile.marker_reason,
            industry=profile.industry,
            export_markets=profile.export_markets,
            products=profile.products,
            year_established=profile.year_established,
            registration_number=profile.registration_number,
            identity_type=profile.identity_type,
            pipeline_status=profile.pipeline_status,
            date_added=profile.date_added,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            contacts=tuple(_contact_view(c) for c in contacts),
            recent_activities=tuple(_activity_view(a) for a in activities),
            gstin_warnings=tuple(warnings),
        )

    # ── Internals ─────────────────────────────────────────────────────────

    async def _require_profile(self, customer_id: uuid.UUID) -> ExporterProfile:
        profile = await self._profiles.get_by_customer_id(customer_id)
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile

    async def _lock_profile(self, customer_id: uuid.UUID) -> ExporterProfile:
        """The company row, locked for the rest of the transaction and read
        fresh — as `QualificationService` locks it before a decision."""
        result = await self._db.execute(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile

    async def _refuse_duplicate_pan(self, pan: str | None, customer_id: uuid.UUID) -> None:
        """Raise `DuplicatePanError` if another company already holds `pan`."""
        if pan is None:
            return
        holder = await self._profiles.get_by_pan(pan)
        if holder is not None and holder.customer_id != customer_id:
            raise DuplicatePanError(holder.customer_id)

    async def _refuse_duplicate_registration_number(
        self,
        registration_number: str | None,
        country: str | None,
        customer_id: uuid.UUID,
    ) -> None:
        """Raise `DuplicateRegistrationNumberError` if another company in this
        country already holds this registration number.

        The foreign counterpart of the duplicate-PAN refusal, and checked the same
        way: ahead of the write, so the caller is told which company holds it,
        with `uq_exporter_profile_country_registration_number` behind it for the
        concurrent case this cannot see.
        """
        if registration_number is None or not (country or "").strip():
            return
        holder = await self._profiles.get_by_registration_number(
            country=country, registration_number=registration_number
        )
        if holder is not None and holder.customer_id != customer_id:
            raise DuplicateRegistrationNumberError(holder.customer_id, country)


async def announce_became_customer(announcement: CustomerAnnouncement | None) -> None:
    """Announce ``company.became_customer`` — **after** the commit that made it true.

    Best effort, as every CRM announcement is (architecture §3.6): the history row
    written by :meth:`ExporterProfileService.promote_to_customer_if_ready` is the
    source of truth, and ``OnboardingEventPublisher`` logs and swallows its own
    failures, so a dead bus never undoes a committed promotion. Announcing before the
    commit would risk telling the customers team about a customer that then failed to
    commit. ``None`` — nothing was promoted — announces nothing.
    """
    if announcement is None:
        return
    await OnboardingEventPublisher().company_became_customer(
        company_id=announcement.company_id,
        name=announcement.name or "",
        country=announcement.country or "",
        pan=announcement.pan,
        gstins=list(announcement.gstins),
        risk_rating=announcement.risk_rating,
        clearing_decision_id=announcement.clearing_decision_id,
        actor_id=announcement.actor_id,
    )


def _normalise_term(value: str | None) -> str | None:
    """An exact-match search term, normalised like the stored value."""
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None


def _cleared_to_none(value: object) -> object:
    """An empty or whitespace-only string, or an empty list, clears the field."""
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, list) and not value:
        return None
    return value


def _history_value(field: str, value: object) -> object:
    """A field's value as the history log stores it: identifiers masked."""
    if value is None:
        return None
    if field in _MASKED_IN_HISTORY:
        if isinstance(value, list):
            return [mask_identifier(str(item)) for item in value]
        return mask_identifier(str(value))
    return value


def _contact_view(contact: ExporterContact) -> ExporterContactView:
    return ExporterContactView(
        id=contact.id,
        customer_id=contact.customer_id,
        name=contact.name,
        role=contact.role,
        email=contact.email,
        phone=contact.phone,
        department=contact.department,
        is_primary_contact=contact.is_primary_contact,
    )


def _activity_view(activity: ExporterActivity) -> ExporterActivityView:
    return ExporterActivityView(
        id=activity.id,
        customer_id=activity.customer_id,
        activity_type=activity.activity_type,
        subject=activity.subject,
        notes=activity.notes,
        actor_id=activity.actor_id,
        occurred_at=activity.occurred_at,
        due_at=activity.due_at,
        created_at=activity.created_at,
    )


__all__ = ["ExporterProfileService", "announce_became_customer"]
