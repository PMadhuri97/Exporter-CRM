"""Interfaces the compliance module requires of its infrastructure.

Ports are owned by the consumer (ARCHITECTURE.md §2), so the shape of each
registry lookup is decided here and satisfied elsewhere.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.entities.registry import (
    PurposeCodeCanonical,
    PurposeCodeCorridorMapping,
)
from app.modules.compliance.domain.entities.sector_registry import (
    SectorCodeExternalMapping,
    SectorCodeRegistry,
    SectorRiskClassification,
)
from app.modules.compliance.domain.jurisdiction import (
    JurisdictionType,
    ResolvingJurisdiction,
)


class PurposeCodeRepository(Protocol):
    async def get_canonical_history(self, canonical_code: str) -> list[PurposeCodeCanonical]:
        """Every row ever defined for this canonical code, regardless of date.

        A code may be retired and later reinstated, so more than one row can
        share a canonical_code — each with its own, non-overlapping validity
        window (enforced by ``ex_purpose_code_canonical_validity``). Deciding
        which row, if any, is in force on a given date is a domain concern, not
        a query concern — the same split already used for corridor mappings.
        An empty list means the code has never existed.
        """
        ...

    async def get_corridor_mappings(
        self, canonical_code: str, corridor_id: str
    ) -> list[PurposeCodeCorridorMapping]: ...

    async def get_mappings(
        self, corridor_id: str, external_code: str
    ) -> list[PurposeCodeCorridorMapping]: ...


class SectorRiskRepository(Protocol):
    """Read access to the sector registry.

    Returns rows regardless of their effective dates; deciding which row is in
    force on a given date is a domain concern, not a query concern. The
    exclusion constraints guarantee at most one row per key is in force, but the
    methods still return lists — a query that silently discarded a second row
    would hide the seed-data error the constraint exists to surface.
    """

    async def get_sector(self, sector_code: str) -> SectorCodeRegistry | None: ...

    async def list_classifications(
        self,
        sector_code: str,
        jurisdiction_type: JurisdictionType,
        jurisdiction_value: str,
    ) -> list[SectorRiskClassification]: ...

    async def list_external_mappings(
        self, sector_code: str, external_standard: str
    ) -> list[SectorCodeExternalMapping]: ...


class ComplianceRuleRepository(Protocol):
    async def list_rules(self) -> list[ComplianceRule]: ...


class IndicativeRateProvider(Protocol):
    """A rate for valuing a settlement against a threshold in another currency.

    Indicative, not dealable. This values an amount so a threshold can be
    compared; it never prices a trade, and nothing settles at the rate it
    returns. Owned here rather than taken from the FX module because the shape
    compliance needs is decided by the question compliance asks (ARCHITECTURE.md
    §2), and because a compliance decision must not depend on quote lifecycle,
    spreads or locking.

    Rates are ``Decimal``. A float cannot represent a rate exactly, and a
    threshold comparison that lands one minor unit either side of the boundary
    decides whether a payment is reviewed.

    Implementations raise on an unavailable pair rather than returning a
    sentinel; the caller treats any failure as the threshold being met.
    """

    async def get_indicative_rate(
        self, from_asset_code: str, to_asset_code: str
    ) -> Decimal: ...


@dataclass(frozen=True)
class ResolvedSectorClassification:
    """What S0T2's lookup answers, in the shape S0T2 defines.

    ``resolving_jurisdiction`` names the authority whose classification won, and
    is ``None`` exactly when ``found`` is False.

    ``found`` is not redundant with a ``standard`` tier. A sector nobody has
    rated and a sector a regulator deliberately rated ``standard`` are different
    facts, and S0T2 requires the first to be reported explicitly rather than
    defaulting silently into the second.
    """

    risk_tier: str
    classification_label: str | None
    resolving_jurisdiction: ResolvingJurisdiction | None
    found: bool

    def __post_init__(self) -> None:
        if self.found != (self.resolving_jurisdiction is not None):
            raise ValueError(
                "found and resolving_jurisdiction must agree; got "
                f"found={self.found!r}, "
                f"resolving_jurisdiction={self.resolving_jurisdiction!r}"
            )


class SectorClassificationLookup(Protocol):
    """S0T2's classification lookup, as the rule engine needs to ask it.

    Both jurisdiction arguments are optional: a caller that knows only the
    corridor passes ``None`` for the country and the resolution simply skips
    that rung of the ladder.

    Never raises for an unknown sector: an absent classification is an answer,
    reported as ``found=False``.
    """

    async def resolve(
        self,
        sector_code: str,
        corridor_id: str | None,
        country_jurisdiction: str | None,
        as_of_date: date,
    ) -> ResolvedSectorClassification: ...


class ComplianceAuditSink(Protocol):
    async def record_threshold_rate_unavailable(
        self,
        *,
        from_asset_code: str,
        to_asset_code: str,
        reason: str,
        error_type: str | None = None,
        rule_ids: tuple[str, ...] = (),
    ) -> None: ...
