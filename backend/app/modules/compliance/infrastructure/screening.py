"""
Mock sanctions screening engine.

In production each function maps to an outbound HTTP call to a real provider
(ComplyAdvantage, Dow Jones, RBI watchlist API, etc.). The interface is
identical — swapping the implementation does not change the service layer.

The sanctioned-names list is a module-level frozenset so tests can inject
known-bad names deterministically.

This is a mock: no SDK, no network. It is therefore module infrastructure rather
than an integration (ARCHITECTURE.md §3). The DNFBP and AML *business rules* that
used to live in this file are policy and moved to domain/policies/screening.py.
"""

from __future__ import annotations

from app.modules.compliance.domain.entities.compliance import ScreeningStatus, ScreeningType
from app.modules.compliance.domain.policies.screening import _PROVIDER_MAP

# ---------------------------------------------------------------------------
# Configurable sanctioned-name lists (one per screening type)
# Names are compared case-insensitively.
# ---------------------------------------------------------------------------

SANCTIONED_NAMES_OFAC: frozenset[str] = frozenset(
    {
        "Terror Finance LLC",
        "OFAC Blocked Corp",
        "Sanctioned Entity OFAC",
    }
)

SANCTIONED_NAMES_UN: frozenset[str] = frozenset(
    {
        "UN Listed Group",
        "Sanctioned Entity UN",
    }
)

SANCTIONED_NAMES_EU: frozenset[str] = frozenset(
    {
        "EU Restricted Corp",
        "Sanctioned Entity EU",
    }
)

SANCTIONED_NAMES_RBI: frozenset[str] = frozenset(
    {
        "RBI Watchlist Entity",
        "Sanctioned Entity RBI",
    }
)

_LIST_MAP: dict[ScreeningType, frozenset[str]] = {
    ScreeningType.SANCTIONS_OFAC: SANCTIONED_NAMES_OFAC,
    ScreeningType.SANCTIONS_UN: SANCTIONED_NAMES_UN,
    ScreeningType.SANCTIONS_EU: SANCTIONED_NAMES_EU,
    ScreeningType.SANCTIONS_RBI: SANCTIONED_NAMES_RBI,
}


def screen_entity_sanctions(
    entity_name: str,
    screening_type: ScreeningType,
) -> tuple[ScreeningStatus, dict]:
    """Check a single entity name against one sanctions list."""
    sanctioned = _LIST_MAP[screening_type]
    normalized = entity_name.strip().upper()
    for name in sanctioned:
        if name.upper() == normalized:
            return ScreeningStatus.FAIL, {
                "provider": _PROVIDER_MAP[screening_type],
                "list": screening_type.value,
                "match": name,
                "confidence": "HIGH",
                "hit": True,
            }
    return ScreeningStatus.PASS, {
        "provider": _PROVIDER_MAP[screening_type],
        "list": screening_type.value,
        "match": None,
        "hit": False,
    }
