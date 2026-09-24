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

``KNOWN_KYB_ADAPTERS`` is populated (B4). It was an empty tuple, which made this
loader a documented no-op: ``load_kyb_vendor_registry`` ran at every boot
(``main.py`` -> ``bootstrap.load_kyb_vendor_registry_seed_data``) and registered
nothing, so ``onboarding.kyb_vendor_registration`` stayed empty and
``KybVendorRegistryService.get_vendor_for_country`` answered *manual review* for
every country including US and IN. The routing mechanism was complete; it simply
had no vendors in it.

The declarations come from the vendors themselves, via
``kyb_verification_adapter.known_vendor_declarations()`` — Middesk declares
``US``, Trulioo declares India and the rest. Country coverage is therefore stated
in exactly one place (each vendor's own ``declare_capabilities()``) and this
loader, the registry, and the adapter's in-process routing fallback all read that
same statement. Nothing here restates a country→vendor mapping.

Deliberately declaration-only: this seeds *which vendor covers what*, never
whether it is credentialled. A vendor with no API key is still the right vendor
for its country, and registering it is what lets
``KybVerificationAdapter._require_credentials`` fail with "middesk is not
enabled" instead of the much less useful "no vendor covers US".
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


def _known_kyb_adapters() -> tuple[type[_KybAdapterLike], ...]:
    """The KYB vendor adapter classes to register, resolved lazily.

    A function rather than a module-level tuple because resolving Middesk and
    Trulioo imports them, and this module is imported at application start —
    evaluating it eagerly would pull both vendor clients into every process
    that touches the loader, including ones that never register anything.

    The classes come from ``kyb_verification_adapter``'s loaders, which reach
    Middesk through the kyb public facade and Trulioo by dotted path through
    kyb's own resolver, so this module inherits that file's compliance with
    ``importlinter``'s ``kyb-internals-are-private`` contract and likewise
    imports nothing under ``app/modules/kyb/`` directly.
    """
    from app.modules.onboarding.infrastructure.adapters.kyb_verification_adapter import (
        _VENDOR_LOADERS,
    )

    return tuple(loader() for loader in _VENDOR_LOADERS.values())


#: Kept as a name because it is this module's published interface (``__all__``)
#: and the S1T4 tests import it. ``()`` means "resolve from
#: :func:`_known_kyb_adapters` at call time"; a caller passing its own sequence
#: to :func:`load_kyb_vendor_registry` still overrides both.
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

    ``adapters`` overrides the default set — the S1T4 tests pass their fakes
    here. With no override, the real Middesk and Trulioo adapters are resolved
    from :func:`_known_kyb_adapters`. Returns the registrations in declaration
    order.

    Registration is capability metadata only: no vendor is contacted, no
    credential is read, and a vendor with neither is still registered so that a
    later verification attempt fails as "vendor not enabled" rather than "no
    vendor covers this country".
    """
    service = KybVendorRegistryService(session)
    registered: list[KybVendorRegistration] = []

    resolved_adapters: Sequence[type[_KybAdapterLike]]
    if adapters is not None:
        resolved_adapters = adapters
    elif KNOWN_KYB_ADAPTERS:
        resolved_adapters = KNOWN_KYB_ADAPTERS
    else:
        resolved_adapters = _known_kyb_adapters()

    for adapter_cls in resolved_adapters:
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
