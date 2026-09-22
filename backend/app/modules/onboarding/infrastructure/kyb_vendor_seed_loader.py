"""Register KYB vendors at service startup — S1T4.

Each KYB vendor adapter declares its capabilities; this loader iterates the
adapters known to the platform, calls ``declare_capabilities()`` on each, and
upserts it into the KYB vendor registry through
:class:`KybVendorRegistryService`.

Follows ``app.modules.rails.infrastructure.dev_rail_seed_loader`` exactly,
including *why the idempotency key is derived from the declaration*: hashing the
declaration into a v4-shaped UUID means an unchanged declaration reproduces the
same key and short-circuits as a duplicate (no write), while an edited
declaration produces a new key and the registry's ``ON CONFLICT DO UPDATE``
refreshes the row — without a per-boot key that would grow
``ledger.idempotency_record`` on every restart.

``KNOWN_KYB_ADAPTERS`` is empty on this branch: the Middesk and Trulioo adapters
are Epic 4.1 deliverables. Until then this loader is a no-op at startup, and the
S1T4 tests register fakes directly.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.kyb_vendor_registry_service import (
    KybVendorRegistryService,
)
from app.modules.onboarding.domain.entities.kyb_vendor_registration import KybVendorRegistration
from app.platform.idempotency.services import derive_internal_key
from app.shared.contracts.kyb import KYBVendorCapabilityDeclaration

logger = structlog.get_logger(__name__)

#: Step identifier for every key this loader derives. The key validator allows
#: lowercase letters and underscores only — no digits — so a declaration
#: revision cannot be encoded here; it is encoded in the parent hash instead.
_SEED_STEP_IDENTIFIER = "register_kyb_vendor"

#: Actor recorded on the idempotency records this loader creates.
_SEED_ACTOR_ID = "kyb_vendor_seed_loader"


@runtime_checkable
class _KybAdapterLike(Protocol):
    """The subset of ``app.modules.kyb.domain.ports.KYBAdapter`` this loader needs.

    Declared structurally so the onboarding module does not import the kyb
    module's internals (importlinter ``kyb-internals-are-private``). Any concrete
    ``KYBAdapter`` satisfies it.
    """

    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration: ...


#: KYB vendor adapter classes registered at startup. Empty until Epic 4.1 ships
#: the Middesk and Trulioo adapters.
KNOWN_KYB_ADAPTERS: tuple[type[_KybAdapterLike], ...] = ()


def _declaration_key(declaration: KYBVendorCapabilityDeclaration) -> str:
    """Derive a stable internal idempotency key from the declaration's content.

    ``uuid.UUID(bytes=..., version=4)`` forces the version and variant bits, so
    the digest becomes a genuinely v4-shaped UUID and passes the platform's
    ``_is_valid_uuid_v4`` check. Same declaration in, same key out.
    """
    payload = declaration.model_dump(mode="json")
    digest = hashlib.blake2b(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        digest_size=16,
    ).digest()
    parent_key = str(uuid.UUID(bytes=digest, version=4))
    return derive_internal_key(parent_key, _SEED_STEP_IDENTIFIER)


async def load_kyb_vendor_registry(
    session: AsyncSession,
    adapters: Sequence[type[_KybAdapterLike]] | None = None,
) -> list[KybVendorRegistration]:
    """Register every known KYB vendor. Safe to call on every boot.

    ``adapters`` overrides :data:`KNOWN_KYB_ADAPTERS` — the S1T4 tests pass their
    fakes here. Returns the registrations in declaration order.
    """
    service = KybVendorRegistryService(session)
    registered: list[KybVendorRegistration] = []

    for adapter_cls in adapters if adapters is not None else KNOWN_KYB_ADAPTERS:
        declaration = adapter_cls().declare_capabilities()
        registration = await service.register_vendor(
            declaration,
            idempotency_key=_declaration_key(declaration),
            actor_id=_SEED_ACTOR_ID,
        )
        registered.append(registration)
        logger.info(
            "kyb_vendor_seed.registered",
            vendor_id=declaration.vendor_id,
            processing_mode=declaration.processing_mode.value,
            supported_countries=declaration.supported_countries,
        )

    logger.info("kyb_vendor_seed.complete", vendor_count=len(registered))
    return registered


__all__ = ["KNOWN_KYB_ADAPTERS", "load_kyb_vendor_registry"]
