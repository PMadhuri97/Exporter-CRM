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
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingEntityType,
    OnboardingRequestStatus,
)
from app.modules.onboarding.domain.exporter_profile_views import (
    ExporterActivityView,
    ExporterContactView,
    ExporterProfileDetail,
    ExporterProfileListItem,
)
from app.modules.onboarding.domain.onboarding_request_views import OnboardingHistoryEntry
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    ExporterSourceImmutableError,
    InvalidExporterLifecycleTransitionError,
)
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    ExporterContactRepository,
    ExporterProfileRepository,
    OnboardingEventRepository,
    OnboardingRequestRepository,
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
    {"source", "customer_id", "id", "date_added", "lifecycle_status", "created_at", "updated_at"}
)

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


class ExporterProfileService:
    """Read/write access to `exporter_profile` and its detail projection (EXP-1)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._profiles = ExporterProfileRepository(db)
        self._contacts = ExporterContactRepository(db)
        self._activities = ExporterActivityRepository(db)
        self._requests = OnboardingRequestRepository(db)
        self._events = OnboardingEventRepository(db)

    # ── Create a bare Lead (Piece 1: "Add Exporter") ────────────────────────

    async def create_lead(
        self,
        *,
        tenant_id: uuid.UUID,
        legal_name: str,
        incorporation_country: str,
        initial_user_email: str,
        idempotency_key: str,
        source: ExporterSource,
        customer_id: uuid.UUID | None = None,
        entity_type: OnboardingEntityType = OnboardingEntityType.CORPORATION,
        gstin: str | None = None,
        pan: str | None = None,
        iec: str | None = None,
        relationship_manager: str | None = None,
        industry: str | None = None,
        export_markets: list[str] | None = None,
        products: list[str] | None = None,
        year_established: int | None = None,
        website: str | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
    ) -> tuple[OnboardingRequest, ExporterProfile, bool]:
        """Create an `ExporterProfile` *and* its minimal `OnboardingRequest`
        together, in one transaction — the actual fix for "Add Exporter has
        nowhere to put a name" (Piece 1). Before this method existed,
        `create_or_get_profile` created only the CRM-shell `ExporterProfile`,
        with no `OnboardingRequest` at all, so a Sales-added Lead had no
        `legal_name` anywhere for `search_profiles`'s `legal_name_contains`
        join (`OnboardingProfile` <- `OnboardingRequest.legal_name`) to find.

        Only `legal_name` and `incorporation_country` are required beyond the
        usual `OnboardingRequest` plumbing (`tenant_id`, `idempotency_key`) —
        `registration_number`/`registered_address` are left `None`, exactly
        what `onboarding_0007_reg_optional` made possible, to be filled in
        later via `OnboardingRequestService.submit_entity_details`. See
        `OnboardingRequestService.initiate_onboarding`'s docstring for why
        `initial_user_email` is still required rather than also loosened.

        Deliberately does *not* call `initiate_onboarding` (which does its
        own idempotency-key registration and commits on its own): that would
        make this method's two writes two separate transactions rather than
        one. Instead this builds both entities directly against the same
        session and flushes each in turn, committing only once at the end —
        the same "flush now, commit together at the end" shape
        `submit_entity_details` already uses to compose its own field update
        with `OnboardingTransitionService`'s write in one transaction.

        Idempotency relies on `onboarding_request`'s own
        `uq_onboarding_request_tenant_idem_key` constraint alone (no
        idempotency-key registry round trip) — the same lean
        `create_or_get_profile` documents for its no-key case: this is a
        trusted, internal "Add Exporter" UI action, not an untrusted,
        retrying caller like the future RXIL ingestion path.

        Returns `(onboarding_request, exporter_profile, created)`. `created` is
        `False` only when the *outer* `idempotency_key` constraint on
        `onboarding_request` catches an exact replay (mirrors
        `create_or_get_profile`'s own `created` flag, and the router's own
        already-documented 200-vs-201 response contract, which this method's
        missing return value previously left unenforceable — found via manual
        end-to-end testing: a resubmitted `Idempotency-Key` correctly returned
        the same `customer_id` both times, but always as `201`, never `200`).
        A *profile-level* race (the inner `except IntegrityError` below,
        `customer_id` colliding with a concurrent, unrelated write) still
        counts as `created=True`: this call's own `OnboardingRequest` really
        was newly created either way, which is what "created" means from the
        caller's perspective.
        """
        customer_id = customer_id or uuid.uuid4()
        now = datetime.now(UTC)

        request = OnboardingRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            customer_id=customer_id,
            status=OnboardingRequestStatus.DRAFT,
            entity_type=entity_type,
            legal_name=legal_name,
            registration_number=None,
            incorporation_country=incorporation_country,
            registered_address=None,
            initial_user_id=initial_user_email,
            initiated_at=now,
            last_activity_at=now,
            correlation_id=correlation_id,
        )

        try:
            async with self._db.begin_nested():
                self._db.add(request)
                await self._db.flush()
        except IntegrityError:
            # A retried "Add Exporter" submission with the same
            # idempotency_key: resolve the winner via the table's own unique
            # constraint (mirrors OnboardingRequestService.initiate_onboarding's
            # lost-race branch) and make sure it has a profile too, so a retry
            # is idempotent end-to-end, not just for the OnboardingRequest half.
            existing_request = await self._requests.get_by_tenant_and_idempotency_key(
                tenant_id, idempotency_key
            )
            if existing_request is None:
                raise
            logger.info(
                "exporter_profile.create_lead.lost_race",
                onboarding_id=str(existing_request.id),
                idempotency_key=idempotency_key,
            )
            profile, _created = await self.create_or_get_profile(
                existing_request.customer_id,
                source=source,
                gstin=gstin,
                pan=pan,
                iec=iec,
                relationship_manager=relationship_manager,
                industry=industry,
                export_markets=export_markets,
                products=products,
                year_established=year_established,
                website=website,
                actor_id=actor_id,
            )
            return existing_request, profile, False

        await self._events.create(
            OnboardingEvent(
                onboarding_request_id=request.id,
                event_type="state_transition",
                from_status=None,
                to_status=OnboardingRequestStatus.DRAFT.value,
                actor_id=actor_id,
                event_metadata={"trigger": "lead_created_via_exporter_profile"},
            )
        )

        profile = ExporterProfile(
            customer_id=customer_id,
            source=source,
            lifecycle_status=ExporterLifecycleStatus.LEAD,
            gstin=gstin,
            pan=pan,
            iec=iec,
            relationship_manager=relationship_manager,
            industry=industry,
            export_markets=export_markets,
            products=products,
            year_established=year_established,
            website=website,
        )
        try:
            async with self._db.begin_nested():
                self._db.add(profile)
                await self._db.flush()
        except IntegrityError:
            existing_profile = await self._profiles.get_by_customer_id(customer_id)
            if existing_profile is None:
                raise
            logger.info(
                "exporter_profile.create_lead.profile_lost_race",
                customer_id=str(customer_id),
            )
            profile = existing_profile

        await self._db.commit()
        await self._db.refresh(request)
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.create_lead.ok",
            customer_id=str(customer_id),
            onboarding_id=str(request.id),
            source=source.value,
        )
        return request, profile, True

    # ── Create ────────────────────────────────────────────────────────────

    async def create_or_get_profile(
        self,
        customer_id: uuid.UUID,
        *,
        source: ExporterSource,
        lifecycle_status: ExporterLifecycleStatus = ExporterLifecycleStatus.LEAD,
        gstin: str | None = None,
        pan: str | None = None,
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
    ) -> tuple[ExporterProfile, bool]:
        """Create an exporter_profile, or return the one already on file.

        Returns ``(profile, created)``; ``created`` is False on an idempotent
        replay or when a profile for this ``customer_id`` already existed.
        See the module docstring for when the ``idempotency_key`` round trip
        runs versus when this relies on ``uq_exporter_profile_customer_id``
        alone.
        """
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

        profile = ExporterProfile(
            customer_id=customer_id,
            source=source,
            lifecycle_status=lifecycle_status,
            gstin=gstin,
            pan=pan,
            iec=iec,
            relationship_manager=relationship_manager,
            industry=industry,
            export_markets=export_markets,
            products=products,
            year_established=year_established,
            website=website,
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
            # already carries.
            winner = await self._profiles.get_by_customer_id(customer_id)
            if winner is None:
                raise
            logger.info(
                "exporter_profile.create.lost_race", customer_id=str(customer_id)
            )
            return winner, False

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

    async def update_profile(self, customer_id: uuid.UUID, **fields: object) -> ExporterProfile:
        """Update mutable CRM fields. Never touches `source` (immutable — see
        `ExporterSourceImmutableError`) or `lifecycle_status` (owned by
        `transition_lifecycle_status`) — both rejected here at the service
        layer, in addition to the DB trigger guarding `source`, so the caller
        always gets a clean domain exception rather than a raw driver error.
        """
        if "source" in fields:
            raise ExporterSourceImmutableError(customer_id)
        forbidden = _UPDATE_FORBIDDEN_FIELDS.intersection(fields)
        if forbidden:
            raise ValidationError(
                f"update_profile cannot set {sorted(forbidden)}: use the dedicated "
                f"write path for each (transition_lifecycle_status for lifecycle_status; "
                f"none for identity/immutable columns)"
            )

        profile = await self._require_profile(customer_id)
        changes = {key: value for key, value in fields.items() if value is not None}
        for key, value in changes.items():
            setattr(profile, key, value)
        await self._db.commit()
        await self._db.refresh(profile)

        logger.info(
            "exporter_profile.update.ok",
            customer_id=str(customer_id),
            changed=sorted(changes),
        )
        return profile

    # ── Search ────────────────────────────────────────────────────────────

    async def search_profiles(
        self,
        *,
        gstin: str | None = None,
        pan: str | None = None,
        iec: str | None = None,
        legal_name_contains: str | None = None,
        source: ExporterSource | None = None,
        lifecycle_status: ExporterLifecycleStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfileListItem]:
        """Filtered profile search.

        `legal_name_contains` does a case-insensitive partial match against
        `OnboardingRequest.legal_name` — `ExporterProfile` deliberately has no
        `legal_name` column of its own (see `exporter_profile.py`'s module
        docstring), so this method resolves the matching `customer_id`s via a
        join first, then filters `exporter_profile` by that set. A profile
        with no `OnboardingRequest` yet (a bare Lead) is correctly excluded
        from a `legal_name_contains` search: there is nothing yet to match.
        """
        legal_name_customer_ids: list[uuid.UUID] | None = None
        if legal_name_contains is not None:
            result = await self._db.execute(
                select(OnboardingRequest.customer_id)
                .where(OnboardingRequest.legal_name.ilike(f"%{legal_name_contains}%"))
                .distinct()
            )
            legal_name_customer_ids = list(result.scalars().all())
            if not legal_name_customer_ids:
                return []

        rows = await self._profiles.search(
            gstin=gstin,
            pan=pan,
            iec=iec,
            legal_name_customer_ids=legal_name_customer_ids,
            source=source,
            lifecycle_status=lifecycle_status,
            limit=limit,
            offset=offset,
        )
        return [
            ExporterProfileListItem(
                customer_id=profile.customer_id,
                legal_name=legal_name,
                gstin=profile.gstin,
                pan=profile.pan,
                iec=profile.iec,
                source=profile.source,
                relationship_manager=profile.relationship_manager,
                relationship_manager_user_id=profile.relationship_manager_user_id,
                lifecycle_status=profile.lifecycle_status,
                industry=profile.industry,
                year_established=profile.year_established,
                date_added=profile.date_added,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
            for profile, legal_name in rows
        ]

    # ── Lifecycle transition ─────────────────────────────────────────────

    async def transition_lifecycle_status(
        self,
        customer_id: uuid.UUID,
        to_status: ExporterLifecycleStatus,
        actor_id: str,
    ) -> ExporterProfile:
        """Move `lifecycle_status` to `to_status`, validated against
        `PERMITTED_LIFECYCLE_TRANSITIONS`. Raises
        `InvalidExporterLifecycleTransitionError` (naming both the current
        and attempted status) for any pair not in that table — including a
        same-status "transition", which has no edge in the table and so is
        rejected the same way, with no special-casing needed.
        """
        profile = await self._require_profile(customer_id)
        from_status = profile.lifecycle_status

        if (from_status, to_status) not in PERMITTED_LIFECYCLE_TRANSITIONS:
            raise InvalidExporterLifecycleTransitionError(customer_id, from_status, to_status)

        profile.lifecycle_status = to_status
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
        """The profile plus its contacts, recent activities, and linked
        `OnboardingRequest` history — all queried by `customer_id` alone (no
        join table needed, per the confirmed plan)."""
        profile = await self._require_profile(customer_id)
        contacts = await self._contacts.list_by_customer(customer_id)
        activities = await self._activities.list_by_customer(
            customer_id, limit=recent_activities_limit
        )
        requests = await self._requests.list_by_customer(customer_id)

        return ExporterProfileDetail(
            customer_id=profile.customer_id,
            gstin=profile.gstin,
            pan=profile.pan,
            iec=profile.iec,
            source=profile.source,
            relationship_manager=profile.relationship_manager,
            relationship_manager_user_id=profile.relationship_manager_user_id,
            lifecycle_status=profile.lifecycle_status,
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
            onboarding_history=tuple(
                OnboardingHistoryEntry(
                    onboarding_id=r.id,
                    status=r.status,
                    legal_name=r.legal_name,
                    initiated_at=r.initiated_at,
                    completed_at=r.completed_at,
                    rejection_category=r.rejection_category,
                )
                for r in requests
            ),
        )

    # ── Internals ─────────────────────────────────────────────────────────

    async def _require_profile(self, customer_id: uuid.UUID) -> ExporterProfile:
        profile = await self._profiles.get_by_customer_id(customer_id)
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile


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
