"""Risk Rating Calculation Policy (ANER-4.1-S5T2).

Pure, deterministic composite risk-rating calculator. Given the onboarding
signals the ticket names — entity type, registration country, sector code,
declared monthly volume, UBO count, UBO PEP status, screening result and KYB
discrepancies — it produces a numeric score, a ``risk_rating`` derived from
that score via configurable thresholds, a human-readable ``risk_rating_factors``
explanation, and an ``edd_required`` / ``edd_reason`` pair.

This module is pure, mirroring ``document_requirements_service.py``: the
service receives an already-parsed configuration mapping and never touches the
filesystem, a database, or any other Epic. Reading and locating the GitOps YAML
is the responsibility of
``app.modules.onboarding.infrastructure.risk_rating_config_loader``. Nothing
in this module calls Epic 3.2, Epic 5.4, or any ``app.modules.*`` outside
``onboarding``.

Determinism
-----------
``calculate()`` is a pure function of its arguments and ``self.config``: the
same inputs always produce the same :class:`RiskRatingResult`. It has no
randomness, no clock read, no I/O. See
``tests/unit/test_s5t2_risk_rating.py::test_calculation_is_deterministic``.

Weights and thresholds are configuration, not code
---------------------------------------------------
Every score in the output is looked up from ``self.config`` — there is no
hardcoded "if sector_code == 'VASP': risk_rating = CRITICAL" branch anywhere
in this file. A VASP/crypto sector code scores CRITICAL only because the
GitOps config gives it a score high enough to clear
``thresholds.high_max`` on its own (see the config file's comments). Changing
any weight or threshold is therefore purely a configuration change.

EDD consequence is future work (ANER-4.1-S5T3, explicitly out of scope here)
------------------------------------------------------------------------------
This service computes ``edd_required`` / ``edd_reason``. It does **not** act
on them. There is currently no automated consequence of ``edd_required=True``
— no maker-checker request is raised, no Temporal workflow is parked. That
requires Epic 5.4 (Maker-Checker), which does not exist yet, or an explicit
product decision about whether onboarding's EDD flow should route through
Epic 4.3's case-resolution stand-in
(``CaseLifecycleService.propose_resolution`` / ``decide_resolution``) — a
decision this module does not make unilaterally. ``onboarding`` does not
import from ``cases``, and nothing here changes that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingRiskRating,
    OnboardingScreeningResult,
    UboPepStatus,
)
from app.modules.onboarding.domain.kyb_vendor_selection import (
    normalise_country,
    normalise_entity_type,
)
from app.modules.onboarding.exceptions import RiskRatingConfigurationError

# ── Config shape ─────────────────────────────────────────────────────────────

_TOP_LEVEL_REQUIRED_KEYS = frozenset(
    {
        "version",
        "entity_type_risk",
        "country_risk",
        "sector_risk",
        "volume_risk",
        "ubo_risk",
        "pep_risk",
        "screening_risk",
        "kyb_discrepancy_risk",
        "thresholds",
    }
)

_COUNTRY_RISK_REQUIRED_KEYS = frozenset(
    {
        "low_risk_countries",
        "medium_risk_countries",
        "high_risk_countries",
        "fatf_grey_list",
        "fatf_black_list",
        "default_band",
        "band_scores",
        "fatf_grey_list_score",
        "fatf_black_list_score",
    }
)

_SECTOR_RISK_REQUIRED_KEYS = frozenset(
    {"dnfbp_sector_codes", "dnfbp_score", "critical_sector_codes", "critical_sector_score", "default_score"}
)

_PEP_RISK_REQUIRED_KEYS = frozenset({"pep_score", "pep_associate_score", "none_score"})

_SCREENING_RISK_REQUIRED_KEYS = frozenset({"scores", "default_score"})

_KYB_DISCREPANCY_RISK_REQUIRED_KEYS = frozenset({"score_per_discrepancy", "max_score"})

_THRESHOLDS_REQUIRED_KEYS = frozenset({"low_max", "medium_max", "high_max"})


def _normalise_sector(value: str | None) -> str:
    return (value or "").strip().upper()


def _normalise_screening_result(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().upper()


def _normalise_pep_status(value: str) -> str:
    return value.strip().upper()


# ── Result ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskRatingResult:
    """The outcome of one deterministic :meth:`RiskRatingService.calculate` call."""

    score: int
    risk_rating: OnboardingRiskRating
    factors: list[dict[str, Any]] = field(default_factory=list)
    edd_required: bool = False
    edd_reason: str | None = None
    config_version: str = "unknown"

    def to_risk_rating_factors_json(self) -> dict[str, Any]:
        """JSON payload for the ``onboarding_request.risk_rating_factors`` column.

        ``onboarding_request`` now has dedicated ``edd_required`` / ``edd_reason``
        columns (migration ``onboarding_0004_screening_fix``), fixing
        the gap this docstring used to describe (the S1 schema, as originally
        implemented, had neither, so callers embedded both values here as a
        workaround). Callers now write ``edd_required``/``edd_reason`` to those
        real columns directly. ``edd_required`` and ``edd_reason`` are *also*
        kept in this JSON payload — a deliberate, harmless duplication: this
        JSON is one of the write-once, audit-grade columns protected by
        ``trg_onboarding_request_field_immutability``, so it captures a fixed
        snapshot of the values at the moment the rating was assigned even if
        something else were ever able to touch the plain columns. Callers
        should treat the dedicated columns as the source of truth for reads.
        """
        return {
            "score": self.score,
            "risk_rating": self.risk_rating.value,
            "factors": self.factors,
            "edd_required": self.edd_required,
            "edd_reason": self.edd_reason,
            "config_version": self.config_version,
        }


# ── Service ──────────────────────────────────────────────────────────────────


class RiskRatingService:
    """Composite onboarding risk-rating calculator, config-driven and pure."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = self._validate_config(config)

    # ── validation ───────────────────────────────────────────────────────────

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise RiskRatingConfigurationError(
                f"Invalid risk rating configuration: expected a mapping, got {type(config).__name__}"
            )

        missing = _TOP_LEVEL_REQUIRED_KEYS - set(config)
        if missing:
            raise RiskRatingConfigurationError(
                f"Invalid risk rating configuration: missing top-level key(s) {sorted(missing)}"
            )

        self._validate_entity_type_risk(config["entity_type_risk"])
        self._validate_country_risk(config["country_risk"])
        self._validate_sector_risk(config["sector_risk"])
        self._validate_band_config(config["volume_risk"], where="volume_risk", max_key="max_usd")
        self._validate_band_config(config["ubo_risk"], where="ubo_risk", max_key="max_count")
        self._validate_pep_risk(config["pep_risk"])
        self._validate_screening_risk(config["screening_risk"])
        self._validate_kyb_discrepancy_risk(config["kyb_discrepancy_risk"])
        self._validate_thresholds(config["thresholds"])

        return config

    def _validate_entity_type_risk(self, section: Any) -> None:
        if not isinstance(section, dict) or "scores" not in section or "default_score" not in section:
            raise RiskRatingConfigurationError(
                "entity_type_risk: must be a mapping with 'scores' and 'default_score'"
            )
        if not isinstance(section["scores"], dict):
            raise RiskRatingConfigurationError("entity_type_risk.scores: must be a mapping")

    def _validate_country_risk(self, section: Any) -> None:
        if not isinstance(section, dict):
            raise RiskRatingConfigurationError("country_risk: must be a mapping")
        missing = _COUNTRY_RISK_REQUIRED_KEYS - set(section)
        if missing:
            raise RiskRatingConfigurationError(f"country_risk: missing key(s) {sorted(missing)}")
        if section["default_band"] not in section["band_scores"]:
            raise RiskRatingConfigurationError(
                f"country_risk.default_band {section['default_band']!r} is not a key in band_scores"
            )

    def _validate_sector_risk(self, section: Any) -> None:
        if not isinstance(section, dict):
            raise RiskRatingConfigurationError("sector_risk: must be a mapping")
        missing = _SECTOR_RISK_REQUIRED_KEYS - set(section)
        if missing:
            raise RiskRatingConfigurationError(f"sector_risk: missing key(s) {sorted(missing)}")

    def _validate_band_config(self, section: Any, *, where: str, max_key: str) -> None:
        if not isinstance(section, dict) or "bands" not in section:
            raise RiskRatingConfigurationError(f"{where}: must be a mapping with a 'bands' list")
        bands = section["bands"]
        if not isinstance(bands, list) or not bands:
            raise RiskRatingConfigurationError(f"{where}.bands: must be a non-empty list")
        for index, band in enumerate(bands):
            if not isinstance(band, dict) or max_key not in band or "score" not in band:
                raise RiskRatingConfigurationError(
                    f"{where}.bands[{index}]: must be a mapping with '{max_key}' and 'score'"
                )
        if bands[-1][max_key] is not None:
            raise RiskRatingConfigurationError(
                f"{where}.bands: the last band's '{max_key}' must be null (an unbounded catch-all)"
            )

    def _validate_pep_risk(self, section: Any) -> None:
        if not isinstance(section, dict):
            raise RiskRatingConfigurationError("pep_risk: must be a mapping")
        missing = _PEP_RISK_REQUIRED_KEYS - set(section)
        if missing:
            raise RiskRatingConfigurationError(f"pep_risk: missing key(s) {sorted(missing)}")

    def _validate_screening_risk(self, section: Any) -> None:
        if not isinstance(section, dict):
            raise RiskRatingConfigurationError("screening_risk: must be a mapping")
        missing = _SCREENING_RISK_REQUIRED_KEYS - set(section)
        if missing:
            raise RiskRatingConfigurationError(f"screening_risk: missing key(s) {sorted(missing)}")
        if not isinstance(section["scores"], dict):
            raise RiskRatingConfigurationError("screening_risk.scores: must be a mapping")

    def _validate_kyb_discrepancy_risk(self, section: Any) -> None:
        if not isinstance(section, dict):
            raise RiskRatingConfigurationError("kyb_discrepancy_risk: must be a mapping")
        missing = _KYB_DISCREPANCY_RISK_REQUIRED_KEYS - set(section)
        if missing:
            raise RiskRatingConfigurationError(f"kyb_discrepancy_risk: missing key(s) {sorted(missing)}")

    def _validate_thresholds(self, section: Any) -> None:
        if not isinstance(section, dict):
            raise RiskRatingConfigurationError("thresholds: must be a mapping")
        missing = _THRESHOLDS_REQUIRED_KEYS - set(section)
        if missing:
            raise RiskRatingConfigurationError(f"thresholds: missing key(s) {sorted(missing)}")
        low, medium, high = section["low_max"], section["medium_max"], section["high_max"]
        if not (low < medium < high):
            raise RiskRatingConfigurationError(
                f"thresholds: must satisfy low_max < medium_max < high_max, got {low}, {medium}, {high}"
            )

    # ── scoring helpers ──────────────────────────────────────────────────────

    def _score_band(self, value: float, bands: list[dict[str, Any]], max_key: str) -> int:
        for band in bands:
            limit = band.get(max_key)
            if limit is None or value <= limit:
                return int(band["score"])
        return int(bands[-1]["score"])  # unreachable given validation, kept defensive

    def _rating_for_score(self, score: int) -> OnboardingRiskRating:
        thresholds = self.config["thresholds"]
        if score <= thresholds["low_max"]:
            return OnboardingRiskRating.LOW
        if score <= thresholds["medium_max"]:
            return OnboardingRiskRating.MEDIUM
        if score <= thresholds["high_max"]:
            return OnboardingRiskRating.HIGH
        return OnboardingRiskRating.CRITICAL

    # ── public API ───────────────────────────────────────────────────────────

    def calculate(
        self,
        *,
        entity_type: str,
        registration_country: str,
        sector_code: str | None,
        declared_monthly_volume_usd: int | float | None,
        ubo_count: int,
        ubo_pep_statuses: Sequence[str] | None = None,
        screening_result: str | OnboardingScreeningResult | None,
        kyb_discrepancies: Sequence[str] | None = None,
    ) -> RiskRatingResult:
        """Compute the composite risk rating for one set of onboarding signals.

        Pure and deterministic: calling this twice with identical arguments
        returns two :class:`RiskRatingResult` instances with identical field
        values every time (see the determinism test).

        Args:
            entity_type: One of :class:`OnboardingEntityType`'s values.
            registration_country: ISO 3166-1 alpha-2 country code.
            sector_code: FATF sector classification, or ``None`` if not yet
                recorded (the ``onboarding_request.industry_code`` column is
                nullable).
            declared_monthly_volume_usd: Customer's declared volume, or
                ``None`` if not yet declared (treated as the lowest volume band).
            ubo_count: Number of identified UBOs.
            ubo_pep_statuses: The ``pep_status`` value of every UBO (e.g.
                ``["NOT_PEP", "PEP"]``). ``None`` or empty means no UBO data yet.
            screening_result: The onboarding's screening outcome (S5T1), or
                ``None`` if screening has not completed yet.
            kyb_discrepancies: Any KYB discrepancy descriptions (name/address
                mismatches etc.) recorded on the ``kyb_vendor_result`` for this
                onboarding.

        Returns:
            A :class:`RiskRatingResult` with the composite score, risk_rating,
            a human-readable factor breakdown, and the EDD determination.
        """
        factors: list[dict[str, Any]] = []
        score = 0

        # ── entity_type ──────────────────────────────────────────────────────
        etype = normalise_entity_type(entity_type)
        etype_section = self.config["entity_type_risk"]
        etype_score = int(etype_section["scores"].get(etype, etype_section["default_score"]))
        score += etype_score
        factors.append(
            {
                "factor": "entity_type",
                "value": etype,
                "score": etype_score,
                "detail": f"entity_type {etype!r} scores {etype_score}.",
            }
        )

        # ── registration_country ─────────────────────────────────────────────
        country = normalise_country(registration_country)
        country_section = self.config["country_risk"]
        if country in country_section["fatf_black_list"]:
            country_score = int(country_section["fatf_black_list_score"])
            country_detail = f"{country!r} is on the FATF black list (call for action)."
        elif country in country_section["fatf_grey_list"]:
            country_score = int(country_section["fatf_grey_list_score"])
            country_detail = f"{country!r} is on the FATF grey list (increased monitoring)."
        else:
            if country in country_section["low_risk_countries"]:
                band = "LOW"
            elif country in country_section["medium_risk_countries"]:
                band = "MEDIUM"
            elif country in country_section["high_risk_countries"]:
                band = "HIGH"
            else:
                band = country_section["default_band"]
            country_score = int(country_section["band_scores"][band])
            country_detail = f"{country!r} is scored {band} country risk ({country_score})."
        score += country_score
        factors.append(
            {"factor": "registration_country", "value": country, "score": country_score, "detail": country_detail}
        )

        # ── sector_code ──────────────────────────────────────────────────────
        sector = _normalise_sector(sector_code)
        sector_section = self.config["sector_risk"]
        is_dnfbp = sector in sector_section["dnfbp_sector_codes"]
        is_critical_sector = sector in sector_section["critical_sector_codes"]
        if is_critical_sector:
            sector_score = int(sector_section["critical_sector_score"])
            sector_detail = f"sector_code {sector!r} is a VASP/crypto sector (critical)."
        elif is_dnfbp:
            sector_score = int(sector_section["dnfbp_score"])
            sector_detail = f"sector_code {sector!r} is a DNFBP sector."
        else:
            sector_score = int(sector_section["default_score"])
            sector_detail = f"sector_code {sector or '(none)'!r} is not a designated high-risk sector."
        score += sector_score
        factors.append(
            {"factor": "sector_code", "value": sector or None, "score": sector_score, "detail": sector_detail}
        )

        # ── declared_monthly_volume_usd ──────────────────────────────────────
        volume = float(declared_monthly_volume_usd) if declared_monthly_volume_usd is not None else 0.0
        volume_bands = self.config["volume_risk"]["bands"]
        volume_score = self._score_band(volume, volume_bands, "max_usd")
        score += volume_score
        factors.append(
            {
                "factor": "declared_monthly_volume_usd",
                "value": declared_monthly_volume_usd,
                "score": volume_score,
                "detail": f"Declared monthly volume {declared_monthly_volume_usd!r} scores {volume_score}.",
            }
        )

        # ── ubo_count ────────────────────────────────────────────────────────
        ubo_bands = self.config["ubo_risk"]["bands"]
        ubo_count_score = self._score_band(float(ubo_count), ubo_bands, "max_count")
        score += ubo_count_score
        factors.append(
            {
                "factor": "ubo_count",
                "value": ubo_count,
                "score": ubo_count_score,
                "detail": f"{ubo_count} identified UBO(s) scores {ubo_count_score}.",
            }
        )

        # ── pep_status (any UBO) ─────────────────────────────────────────────
        pep_section = self.config["pep_risk"]
        normalised_pep_statuses = [_normalise_pep_status(p) for p in (ubo_pep_statuses or [])]
        any_pep = UboPepStatus.PEP.value in normalised_pep_statuses
        any_pep_associate = UboPepStatus.PEP_ASSOCIATE.value in normalised_pep_statuses
        if any_pep:
            pep_score = int(pep_section["pep_score"])
            pep_detail = "At least one UBO is a politically exposed person (PEP)."
        elif any_pep_associate:
            pep_score = int(pep_section["pep_associate_score"])
            pep_detail = "At least one UBO is a PEP associate."
        else:
            pep_score = int(pep_section["none_score"])
            pep_detail = "No UBO is a PEP or PEP associate."
        score += pep_score
        factors.append({"factor": "pep_status", "value": any_pep, "score": pep_score, "detail": pep_detail})

        # ── screening_result ─────────────────────────────────────────────────
        screening_value = screening_result.value if isinstance(screening_result, OnboardingScreeningResult) else screening_result
        screening_norm = _normalise_screening_result(screening_value)
        screening_section = self.config["screening_risk"]
        if screening_norm is None:
            screening_score = int(screening_section["default_score"])
            screening_detail = "Screening result not yet available; contributes no score."
        else:
            screening_score = int(
                screening_section["scores"].get(screening_norm, screening_section["default_score"])
            )
            screening_detail = f"Screening result {screening_norm!r} scores {screening_score}."
        score += screening_score
        factors.append(
            {
                "factor": "screening_result",
                "value": screening_norm,
                "score": screening_score,
                "detail": screening_detail,
            }
        )

        # ── kyb_discrepancies ────────────────────────────────────────────────
        discrepancy_section = self.config["kyb_discrepancy_risk"]
        discrepancy_count = len(kyb_discrepancies or [])
        discrepancy_score = min(
            discrepancy_count * int(discrepancy_section["score_per_discrepancy"]),
            int(discrepancy_section["max_score"]),
        )
        score += discrepancy_score
        factors.append(
            {
                "factor": "kyb_discrepancies",
                "value": discrepancy_count,
                "score": discrepancy_score,
                "detail": f"{discrepancy_count} KYB discrepancy(ies) scores {discrepancy_score}.",
            }
        )

        # ── composite rating + EDD determination ────────────────────────────
        risk_rating = self._rating_for_score(score)

        edd_reasons: list[str] = []
        if risk_rating in (OnboardingRiskRating.HIGH, OnboardingRiskRating.CRITICAL):
            edd_reasons.append(f"the composite risk_rating is {risk_rating.value}")
        if is_dnfbp:
            edd_reasons.append(f"sector_code {sector!r} is classified DNFBP")
        if any_pep:
            edd_reasons.append("at least one UBO is a politically exposed person (PEP)")

        edd_required = bool(edd_reasons)
        edd_reason = (
            "Enhanced due diligence required because " + "; ".join(edd_reasons) + "."
            if edd_reasons
            else None
        )

        return RiskRatingResult(
            score=score,
            risk_rating=risk_rating,
            factors=factors,
            edd_required=edd_required,
            edd_reason=edd_reason,
            config_version=str(self.config.get("version", "unknown")),
        )


__all__ = ["RiskRatingResult", "RiskRatingService"]
