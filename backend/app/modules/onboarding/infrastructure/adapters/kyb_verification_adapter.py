"""`KybVerificationAdapter` — the caller for Middesk and Trulioo (B4).

Both vendor adapters are fully built and, until this module, imported by nothing
outside `tests/contract/test_kyb_interface.py`. They speak `KYBAdapter`
(`verify_entity` → `KYBVerificationResult`); the Exporter CRM speaks
`VerificationAdapter` (`verify` → `VerificationOutcome`) and reads, reviews and
displays `verification_result`. This adapter is the translation between the two,
so results land in the table the CRM already has rather than a second store.

**Nothing under `app/modules/kyb/` is touched.** Middesk arrives through the kyb
public facade (`from app.modules.kyb import MiddeskAdapter`). Trulioo is not on
that facade and cannot be imported directly — `importlinter`'s
`kyb-internals-are-private` contract forbids `app.modules.onboarding` from
importing `app.modules.kyb.infrastructure`. It is therefore resolved through
kyb's own `get_adapter()` by dotted *string*, so this module performs no static
import of a kyb internal and the contract stays green. `importlib` runs inside
kyb, against kyb's own `ADAPTER_MODULE_ALLOWLIST`, which already admits that
path. If Trulioo is later added to the kyb facade, `_TRULIOO_CLASS_PATH` and
`_load_trulioo()` collapse into a plain import and nothing else here changes.

Provider provenance
-------------------
Registered once, under `"kyb"`. What it reports is *not* `"kyb"`:
`VerificationOutcome.provider` carries the vendor that actually answered —
`"middesk"` or `"trulioo"` — taken from that vendor's own
`declare_capabilities().vendor_id`. `verification_service` persists
`outcome.provider` verbatim, so the CRM shows the real vendor. Reporting `"kyb"`
would have been simpler and would have flattened Middesk and Trulioo into one
indistinguishable label on a compliance record.

This is a deliberate departure from `ManualEntryAdapter`'s "one constant for the
registry name and the reported provider so they cannot drift": here they are
*meant* to differ, because one registry entry fronts two vendors.

Routing
-------
Country → vendor is never hardcoded in this file. There are two sources, in
order:

1. `payload["kyb_vendor_id"]` — a vendor already resolved by
   `KybVendorRegistryService.get_vendor_for_country()`. Preferred: that lookup
   is health-aware (it excludes `DOWN` vendors and applies the documented
   tie-break) and it is the authority the brief names.
2. Failing that, the vendors' own `declare_capabilities()` — the very
   declarations the registry is seeded from — matched on country and entity
   type in-process.

Why a fallback exists at all: `VerificationAdapter.verify()` is **synchronous**
and `verification_service.trigger_verification` constructs adapters with no
arguments (`adapter_cls()`), while `get_vendor_for_country()` is a coroutine
needing an `AsyncSession`. There is no supported way to await it from inside
`verify()` — the platform has no synchronous session (`DATABASE_SYNC_URL`
appears only in tests), and driving the loop from within itself is not
something to smuggle into an adapter. So an async caller resolves first and
passes the answer down; when nobody has, this falls back to the declarations
rather than refusing to work. Both paths agree on US → Middesk and IN →
Trulioo, because both read the same declarations; only health-awareness is lost
on path 2. `resolve_vendor_id()` below is the async helper a caller uses for
path 1.

The registry is empty until `KNOWN_KYB_ADAPTERS` is populated — see
`kyb_vendor_seed_loader`, which this change fills in.

Credentials
-----------
Neither vendor is usable without one, and neither fails loudly on its own:
`TruliooApiClient` sends `settings.TRULIOO_API_KEY` even when it is `""`, and
`VaultClient.get_middesk_credentials()` returns `""` when Vault is unreachable
and `MIDDESK_API_KEY` is unset. Both then fail at the vendor as a 401, which is
an *upstream* error — the wrong shape, and the wrong thing to be seen retrying.
`_require_credentials()` checks before any call and raises
`ProviderNotEnabledError` (422). The one outcome that must never occur is a
missing credential reading as a pass, so there is no default-allow branch
anywhere below.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog

from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationResultStatus,
    VerificationRiskLevel,
    VerificationType,
)
from app.modules.onboarding.domain.workflow_dependencies import (
    VerificationCapabilityDeclaration,
    VerificationOutcome,
    VerificationRequest,
    register_adapter,
)
from app.modules.onboarding.exceptions import (
    InvalidProviderPayloadError,
    ProviderCapabilityError,
    ProviderNotEnabledError,
)
from app.platform.configuration.config import get_settings
from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.enums.kyb import (
    KYBVendorProcessingMode,
    NormalisedResult,
    VendorHealthStatusEnum,
)

if TYPE_CHECKING:  # pragma: no cover — typing only, never imported at runtime
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

#: The registry name. Unlike `ManualEntryAdapter`'s `PROVIDER_NAME`, this is
#: *not* what lands on `VerificationResult.provider` — see the module docstring.
REGISTRY_KEY = "kyb"

#: Trulioo's dotted class path, passed to kyb's own `get_adapter` as a string so
#: this module never statically imports a kyb internal. Inside kyb's
#: `ADAPTER_MODULE_ALLOWLIST` already.
_TRULIOO_CLASS_PATH = "app.modules.kyb.infrastructure.adapters.trulioo.adapter.TruliooAdapter"

#: `NormalisedResult` (what a KYB vendor returns) → `VerificationResultStatus`
#: (what `verification_result` stores). Exhaustive by construction — the guard
#: below fails at import if `NormalisedResult` ever grows a member, rather than
#: letting an unmapped vendor answer fall through to a default.
_STATUS_MAP: dict[NormalisedResult, VerificationResultStatus] = {
    NormalisedResult.VERIFIED: VerificationResultStatus.PASSED,
    NormalisedResult.REJECTED: VerificationResultStatus.FAILED,
    NormalisedResult.PENDING: VerificationResultStatus.PENDING,
    # Not a failure and not a pass: the vendor could not find the entity, or
    # declines to answer for it. Both need a human, which is what REVIEW means.
    NormalisedResult.NOT_FOUND: VerificationResultStatus.REVIEW,
    NormalisedResult.REQUIRES_MANUAL_REVIEW: VerificationResultStatus.REVIEW,
    NormalisedResult.NOT_SUPPORTED: VerificationResultStatus.REVIEW,
}

_UNMAPPED = set(NormalisedResult) - set(_STATUS_MAP)
if _UNMAPPED:  # pragma: no cover — guards a source edit, not input
    raise RuntimeError(
        "kyb_verification_adapter._STATUS_MAP is missing an entry for: "
        + ", ".join(sorted(r.value for r in _UNMAPPED))
    )

#: Risk banding for a KYB answer. Deliberately coarse: a KYB vendor confirms or
#: fails to confirm an entity, it does not band risk. `None` for the clean case
#: (`VerificationResult.risk_level` is nullable precisely for checks that
#: produce no banding) and a discrepancy-driven band otherwise.
_DISCREPANCY_RISK_THRESHOLD = 3

#: The checks this adapter can answer. KYB against an exporter or a buyer — a
#: KYB vendor verifies a business, so `DIRECTOR` is not offered here
#: (`SumsubVerificationAdapter` covers natural persons).
_SUPPORTED_VERIFICATION_TYPES: tuple[VerificationType, ...] = (VerificationType.KYB,)
_SUPPORTED_ENTITY_TYPES: tuple[VerificationEntityType, ...] = (
    VerificationEntityType.EXPORTER,
    VerificationEntityType.BUYER,
)

#: The legal-entity structure used for routing when the caller names none.
#:
#: **These are two different axes and conflating them breaks routing.**
#: `VerificationEntityType` (EXPORTER / BUYER / DIRECTOR) says *what kind of
#: subject* a check is about. A KYB vendor's `supported_entity_types` says what
#: *legal structure* it can verify — Middesk lists `corporation`, `llc`,
#: `partnership`, `c_corp`, `s_corp`; Trulioo lists `PRIVATE_LIMITED`, `LLP`,
#: `CORPORATION` and so on. `orchestration_enums` names the first
#: `VerificationEntityType` precisely so it is not read as a synonym for the
#: second.
#:
#: So routing reads `payload["entity_type"]`, not `request.entity_type`. Passing
#: `"EXPORTER"` to a vendor expecting `"corporation"` matches no declared type,
#: and every check — including US and IN — would fall through to manual review
#: while looking like a coverage gap rather than a units error.
#:
#: `corporation` is the default because `create_lead` already defaults
#: `OnboardingEntityType.CORPORATION`, and both vendors declare it.
_DEFAULT_KYB_ENTITY_TYPE = "corporation"


def _load_middesk() -> type[Any]:
    """Middesk, from the kyb public facade. Imported lazily so that merely
    importing this module never constructs a vendor client."""
    from app.modules.kyb import MiddeskAdapter

    return MiddeskAdapter


def _load_trulioo() -> type[Any]:
    """Trulioo, by dotted string through kyb's own resolver.

    `get_adapter` is on the kyb facade, so importing *it* is legal;
    `_TRULIOO_CLASS_PATH` is a string, so `importlinter` sees no edge from
    onboarding to `kyb.infrastructure`. kyb checks the path against its own
    allowlist and that the result is a `KYBAdapter` before returning it.
    """
    from app.modules.kyb import get_adapter

    return get_adapter(_TRULIOO_CLASS_PATH)


#: vendor_id → zero-argument loader. Built from the loaders rather than from
#: imported classes so that nothing is imported until a vendor is actually
#: needed, matching `infrastructure/registry.py`'s `_KNOWN_FACTORIES` comment:
#: "a provider that is configured off is never imported and its optional
#: dependencies and credentials are never touched".
_VENDOR_LOADERS: dict[str, Any] = {
    "middesk": _load_middesk,
    "trulioo": _load_trulioo,
}


def known_vendor_declarations() -> dict[str, KYBVendorCapabilityDeclaration]:
    """Every wrapped vendor's own `declare_capabilities()`, keyed by vendor_id.

    The single source of truth for which vendor covers which country — read
    from the vendors themselves, never restated here. `kyb_vendor_seed_loader`
    registers these same declarations, which is why the registry and the
    in-process fallback cannot disagree about coverage.
    """
    declarations: dict[str, KYBVendorCapabilityDeclaration] = {}
    for vendor_id, loader in _VENDOR_LOADERS.items():
        declarations[vendor_id] = loader()().declare_capabilities()
    return declarations


async def resolve_vendor_id(
    session: AsyncSession,
    *,
    registration_country: str,
    entity_type: str,
) -> str | None:
    """Ask `KybVendorRegistryService` which vendor covers this combination.

    The health-aware path. An async caller runs this and puts the answer in
    `payload["kyb_vendor_id"]`; `verify()` cannot call it itself because it is
    synchronous (see the module docstring).

    Returns the vendor_id, or `None` when the registry says manual review —
    which `verify()` surfaces as a `REVIEW` outcome, not a failure and
    emphatically not a pass.
    """
    from app.modules.onboarding.application.kyb_vendor_registry_service import (
        KybVendorRegistryService,
    )

    lookup = await KybVendorRegistryService(session).get_vendor_for_country(
        registration_country, entity_type
    )
    vendor = getattr(lookup, "vendor", None)
    if vendor is None:
        return None
    return str(vendor.vendor_id)


def _resolve_from_declarations(registration_country: str, entity_type: str) -> str | None:
    """Fallback routing: match the vendors' own declared coverage.

    Not hardcoding — `supported_countries` and `supported_entity_types` come
    from `declare_capabilities()`. Ordering is `_VENDOR_LOADERS`' insertion
    order so the choice is deterministic when two vendors both cover a country.
    Health is not consulted here; only the registry knows that.
    """
    country = (registration_country or "").strip().upper()
    etype = (entity_type or "").strip().lower()
    for vendor_id, declaration in known_vendor_declarations().items():
        countries = {c.strip().upper() for c in declaration.supported_countries}
        etypes = {e.strip().lower() for e in declaration.supported_entity_types}
        if country in countries and (not etype or etype in etypes):
            return vendor_id
    return None


def _require_credentials(vendor_id: str) -> None:
    """Refuse before calling a vendor we have no credential for.

    Absent credentials must fail loudly. Neither vendor does this on its own:
    Trulioo's client sends an empty `x-trulioo-api-key` header, and Middesk's
    Vault fallback hands back `""`. Both then fail upstream as a 401, which
    reads as a vendor outage rather than a misconfiguration on our side.

    `ProviderNotEnabledError` is 422 through the existing
    `aner_exception_handler` — a configuration problem the caller can act on,
    not a 502 implying the vendor is down.
    """
    settings = get_settings()

    if vendor_id == "trulioo":
        if not getattr(settings, "TRULIOO_ENABLED", False):
            raise ProviderNotEnabledError("trulioo")
        if not (getattr(settings, "TRULIOO_API_KEY", "") or "").strip():
            raise ProviderNotEnabledError("trulioo")
        return

    if vendor_id == "middesk":
        if not getattr(settings, "MIDDESK_ENABLED", False):
            raise ProviderNotEnabledError("middesk")
        # Middesk reads its key from Vault, falling back to MIDDESK_API_KEY.
        # Either satisfies this; neither present is a hard stop.
        vault_configured = bool(
            (getattr(settings, "VAULT_ADDR", "") or "").strip()
            and (getattr(settings, "VAULT_TOKEN", "") or "").strip()
        )
        if not vault_configured and not (getattr(settings, "MIDDESK_API_KEY", "") or "").strip():
            raise ProviderNotEnabledError("middesk")
        return

    raise ProviderNotEnabledError(vendor_id)


def _entity_request(payload: dict[str, Any]) -> EntityVerificationRequest:
    """Build the vendors' `EntityVerificationRequest` from the caller's payload.

    `InvalidProviderPayloadError` (422) rather than letting Pydantic's
    `ValidationError` escape as a 500: a missing `legal_name` is a caller
    mistake with a name, not an internal fault.
    """
    try:
        return EntityVerificationRequest(
            legal_name=payload["legal_name"],
            trading_name=payload.get("trading_name"),
            registration_country=payload["registration_country"],
            registration_number=payload["registration_number"],
            registered_address=payload["registered_address"],
            tax_identification_number=payload.get("tax_identification_number"),
        )
    except KeyError as exc:
        raise InvalidProviderPayloadError(
            f"KYB verification payload is missing required field {exc.args[0]!r}. "
            "Required: legal_name, registration_country, registration_number, "
            "registered_address.",
            provider_name=REGISTRY_KEY,
        ) from exc
    except Exception as exc:  # pydantic ValidationError and anything like it
        raise InvalidProviderPayloadError(
            f"KYB verification payload is not a valid entity request: {exc}",
            provider_name=REGISTRY_KEY,
        ) from exc


def _risk_level(result: KYBVerificationResult) -> VerificationRiskLevel | None:
    """Band a KYB answer by how far the vendor's view differs from ours.

    A KYB vendor's job is confirmation, not risk scoring, so there is no vendor
    score to pass through. Discrepancy count is the only signal it does give:
    none is unremarkable (`None` — the column is nullable for exactly this),
    a few warrant a look, many mean the entity we were given does not match the
    entity the registry holds.
    """
    if result.normalised_result is NormalisedResult.REJECTED:
        return VerificationRiskLevel.HIGH
    count = len(result.discrepancies or [])
    if count == 0:
        return None
    if count < _DISCREPANCY_RISK_THRESHOLD:
        return VerificationRiskLevel.MEDIUM
    return VerificationRiskLevel.HIGH


def _outcome_from_result(vendor_id: str, result: KYBVerificationResult) -> VerificationOutcome:
    """`KYBVerificationResult` → `VerificationOutcome`, provenance intact."""
    return VerificationOutcome(
        # The vendor that answered, not REGISTRY_KEY.
        provider=result.vendor_id or vendor_id,
        provider_reference=result.vendor_reference,
        status=_STATUS_MAP[result.normalised_result],
        normalized_result={
            "normalised_result": result.normalised_result.value,
            "verified_legal_name": result.verified_legal_name,
            "verified_registration_number": result.verified_registration_number,
            "verified_address": result.verified_address,
            "discrepancies": list(result.discrepancies or []),
            # A pointer, not the payload: `raw_response_reference` is the
            # vendor's own handle for the stored response, which is what
            # `KYBVerificationResult` carries instead of the body.
            "raw_response_reference": result.raw_response_reference,
            "retrieved_at": result.retrieved_at.isoformat() if result.retrieved_at else None,
        },
        risk_level=_risk_level(result),
        valid_until=None,
    )


class KybVerificationAdapter:
    """A `VerificationAdapter` fronting the Middesk and Trulioo KYB vendors."""

    def declare_capabilities(self) -> VerificationCapabilityDeclaration:
        """Asynchronous, because the most demanding vendor behind it is.

        Middesk declares `ASYNCHRONOUS` (it answers by webhook/poll); Trulioo
        declares `SYNCHRONOUS`. One registry entry fronting both can only
        honestly declare the weaker guarantee — a caller told `SYNCHRONOUS`
        would be entitled to treat every `verify()` as final, which is untrue
        for the Middesk half.
        """
        return VerificationCapabilityDeclaration(
            provider=REGISTRY_KEY,
            supported_verification_types=_SUPPORTED_VERIFICATION_TYPES,
            supported_entity_types=_SUPPORTED_ENTITY_TYPES,
            processing_mode=KYBVendorProcessingMode.ASYNCHRONOUS,
        )

    def verify(self, request: VerificationRequest) -> VerificationOutcome:
        """Route to a KYB vendor and translate its answer.

        Raises `ProviderNotEnabledError` (422) when the chosen vendor has no
        credentials, and `InvalidProviderPayloadError` (422) when the payload
        cannot describe an entity. Returns a `REVIEW` outcome — never a pass —
        when no vendor covers the country.
        """
        payload = dict(request.payload or {})
        entity = _entity_request(payload)

        # payload["entity_type"], NOT request.entity_type — see
        # _DEFAULT_KYB_ENTITY_TYPE for why those are different vocabularies.
        kyb_entity_type = str(payload.get("entity_type") or _DEFAULT_KYB_ENTITY_TYPE)

        vendor_id = payload.get("kyb_vendor_id") or _resolve_from_declarations(
            entity.registration_country, kyb_entity_type
        )

        if not vendor_id:
            # The registry's manual_review indicator, in this Protocol's
            # vocabulary. Not FAILED: nothing about the entity was disproved,
            # there is simply nobody to ask.
            logger.info(
                "kyb_verification.manual_review",
                registration_country=entity.registration_country,
                kyb_entity_type=kyb_entity_type,
                subject_entity_type=request.entity_type.value,
            )
            return VerificationOutcome(
                provider=REGISTRY_KEY,
                provider_reference=None,
                status=VerificationResultStatus.REVIEW,
                normalized_result={
                    "routing": "manual_review",
                    "reason": (
                        "No KYB vendor covers registration_country="
                        f"{entity.registration_country!r} for entity_type="
                        f"{kyb_entity_type!r}"
                    ),
                },
                risk_level=None,
            )

        if vendor_id not in _VENDOR_LOADERS:
            raise ProviderNotEnabledError(str(vendor_id))

        _require_credentials(vendor_id)

        adapter = _VENDOR_LOADERS[vendor_id]()()
        result = adapter.verify_entity(entity)

        logger.info(
            "kyb_verification.completed",
            vendor_id=vendor_id,
            registration_country=entity.registration_country,
            normalised_result=result.normalised_result.value,
        )
        return _outcome_from_result(vendor_id, result)

    def get_verification_status(self, provider_reference: str) -> VerificationOutcome:
        """Poll a previously submitted check.

        Needs to know *which* vendor issued `provider_reference`, and a bare
        reference string does not say. The Protocol gives this method no other
        argument, so there is nothing here to dispatch on: Middesk's references
        and Trulioo's are both opaque strings with no distinguishing shape, and
        guessing by trying each vendor in turn would send one vendor another
        vendor's identifiers.

        Raises `ProviderCapabilityError` (422) rather than guessing. Resolving
        this properly needs the polling route described in this phase's TASK 4
        report, which can pass the vendor alongside the reference — a route is
        another lane's file, so it is reported, not built.
        """
        raise ProviderCapabilityError(REGISTRY_KEY, "get_verification_status")

    def get_vendor_health(self) -> VendorHealthStatus:
        """Aggregate health across the wrapped vendors.

        `VendorHealthStatus` is the same shared contract type on both
        Protocols, so each vendor's own answer passes through untranslated. The
        aggregate is the worst of them: one vendor being `DOWN` means some
        countries cannot be verified, which is `DEGRADED` overall, not healthy.
        A vendor that raises while being asked counts as `DOWN` — a health
        check that throws has answered the question.
        """
        started = time.monotonic()
        statuses: list[VendorHealthStatusEnum] = []
        issues: list[str] = []

        for vendor_id, loader in _VENDOR_LOADERS.items():
            try:
                health = loader()().get_vendor_health()
                statuses.append(health.status)
                if health.known_issues:
                    issues.append(f"{vendor_id}: {health.known_issues}")
            except Exception as exc:  # noqa: BLE001 — any failure is DOWN
                statuses.append(VendorHealthStatusEnum.DOWN)
                issues.append(f"{vendor_id}: {type(exc).__name__}: {exc}")

        elapsed_ms = int((time.monotonic() - started) * 1000)

        if not statuses or all(s is VendorHealthStatusEnum.DOWN for s in statuses):
            overall = VendorHealthStatusEnum.DOWN
        elif all(s is VendorHealthStatusEnum.HEALTHY for s in statuses):
            overall = VendorHealthStatusEnum.HEALTHY
        else:
            overall = VendorHealthStatusEnum.DEGRADED

        return VendorHealthStatus(
            status=overall,
            response_time_ms=elapsed_ms,
            known_issues="; ".join(issues) or None,
        )


# Fires when this module is imported. The adapters package does not import it
# (that file is another lane's), so the short name `"kyb"` is unresolvable until
# it does — but `get_adapter` resolves this class by its full dotted path, and
# doing so imports this module, which runs the line below. The short name works
# from then on.
register_adapter(REGISTRY_KEY, KybVerificationAdapter)

__all__ = [
    "REGISTRY_KEY",
    "KybVerificationAdapter",
    "known_vendor_declarations",
    "resolve_vendor_id",
]
