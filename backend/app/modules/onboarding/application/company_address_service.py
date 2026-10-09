"""``CompanyAddressService`` — a company's addresses.

Many addresses per company, each of a type, at most one **default** per type among the
active ones. The first active address of a type becomes its default; making another
the default demotes the old one in the same transaction. Addresses are deactivated,
never deleted, and every change writes one ``address`` history row.

Writes lock the **company** row first, so two people setting a default for the same
company at once queue rather than both succeeding (the partial unique index
``uq_company_address_default_per_type`` would refuse the second anyway; the lock turns
that refusal into the right answer).

An address added from a GST registration (``gst_registration_id``) is linked to it
(``exporter_gstin.address_id``); the registration must be the same company's.

The registered address is what the background check's "is the registered address a
physical business address?" question is about, so the list says whether the default
registered address changed after the company's last Clear.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
)
from app.modules.onboarding.domain.entities.company_address import CompanyAddress
from app.modules.onboarding.domain.entities.exporter_enums import CompanyAddressType
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    CompanyAddressNotFoundError,
    ExporterProfileNotFoundError,
    GstRegistrationNotFoundError,
)
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The fields an edit may change, and the name each has in a history row.
EDITABLE = ("address_type", "line1", "line2", "city", "state", "postal_code", "country")


@dataclass(frozen=True)
class CompanyAddresses:
    addresses: list[CompanyAddress]
    #: When the company's background check was last cleared, if ever.
    last_clear_at: datetime | None
    #: Whether the default registered address was added or changed after that Clear.
    registered_changed_since_clear: bool


class CompanyAddressService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    async def list_for_company(self, customer_id: uuid.UUID) -> CompanyAddresses:
        """Every address, active ones first, then by type and age — deactivated ones
        included, because a branch or a past document may still name one."""
        await self._require_company(customer_id)
        addresses = list(
            await self._db.scalars(
                select(CompanyAddress)
                .where(CompanyAddress.customer_id == customer_id)
                .order_by(
                    CompanyAddress.is_active.desc(),
                    CompanyAddress.address_type,
                    CompanyAddress.is_default.desc(),
                    CompanyAddress.created_at,
                )
            )
        )
        last_clear_at = await self._db.scalar(
            select(func.max(BackgroundCheckDecision.decided_at)).where(
                BackgroundCheckDecision.company_id == customer_id,
                BackgroundCheckDecision.to_value == "CLEAR",
            )
        )
        registered = next(
            (
                address
                for address in addresses
                if address.is_default
                and address.address_type == CompanyAddressType.REGISTERED.value
            ),
            None,
        )
        changed = (
            last_clear_at is not None
            and registered is not None
            and registered.updated_at > last_clear_at
        )
        return CompanyAddresses(addresses, last_clear_at, changed)

    async def add(
        self,
        customer_id: uuid.UUID,
        *,
        fields: Mapping[str, object],
        make_default: bool,
        actor_id: str,
        gst_registration_id: uuid.UUID | None = None,
    ) -> CompanyAddress:
        """Add an address. It becomes its type's default when asked to, or when the
        company has no active default of that type yet."""
        await self._lock_company(customer_id)
        registration = None
        if gst_registration_id is not None:
            registration = await self._db.scalar(
                select(ExporterGstin)
                .where(
                    ExporterGstin.id == gst_registration_id,
                    ExporterGstin.customer_id == customer_id,
                )
                .with_for_update()
            )
            if registration is None:
                raise GstRegistrationNotFoundError(gst_registration_id)

        address_type = str(fields["address_type"])
        has_default = await self._default_of(customer_id, address_type) is not None
        default = make_default or not has_default
        if default:
            await self._clear_default(customer_id, address_type)
        address = CompanyAddress(
            customer_id=customer_id,
            **{name: fields.get(name) for name in EDITABLE},
            is_default=default,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._db.add(address)
        await self._db.flush()
        if registration is not None:
            registration.address_id = address.id
        await self._record(
            address,
            event_type="address_added",
            actor_id=actor_id,
            details={
                "is_default": default,
                "gst_registration_id": str(gst_registration_id) if registration else None,
            },
        )
        await self._db.commit()
        await self._db.refresh(address)
        logger.info(
            "company_address.added",
            customer_id=str(customer_id),
            address_id=str(address.id),
            address_type=address_type,
        )
        return address

    async def update(
        self, address_id: uuid.UUID, *, changes: Mapping[str, object], actor_id: str
    ) -> CompanyAddress:
        """Change the fields named in ``changes``. A deactivated address is read-only.
        A default address moved to another type takes that type's default with it."""
        address = await self._lock_address(address_id)
        if not address.is_active:
            raise ValidationError("A deactivated address cannot be changed")
        changed = {
            name: (getattr(address, name), value)
            for name, value in changes.items()
            if name in EDITABLE and getattr(address, name) != value
        }
        if not changed:
            return address
        new_type = changes.get("address_type")
        if new_type is not None and new_type != address.address_type and address.is_default:
            await self._clear_default(address.customer_id, str(new_type))
        for name, (_old, value) in changed.items():
            setattr(address, name, value)
        address.updated_by = actor_id
        await self._record(
            address,
            event_type="address_updated",
            actor_id=actor_id,
            details={
                "changed": sorted(changed),
                "from": {name: old for name, (old, _new) in changed.items()},
            },
        )
        await self._db.commit()
        await self._db.refresh(address)
        return address

    async def set_default(self, address_id: uuid.UUID, *, actor_id: str) -> CompanyAddress:
        address = await self._lock_address(address_id)
        if not address.is_active:
            raise ValidationError("A deactivated address cannot be a default")
        if address.is_default:
            return address
        await self._clear_default(address.customer_id, address.address_type)
        address.is_default = True
        address.updated_by = actor_id
        await self._record(address, event_type="address_default_set", actor_id=actor_id)
        await self._db.commit()
        await self._db.refresh(address)
        return address

    async def deactivate(
        self, address_id: uuid.UUID, *, reason: str | None, actor_id: str
    ) -> CompanyAddress:
        """Stop using an address, keeping its row. A default address leaves its type
        with no default until another is chosen. Deactivating twice is a no-op."""
        address = await self._lock_address(address_id)
        if not address.is_active:
            return address
        was_default = address.is_default
        address.is_active = False
        address.is_default = False
        address.updated_by = actor_id
        await self._record(
            address,
            event_type="address_deactivated",
            actor_id=actor_id,
            reason=(reason or "").strip() or None,
            details={"was_default": was_default},
        )
        await self._db.commit()
        await self._db.refresh(address)
        return address

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require_company(self, customer_id: uuid.UUID) -> None:
        found = await self._db.scalar(
            select(ExporterProfile.customer_id).where(ExporterProfile.customer_id == customer_id)
        )
        if found is None:
            raise ExporterProfileNotFoundError(customer_id)

    async def _lock_company(self, customer_id: uuid.UUID) -> None:
        found = await self._db.scalar(
            select(ExporterProfile.customer_id)
            .where(ExporterProfile.customer_id == customer_id)
            .with_for_update()
        )
        if found is None:
            raise ExporterProfileNotFoundError(customer_id)

    async def _lock_address(self, address_id: uuid.UUID) -> CompanyAddress:
        """Lock the owning company, then the address — the order every write takes."""
        customer_id = await self._db.scalar(
            select(CompanyAddress.customer_id).where(CompanyAddress.id == address_id)
        )
        if customer_id is None:
            raise CompanyAddressNotFoundError(address_id)
        await self._lock_company(customer_id)
        address = await self._db.scalar(
            select(CompanyAddress)
            .where(CompanyAddress.id == address_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if address is None:  # pragma: no cover - addresses are never deleted
            raise CompanyAddressNotFoundError(address_id)
        return address

    async def _default_of(self, customer_id: uuid.UUID, address_type: str) -> uuid.UUID | None:
        return await self._db.scalar(
            select(CompanyAddress.id).where(
                CompanyAddress.customer_id == customer_id,
                CompanyAddress.address_type == address_type,
                CompanyAddress.is_default.is_(True),
                CompanyAddress.is_active.is_(True),
            )
        )

    async def _clear_default(self, customer_id: uuid.UUID, address_type: str) -> None:
        await self._db.execute(
            update(CompanyAddress)
            .where(
                CompanyAddress.customer_id == customer_id,
                CompanyAddress.address_type == address_type,
                CompanyAddress.is_default.is_(True),
            )
            .values(is_default=False)
        )
        await self._db.flush()

    async def _record(
        self,
        address: CompanyAddress,
        *,
        event_type: str,
        actor_id: str,
        reason: str | None = None,
        details: dict | None = None,
    ) -> None:
        await self._history.record(
            address.customer_id,
            dimension=history_dimensions.ADDRESS,
            event_type=event_type,
            to_value=address.address_type,
            actor_id=actor_id,
            source="company_address_service",
            reason=reason,
            details={
                "address_id": str(address.id),
                "summary": summary(address),
                **(details or {}),
            },
        )


def summary(address: CompanyAddress) -> str:
    """One line: "12 Marine Drive, Mumbai, MH 400001, IN"."""
    place = " ".join(part for part in (address.state, address.postal_code) if part)
    return ", ".join(
        part for part in (address.line1, address.line2, address.city, place, address.country) if part
    )
