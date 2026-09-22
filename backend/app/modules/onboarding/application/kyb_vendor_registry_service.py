"""KybVendorRegistryService — authoritative source of registered KYB vendors (S1T4).

Manages the ``onboarding.kyb_vendor_registration`` table and answers "which KYB
vendor should verify a customer registered in country X as entity type Y?".

Modelled on ``app.modules.rails.application.registry_service.RailRegistryService``
(Epic 2.4 S1T3): the same shape of upsert-under-an-idempotency-key registration,
key-free reads, and an approval-free operational-state update.

All mutating operations use Epic 2.3 idempotency keys
(``app.platform.idempotency``). Nothing here reimplements that machinery.

Vendor selection when several healthy vendors match
--------------------------------------------------
The ticket does not specify a tie-break. This service uses a deterministic one,
consistent with the rails registry's "healthiest and fastest first" ordering:

  1. prefer the healthier vendor (HEALTHY before DEGRADED);
  2. then the earliest-registered vendor (``created_at`` ascending);
  3. then ``vendor_id`` ascending, so the result is fully deterministic.

``DOWN`` vendors are excluded from selection entirely, exactly as
``RailRegistryService.get_rails_for_corridor`` excludes rails outside
``(ACTIVE, DEGRADED)``. If every matching vendor is ``DOWN``, the lookup returns
a manual-review result.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.kyb_vendor_registration import KybVendorRegistration
from app.modules.onboarding.domain.kyb_vendor_selection import (
    KybVendorLookupResult,
    normalise_country,
    normalise_country_list,
    normalise_entity_type,
    normalise_entity_type_list,
)
from app.platform.idempotency.models import IdempotencyKeyType, RegistrationResultType
from app.platform.idempotency.services import complete_key, register_key
from app.shared.contracts.kyb import KYBVendorCapabilityDeclaration
from app.shared.enums.kyb import VendorHealthStatusEnum
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)

#: Scope identifier for every idempotency record this service creates.
_SCOPE = "kyb_vendor_registry"

_OP_REGISTER = "register_kyb_vendor"
_OP_UPDATE_HEALTH = "update_kyb_vendor_health"

#: Health states a vendor may be in and still be handed to the orchestration
#: engine. Mirrors RailRegistryService's ``status IN (ACTIVE, DEGRADED)`` filter.
_SELECTABLE_HEALTH: tuple[VendorHealthStatusEnum, ...] = (
    VendorHealthStatusEnum.HEALTHY,
    VendorHealthStatusEnum.DEGRADED,
)

#: Ordering weight for the selection tie-break — lower is preferred.
_HEALTH_RANK: dict[VendorHealthStatusEnum, int] = {
    VendorHealthStatusEnum.HEALTHY: 0,
    VendorHealthStatusEnum.DEGRADED: 1,
    VendorHealthStatusEnum.DOWN: 2,
}


class KybVendorRegistryService:
    """Read/write access to the KYB vendor registry."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Register vendor ───────────────────────────────────────────────────────

    async def register_vendor(
        self,
        declaration: KYBVendorCapabilityDeclaration,
        *,
        idempotency_key: str,
        actor_id: str | None = None,
    ) -> KybVendorRegistration:
        """Upsert a vendor from its capability declaration.

        Called at service startup by the KYB vendor seed loader, once per
        adapter, passing that adapter's ``declare_capabilities()`` output.

        Semantics:

        * validated by Pydantic on ``KYBVendorCapabilityDeclaration`` construction
          (the caller builds it) — this method additionally rejects a blank
          ``vendor_id``;
        * ``INSERT ... ON CONFLICT (vendor_id) DO UPDATE`` — no duplicate rows;
        * ``health_status`` / ``last_health_check_at`` are **not** in the update
          set: re-registration never resets operational state owned by the
          health monitor;
        * idempotent under the Epic 2.3 key — a completed key replays the cached
          row with no write.
        """
        if not declaration.vendor_id or not declaration.vendor_id.strip():
            raise ValueError("KYB vendor declaration has a blank vendor_id")

        reg_result = await register_key(
            session=self._db,
            key_value=idempotency_key,
            key_type=IdempotencyKeyType.INTERNAL_DERIVED_KEY,
            scope_id=_SCOPE,
            operation_type=_OP_REGISTER,
            created_by=actor_id,
        )

        if reg_result.result == RegistrationResultType.DUPLICATE:
            cached = reg_result.record.response_cache if reg_result.record is not None else None
            if cached and cached.get("kyb_vendor_registration_id"):
                existing = await self._db.get(
                    KybVendorRegistration, uuid.UUID(cached["kyb_vendor_registration_id"])
                )
                if existing is not None:
                    logger.info(
                        "kyb_vendor_registry.register_vendor.idempotent_replay",
                        vendor_id=declaration.vendor_id,
                        idempotency_key=idempotency_key,
                    )
                    return existing

        now = datetime.now(UTC)
        cap_dict = declaration.model_dump(mode="json")
        countries = normalise_country_list(list(declaration.supported_countries))
        entity_types = normalise_entity_type_list(list(declaration.supported_entity_types))

        stmt = (
            pg_insert(KybVendorRegistration)
            .values(
                id=uuid.uuid4(),
                vendor_id=declaration.vendor_id,
                vendor_name=declaration.vendor_name,
                supported_countries=countries,
                supported_entity_types=entity_types,
                processing_mode=declaration.processing_mode,
                capability_declaration=cap_dict,
                health_status=VendorHealthStatusEnum.HEALTHY,
                last_health_check_at=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_kyb_vendor_registration_vendor_id",
                set_={
                    "vendor_name": declaration.vendor_name,
                    "supported_countries": countries,
                    "supported_entity_types": entity_types,
                    "processing_mode": declaration.processing_mode,
                    "capability_declaration": cap_dict,
                    "updated_at": now,
                    # health_status / last_health_check_at deliberately untouched.
                },
            )
            .returning(KybVendorRegistration)
        )

        result = await self._db.execute(stmt)
        vendor = result.scalar_one()

        await complete_key(
            session=self._db,
            key_value=idempotency_key,
            scope_id=_SCOPE,
            terminal_status="completed",
            response_payload={"kyb_vendor_registration_id": str(vendor.id)},
        )
        await self._db.commit()
        await self._db.refresh(vendor)

        logger.info(
            "kyb_vendor_registry.register_vendor.ok",
            vendor_id=vendor.vendor_id,
            registration_id=str(vendor.id),
            supported_countries=vendor.supported_countries,
        )
        return vendor

    # ── Get vendor for country ───────────────────────────────────────────────

    async def get_vendor_for_country(
        self,
        registration_country: str,
        entity_type: str,
    ) -> KybVendorLookupResult:
        """Resolve the KYB vendor for a customer's registration country + entity type.

        Read-only; carries no idempotency key (a lookup has no side effects —
        the same stance ``RailRegistryService`` takes for its reads).

        Returns a :class:`KybVendorLookupResult`: either a matched vendor, or a
        manual-review result when no registered, selectable vendor covers the
        combination.
        """
        country = normalise_country(registration_country)
        etype = normalise_entity_type(entity_type)

        stmt = (
            select(KybVendorRegistration)
            .where(
                KybVendorRegistration.supported_countries.contains([country]),
                KybVendorRegistration.health_status.in_(_SELECTABLE_HEALTH),
            )
            .order_by(KybVendorRegistration.created_at.asc())
        )
        result = await self._db.execute(stmt)
        candidates = list(result.scalars().all())

        matches = [v for v in candidates if _entity_type_supported(v, etype)]
        if not matches:
            reason = (
                f"No registered KYB vendor supports registration_country={country!r} "
                f"entity_type={etype!r}"
            )
            logger.info(
                "kyb_vendor_registry.get_vendor_for_country.manual_review",
                registration_country=country,
                entity_type=etype,
            )
            return KybVendorLookupResult.manual_review(reason)

        chosen = min(
            matches,
            key=lambda v: (_HEALTH_RANK[v.health_status], v.created_at, v.vendor_id),
        )
        logger.info(
            "kyb_vendor_registry.get_vendor_for_country.matched",
            registration_country=country,
            entity_type=etype,
            vendor_id=chosen.vendor_id,
        )
        return KybVendorLookupResult.matched(chosen)

    # ── Update vendor health ─────────────────────────────────────────────────

    async def update_vendor_health(
        self,
        vendor_id: str,
        *,
        status: VendorHealthStatusEnum,
        idempotency_key: str,
        checked_at: datetime | None = None,
        actor_id: str | None = None,
    ) -> KybVendorRegistration:
        """Record a health-check result: set ``health_status`` and ``last_health_check_at``.

        Called by the health monitor. Uses an Epic 2.3 idempotency key like every
        other mutating registry operation (AC6). ``NotFoundError`` if the vendor
        is not registered.
        """
        reg_result = await register_key(
            session=self._db,
            key_value=idempotency_key,
            key_type=IdempotencyKeyType.INTERNAL_DERIVED_KEY,
            scope_id=_SCOPE,
            operation_type=_OP_UPDATE_HEALTH,
            created_by=actor_id,
        )

        if reg_result.result == RegistrationResultType.DUPLICATE:
            cached = reg_result.record.response_cache if reg_result.record is not None else None
            if cached and cached.get("kyb_vendor_registration_id"):
                existing = await self._db.get(
                    KybVendorRegistration, uuid.UUID(cached["kyb_vendor_registration_id"])
                )
                if existing is not None:
                    logger.info(
                        "kyb_vendor_registry.update_vendor_health.idempotent_replay",
                        vendor_id=vendor_id,
                        idempotency_key=idempotency_key,
                    )
                    return existing

        result = await self._db.execute(
            select(KybVendorRegistration)
            .where(KybVendorRegistration.vendor_id == vendor_id)
            .with_for_update()
        )
        vendor = result.scalar_one_or_none()
        if vendor is None:
            raise NotFoundError(f"KYB vendor '{vendor_id}' is not registered")

        now = datetime.now(UTC)
        previous = vendor.health_status
        vendor.health_status = status
        vendor.last_health_check_at = checked_at or now
        vendor.updated_at = now
        self._db.add(vendor)

        await complete_key(
            session=self._db,
            key_value=idempotency_key,
            scope_id=_SCOPE,
            terminal_status="completed",
            response_payload={"kyb_vendor_registration_id": str(vendor.id)},
        )
        await self._db.commit()
        await self._db.refresh(vendor)

        logger.info(
            "kyb_vendor_registry.update_vendor_health.ok",
            vendor_id=vendor_id,
            previous_health_status=previous.value,
            new_health_status=status.value,
        )
        return vendor

    # ── Reads ────────────────────────────────────────────────────────────────

    async def get_vendor(self, vendor_id: str) -> KybVendorRegistration:
        """Return the registration for ``vendor_id``. ``NotFoundError`` if absent."""
        result = await self._db.execute(
            select(KybVendorRegistration).where(KybVendorRegistration.vendor_id == vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if vendor is None:
            raise NotFoundError(f"KYB vendor '{vendor_id}' is not registered")
        return vendor

    async def list_vendors(self) -> list[KybVendorRegistration]:
        """Every registered vendor, oldest first. Used by the health monitor."""
        result = await self._db.execute(
            select(KybVendorRegistration).order_by(KybVendorRegistration.created_at.asc())
        )
        return list(result.scalars().all())


def _entity_type_supported(vendor: KybVendorRegistration, entity_type: str) -> bool:
    """True when the vendor explicitly covers this entity type.

    An empty ``supported_entity_types`` list matches nothing — a vendor that
    declares no entity types verifies no entity types (it is never a wildcard).
    Matching is case-insensitive on the normalised value.
    """
    declared = vendor.supported_entity_types or []
    return normalise_entity_type(entity_type) in {normalise_entity_type(e) for e in declared}


__all__ = ["KybVendorRegistryService"]
