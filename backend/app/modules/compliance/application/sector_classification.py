"""S0T2's classification lookup, in the shape the rule engine asks for.

A thin adapter and deliberately nothing more. S0T2 owns the resolution — which
authority's classification governs a sector on a date, and the corridor →
country → framework precedence that decides it — and that logic lives in
:mod:`app.modules.compliance.application.sector_risk_service`. This translates
the answer into the port S0T3 declares (``domain.ports.SectorClassificationLookup``)
so the evaluator depends on a shape it owns rather than on S0T2's return type.

This replaces ``StubSectorClassificationLookup``, which existed only because the
registry once stored a single free-text ``jurisdiction`` column and so could not
express the precedence ladder. It now stores a ``jurisdiction_type`` /
``jurisdiction_value`` pair (AL-443), the real lookup resolves all three rungs,
and the stub's central compromise — reporting ``framework``/``FATF`` whatever
actually answered — became a lie rather than a limitation. It was deleted rather
than repaired.

The mapping is total and lossless in the direction S0T3 needs, taking
``SectorRiskResolution`` to ``ResolvedSectorClassification``:

* ``risk_tier`` -> ``risk_tier``, as the enum's value
* ``classification_label`` -> ``classification_label``
* ``jurisdiction_type`` + ``jurisdiction_value`` -> ``resolving_jurisdiction``
* ``matched`` -> ``found``
"""

from datetime import date

from app.modules.compliance.application.sector_risk_service import (
    get_sector_risk_classification,
)
from app.modules.compliance.domain.jurisdiction import ResolvingJurisdiction
from app.modules.compliance.domain.ports import (
    ResolvedSectorClassification,
    SectorRiskRepository,
)


class SectorRegistryClassificationLookup:
    """Resolves a sector's classification against the seeded sector registry.

    Satisfies ``SectorClassificationLookup``. Holds no state beyond the
    repository, and never raises for an unknown sector — an absent
    classification is an answer, reported as ``found=False``.
    """

    def __init__(self, repository: SectorRiskRepository) -> None:
        self._repository = repository

    async def resolve(
        self,
        sector_code: str,
        corridor_id: str | None,
        country_jurisdiction: str | None,
        as_of_date: date,
    ) -> ResolvedSectorClassification:
        resolution = await get_sector_risk_classification(
            sector_code,
            corridor_id,
            country_jurisdiction,
            as_of_date,
            self._repository,
        )

        # ``matched`` is the authority on whether anything was found, rather than
        # the tier: an unrated sector and one a regulator deliberately rated
        # ``standard`` both carry the standard tier, and only the first is a gap.
        if not resolution.matched:
            return ResolvedSectorClassification(
                risk_tier=resolution.risk_tier.value,
                classification_label=None,
                resolving_jurisdiction=None,
                found=False,
            )

        # A matched resolution always names its authority — the row it came from
        # has both columns NOT NULL — so the pair is never half-populated here.
        # Stated as a check rather than left to the type system's optimism: the
        # alternative to failing here is a ``ResolvingJurisdiction`` carrying a
        # None, which would travel all the way into an audit record before
        # anyone noticed the authority was missing.
        jurisdiction_type = resolution.jurisdiction_type
        jurisdiction_value = resolution.jurisdiction_value
        if jurisdiction_type is None or jurisdiction_value is None:
            raise ValueError(
                "a matched sector classification must name its authority; got "
                f"jurisdiction_type={jurisdiction_type!r}, "
                f"jurisdiction_value={jurisdiction_value!r} "
                f"for sector_code={sector_code!r}"
            )

        return ResolvedSectorClassification(
            risk_tier=resolution.risk_tier.value,
            classification_label=resolution.classification_label,
            resolving_jurisdiction=ResolvingJurisdiction(
                type=jurisdiction_type,
                value=jurisdiction_value,
            ),
            found=True,
        )
