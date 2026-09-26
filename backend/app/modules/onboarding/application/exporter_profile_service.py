"""``ExporterProfileService`` — EXP-1's profile-lifecycle service, mirroring
``OnboardingRequestService``'s method-per-operation style.

**Idempotency (judgment call — the ticket explicitly asks for one here).**
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
ingestion (a later ticket) as an untrusted, retrying caller of this exact
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.api.schemas.masking import mask_identifier
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.engagement_views import (
    ExporterActivityView,
    ExporterContactView,
)
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterLifecycleStatus,
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
    DuplicateGstinWarning,
    ExporterProfileDetail,
    ExporterProfileListItem,
)
from app.modules.onboarding.domain.tax_identifiers import (
    check_gstins_match_pan,
    normalise_cin,
    normalise_country,
    normalise_gstins,
    normalise_iec,
    normalise_name,
    normalise_pan,
)
from app.modules.onboarding.exceptions import (
    DuplicatePanError,
    ExporterLifecycleComplianceRequiredError,
    ExporterProfileNotFoundError,
    ExporterSourceImmutableError,
    InvalidExporterLifecycleTransitionError,
    InvalidMarkerTransitionError,
)
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    ExporterContactRepository,
    ExporterProfileRepository,
)
from app.platform.idempotency.models import IdempotencyKeyType, RegistrationResultType
from app.platform.idempotency.services import complete_key, register_key
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: Scope identifier for every idempotency record this service creates.
_SCOPE = "exporter_profile"
_OP_CREATE = "create_or_get_profile"

#: Fields ``update_profile`` refuses to touch, each for its own reason:
#: ``source`` is immutable (audit-relevant provenance — see
#: ``ExporterSourceImmutableError``); ``customer_id``/``id``/``date_added`` are
#: identity/immutable columns; ``lifecycle_status`` has its own governed write
#: path (``transition_lifecycle_status``, checked against
#: ``PERMITTED_LIFECYCLE_TRANSITIONS``) and must never be set as a bare field
#: update that bypasses that table.
_UPDATE_FORBIDDEN_FIELDS = frozenset(
    {
        "source",
        "customer_id",
        "id",
        "date_added",
        "lifecycle_status",
        "journey",
        "qualification",
        "marker",
        "marker_reason",
        "created_at",
        "updated_at",
    }
)

#: The company fields staff may edit through `update_profile` (L2-07), with
#: every change recorded in the history log. Each may be cleared except those
#: in `_NOT_CLEARABLE`.
_EDITABLE_FIELDS = frozenset(
    {
        "name",
        "country",
        "cin",
        "pan",
        "gstins",
        "iec",
        "relationship_manager",
        "industry",
        "export_markets",
        "products",
        "year_established",
        "website",
    }
)

#: A named company keeps its name and country: they can be corrected, never
#: emptied (company-record contract §2.1).
_NOT_CLEARABLE = frozenset({"name", "country"})

#: Identifiers written to the history log masked. The history read route
#: shows a row's details to every CRM reader, including roles that only ever
#: see these masked on the company itself, so a full value in the log would
#: undo the company route's masking (company-record contract §6, O5).
_MASKED_IN_HISTORY = frozenset({"gstins", "pan", "iec", "cin"})

#: History dimensions and event types this service writes
#: (`docs/contracts/company-record.md` §6).
HISTORY_DIMENSION_PROFILE = "profile"
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

#: The permitted `(from, to)` lifecycle_status edges — follows `cases`'
#: `PERMITTED_TRANSITIONS` pattern: a module-level frozenset, not a
#: free-for-all. `transition_lifecycle_status` is the one place this is
#: checked, so an attempted skip (e.g. LEAD -> ACTIVE) is rejected uniformly
#: regardless of caller.
PERMITTED_LIFECYCLE_TRANSITIONS: frozenset[
    tuple[ExporterLifecycleStatus, ExporterLifecycleStatus]
] = frozenset(
    {
        (ExporterLifecycleStatus.LEAD, ExporterLifecycleStatus.CONTACTED),
        (ExporterLifecycleStatus.CONTACTED, ExporterLifecycleStatus.DATA_COLLECTION),
        (ExporterLifecycleStatus.DATA_COLLECTION, ExporterLifecycleStatus.VERIFICATION_IN_PROGRESS),
        (
            ExporterLifecycleStatus.VERIFICATION_IN_PROGRESS,
            ExporterLifecycleStatus.COMPLIANCE_REVIEW,
        ),
        # A compliance rejection sends the relationship back for more data
        # rather than dead-ending it.
        (ExporterLifecycleStatus.COMPLIANCE_REVIEW, ExporterLifecycleStatus.DATA_COLLECTION),
        (ExporterLifecycleStatus.COMPLIANCE_REVIEW, ExporterLifecycleStatus.ONBOARDED),
        (ExporterLifecycleStatus.ONBOARDED, ExporterLifecycleStatus.FINANCING_ELIGIBLE),
        (ExporterLifecycleStatus.ONBOARDED, ExporterLifecycleStatus.ACTIVE),
        (ExporterLifecycleStatus.FINANCING_ELIGIBLE, ExporterLifecycleStatus.ACTIVE),
        (ExporterLifecycleStatus.ACTIVE, ExporterLifecycleStatus.SUSPENDED),
        (ExporterLifecycleStatus.SUSPENDED, ExporterLifecycleStatus.ACTIVE),
        (ExporterLifecycleStatus.ACTIVE, ExporterLifecycleStatus.OFFBOARDED),
        (ExporterLifecycleStatus.SUSPENDED, ExporterLifecycleStatus.OFFBOARDED),
    }
)

#: Statuses an exporter can only reach through a compliance decision. Creating
#: a profile directly at one of these would skip that decision entirely, so
#: `create_or_get_profile` refuses it unless the caller is compliance-authorised.
COMPLIANCE_DECIDED_STATUSES: frozenset[ExporterLifecycleStatus] = frozenset(
    {
        ExporterLifecycleStatus.ONBOARDED,
        ExporterLifecycleStatus.FINANCING_ELIGIBLE,
        ExporterLifecycleStatus.ACTIVE,
        ExporterLifecycleStatus.SUSPENDED,
        ExporterLifecycleStatus.OFFBOARDED,
    }
)

#: A move *out of* any of these is a compliance decision: approving or sending
#: back from COMPLIANCE_REVIEW, and every change to an onboarded relationship.
#: The sales stages before it (LEAD -> ... -> COMPLIANCE_REVIEW, i.e. submitting
#: for review) stay open to Relationship Managers.
COMPLIANCE_GATED_FROM_STATUSES: frozenset[ExporterLifecycleStatus] = (
    COMPLIANCE_DECIDED_STATUSES | {ExporterLifecycleStatus.COMPLIANCE_REVIEW}
)


class ExporterProfileService:
    """Read/write access to `exporter_profile` and its detail projection (EXP-1)."""

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
        website: str | None = None,
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
            website=website,
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
        lifecycle_status: ExporterLifecycleStatus = ExporterLifecycleStatus.LEAD,
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
        website: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
        compliance_authorized: bool = False,
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

        Raises ``ExporterLifecycleComplianceRequiredError`` (403) for a
        ``lifecycle_status`` in ``COMPLIANCE_DECIDED_STATUSES`` unless
        ``compliance_authorized``.
        """
        if lifecycle_status in COMPLIANCE_DECIDED_STATUSES and not compliance_authorized:
            raise ExporterLifecycleComplianceRequiredError(customer_id, lifecycle_status)

        name = normalise_name(name)
        country = normalise_country(country)
        pan = normalise_pan(pan)
        cin = normalise_cin(cin)
        iec = normalise_iec(iec)
        gstin_values = normalise_gstins(gstins)
        check_gstins_match_pan(pan, gstin_values)

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

        profile = ExporterProfile(
            customer_id=customer_id,
            source=source,
            lifecycle_status=lifecycle_status,
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
            website=website,
            gstin_rows=[ExporterGstin(customer_id=customer_id, gstin=g) for g in gstin_values],
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
                raise
            logger.info(
                "exporter_profile.create.lost_race", customer_id=str(customer_id)
            )
            return winner, False

        await self._record_lifecycle(
            customer_id,
            from_status=None,
            to_status=lifecycle_status,
            actor_id=actor_id,
            event_type=LIFECYCLE_INITIAL_EVENT,
            source=history_source,
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
        PAN must fit the GSTINs being kept, and new GSTINs must carry the PAN.
        `gstins` replaces the company's whole list.

        Each field whose value actually changes writes one `profile` history
        row through the shared `HistoryService`: `to_value` names the field,
        and `details` carries `field`, `from`, `to`, and an `edit_id` shared by
        every row of the same edit. A supplied value equal to the current one
        writes nothing. The values live in `details` rather than in
        `from_value`/`to_value` because those columns hold 64 characters and
        refuse an empty value (company-record contract §6, O7).

        The column writes and the history rows are committed together, once,
        at the end — the writer flushes and never commits — so a company can
        never show an edit with no record of it. Everything is validated before
        the first assignment, so a refused edit leaves nothing behind.

        `actor_id` is the signed-in user, from the session. It is a separate
        keyword, never one of `changes`.

        Never touches `source` (immutable — see `ExporterSourceImmutableError`),
        `lifecycle_status` (owned by `transition_lifecycle_status`) or the
        marker (owned by `set_marker`), nor the journey or the qualification
        gauge (owned by `QualificationService`).
        """
        if "source" in changes:
            raise ExporterSourceImmutableError(customer_id)
        forbidden = _UPDATE_FORBIDDEN_FIELDS.intersection(changes)
        if forbidden:
            raise ValidationError(
                f"update_profile cannot set {sorted(forbidden)}: use the dedicated "
                f"write path for each (transition_lifecycle_status for lifecycle_status; "
                f"set_marker for the marker; none for identity/immutable columns)"
            )
        unknown = set(changes) - _EDITABLE_FIELDS
        if unknown:
            raise ValidationError(
                f"update_profile cannot set {sorted(unknown)}: not an editable company field"
            )

        profile = await self._require_profile(customer_id)
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
        if "gstins" in wanted:
            wanted["gstins"] = normalise_gstins(wanted["gstins"]) or None  # type: ignore[arg-type]
        check_gstins_match_pan(
            wanted.get("pan", profile.pan),  # type: ignore[arg-type]
            wanted.get("gstins", profile.gstins) or [],  # type: ignore[arg-type]
        )
        if wanted.get("pan") is not None and wanted["pan"] != profile.pan:
            await self._refuse_duplicate_pan(wanted["pan"], customer_id)  # type: ignore[arg-type]

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
            if field == "gstins":
                # Keep the row of every GSTIN that stays: the unit of work
                # inserts before it deletes, so re-creating a kept GSTIN would
                # collide with its own old row on uq_exporter_gstin_customer_gstin.
                kept = {row.gstin: row for row in profile.gstin_rows}
                profile.gstin_rows = [
                    kept.get(g) or ExporterGstin(customer_id=customer_id, gstin=g)
                    for g in (new_value or [])  # type: ignore[union-attr]
                ]
            else:
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

        try:
            await self._db.commit()
        except IntegrityError:
            # A concurrent writer took the PAN between the check and the commit.
            await self._db.rollback()
            if "pan" in edits:
                await self._refuse_duplicate_pan(wanted["pan"], customer_id)  # type: ignore[arg-type]
            raise
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.update.ok",
            customer_id=str(customer_id),
            changed=sorted(edits),
            actor_id=actor_id,
        )
        return profile

    # ── Marker (L2-08) ──────────────────────────────────────────────────────

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
        `lifecycle_status`, not any gauge (decision 3). Allowed moves and
        which of them need a reason are `_MARKER_MOVES` (company-record
        contract §3.3); anything else is `InvalidMarkerTransitionError` (409).
        Setting `PAUSED` or `ENDED` without a reason is a 422, and the
        database refuses it too (`ck_exporter_profile_marker_reason`).

        The marker, its current reason and one `marker` history row — from,
        to, reason, the signed-in user — commit together.
        """
        profile = await self._require_profile(customer_id)
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
        lifecycle_status: ExporterLifecycleStatus | None = None,
        journey: ExporterJourney | None = None,
        qualification: QualificationState | None = None,
        marker: ExporterMarker | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfileListItem]:
        """Filtered company search.

        `name_contains` is a case-insensitive partial match on the company's
        name. `gstin` matches any of a company's GSTINs; `pan`, `gstin` and
        `iec` are normalised first, so case and surrounding spaces do not
        matter.

        **`ENDED` companies are left out of the default working list and stay
        searchable** (assumption A11): with no `marker` filter and no search
        term (`name_contains`, `pan`, `gstin`, `iec`), `ENDED` companies are
        excluded; any search term includes them; `marker=ENDED` lists only
        them. `source` and `lifecycle_status` are list filters, not search
        terms, and do not bring `ENDED` companies back.
        """
        pan = _normalise_term(pan)
        gstin = _normalise_term(gstin)
        iec = _normalise_term(iec)
        searching = any(term is not None for term in (name_contains, pan, gstin, iec))

        profiles = await self._profiles.search(
            gstin=gstin,
            pan=pan,
            iec=iec,
            name_contains=name_contains,
            source=source,
            lifecycle_status=lifecycle_status,
            journey=journey,
            qualification=qualification,
            marker=marker,
            exclude_ended=marker is None and not searching,
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
                lifecycle_status=profile.lifecycle_status,
                marker=profile.marker,
                marker_reason=profile.marker_reason,
                industry=profile.industry,
                year_established=profile.year_established,
                date_added=profile.date_added,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
            for profile in profiles
        ]

    # ── Lifecycle transition ─────────────────────────────────────────────

    async def _record_lifecycle(
        self,
        customer_id: uuid.UUID,
        *,
        from_status: ExporterLifecycleStatus | None,
        to_status: ExporterLifecycleStatus,
        actor_id: str | None,
        event_type: str,
        source: str,
        reason: str | None = None,
    ) -> None:
        """Append one journey history row through the shared writer.

        A thin adapter over `HistoryService.record`, not a second
        implementation: it turns this service's `ExporterLifecycleStatus`
        members into the strings the history log stores, supplies
        `dimension="journey"`, and computes the `terminal` flag below. There is
        one writer of `exporter_lifecycle_history` and it is `HistoryService`.

        Still flushed and not committed — the rule has moved into the shared
        writer rather than away. `transition_lifecycle_status` commits the
        status column and this row together, so a profile can never hold a
        status with no record of how it got there.

        `event_type` is passed explicitly rather than letting `record` derive
        it. The derived names would be `journey_initial`/`journey_transition`;
        these rows have always been `lifecycle_initial`/`lifecycle_transition`,
        a downstream consumer (ANER-4.2-S1T2) polls for them, and 1,659 existing
        rows carry them. Renaming is not this change's to make.

        Enough for a downstream consumer to act on without re-reading the
        profile: ANER-4.2-S1T2 wants a completion hook on
        COMPLIANCE_REVIEW -> ONBOARDED, and Epic 4.1 has none. `terminal` is
        the flag that edge is identified by, computed from the status rather
        than hardcoded at a call site so adding a lifecycle status cannot
        silently change what "onboarding completed" means. A profile *created*
        at ONBOARDED is terminal too — it is onboarded, and the hook must see
        it. `source` distinguishes the write paths.
        """
        await self._history.record(
            customer_id,
            dimension=HISTORY_DIMENSION_JOURNEY,
            from_value=from_status.value if from_status is not None else None,
            to_value=to_status.value,
            actor_id=actor_id,
            reason=reason,
            source=source,
            event_type=event_type,
            details={"terminal": to_status is ExporterLifecycleStatus.ONBOARDED},
        )

    async def transition_lifecycle_status(
        self,
        customer_id: uuid.UUID,
        to_status: ExporterLifecycleStatus,
        actor_id: str,
        *,
        compliance_authorized: bool = False,
    ) -> ExporterProfile:
        """Move `lifecycle_status` to `to_status`, validated against
        `PERMITTED_LIFECYCLE_TRANSITIONS`. Raises
        `InvalidExporterLifecycleTransitionError` (naming both the current
        and attempted status) for any pair not in that table — including a
        same-status "transition", which has no edge in the table and so is
        rejected the same way, with no special-casing needed.

        A permitted move out of `COMPLIANCE_GATED_FROM_STATUSES` additionally
        raises `ExporterLifecycleComplianceRequiredError` (403) unless
        `compliance_authorized`. The edge check runs first, so an illegal move
        is a 409 for every caller.

        Every accepted move writes an append-only `exporter_lifecycle_history`
        row carrying `from_status`, `to_status` and `actor_id`, in the same
        transaction as the column write. Before this, `actor_id` was a parameter
        that reached a log line and nothing else: the fact that a named person
        moved an exporter to `ONBOARDED` survived only as long as log retention.

        The row and the column commit together on purpose. Two commits would
        allow a profile to be `ONBOARDED` with no record of who did it, which is
        the exact failure being fixed; the trigger on the history table means the
        row cannot later be quietly adjusted to match a column someone edited by
        hand.

        Why this is not an `onboarding_event` row — `self._events` is right
        there, and it was the first choice — is in
        `ExporterLifecycleHistory`'s module docstring: that table's
        `onboarding_request_id` is NOT NULL, and most exporter profiles have no
        onboarding request.
        """
        profile = await self._require_profile(customer_id)
        from_status = profile.lifecycle_status

        if (from_status, to_status) not in PERMITTED_LIFECYCLE_TRANSITIONS:
            raise InvalidExporterLifecycleTransitionError(customer_id, from_status, to_status)

        if from_status in COMPLIANCE_GATED_FROM_STATUSES and not compliance_authorized:
            raise ExporterLifecycleComplianceRequiredError(customer_id, to_status, from_status)

        profile.lifecycle_status = to_status

        await self._record_lifecycle(
            customer_id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            event_type=LIFECYCLE_TRANSITION_EVENT,
            source="exporter_profile_service.transition_lifecycle_status",
        )

        await self._db.commit()
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.transition_lifecycle_status.ok",
            customer_id=str(customer_id),
            from_status=from_status.value,
            to_status=to_status.value,
            actor_id=actor_id,
        )
        return profile

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
            lifecycle_status=profile.lifecycle_status,
            marker=profile.marker,
            marker_reason=profile.marker_reason,
            industry=profile.industry,
            export_markets=profile.export_markets,
            products=profile.products,
            year_established=profile.year_established,
            website=profile.website,
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

    async def _refuse_duplicate_pan(self, pan: str | None, customer_id: uuid.UUID) -> None:
        """Raise `DuplicatePanError` if another company already holds `pan`."""
        if pan is None:
            return
        holder = await self._profiles.get_by_pan(pan)
        if holder is not None and holder.customer_id != customer_id:
            raise DuplicatePanError(holder.customer_id)


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


__all__ = ["ExporterProfileService", "PERMITTED_LIFECYCLE_TRANSITIONS"]
