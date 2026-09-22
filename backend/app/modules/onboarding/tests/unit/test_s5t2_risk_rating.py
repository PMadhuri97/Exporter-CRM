"""Unit tests for S5T2: Risk Rating Calculation.

Pure calculator tests — no database, no I/O — mirroring the style of
test_s1t2_document_requirements.py for the sibling document-requirements
policy. Acceptance criteria covered (ANER-4.1-S5T2):

  AC1  A US corporation, DNFBP sector, medium country risk, no PEP UBOs
       -> high risk_rating, edd_required true.
  AC2  A standard low-volume non-DNFBP company -> low risk_rating.
  AC3  A PEP UBO -> high or critical risk_rating, PEP factor named in
       risk_rating_factors.
  AC4  Thresholds are read from configuration, not hardcoded.
  AC5  The calculation is deterministic: identical inputs always produce
       identical outputs.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.modules.onboarding import RiskRatingService as FacadeRiskRatingService
from app.modules.onboarding.domain.entities.orchestration_enums import OnboardingRiskRating
from app.modules.onboarding.domain.policies.risk_rating_service import RiskRatingService
from app.modules.onboarding.exceptions import RiskRatingConfigurationError
from app.modules.onboarding.infrastructure.risk_rating_config_loader import (
    load_risk_rating_config,
    load_risk_rating_service,
)


def _valid_config() -> dict:
    """A minimal, structurally valid configuration for negative-case mutation."""
    return {
        "version": "1.0",
        "entity_type_risk": {
            "scores": {"CORPORATION": 0, "PARTNERSHIP": 10, "SOLE_TRADER": 15, "TRUST": 15, "FUND": 5},
            "default_score": 10,
        },
        "country_risk": {
            "low_risk_countries": ["GB"],
            "medium_risk_countries": ["US"],
            "high_risk_countries": ["NG"],
            "fatf_grey_list": ["ZA"],
            "fatf_black_list": ["KP"],
            "default_band": "MEDIUM",
            "band_scores": {"LOW": 5, "MEDIUM": 15, "HIGH": 30},
            "fatf_grey_list_score": 25,
            "fatf_black_list_score": 45,
        },
        "sector_risk": {
            "dnfbp_sector_codes": ["DNFBP"],
            "dnfbp_score": 30,
            "critical_sector_codes": ["VASP"],
            "critical_sector_score": 100,
            "default_score": 0,
        },
        "volume_risk": {
            "bands": [
                {"max_usd": 50000, "score": 0},
                {"max_usd": 250000, "score": 10},
                {"max_usd": 500000, "score": 20},
                {"max_usd": None, "score": 35},
            ]
        },
        "ubo_risk": {
            "bands": [
                {"max_count": 2, "score": 0},
                {"max_count": 5, "score": 10},
                {"max_count": None, "score": 30},
            ]
        },
        "pep_risk": {"pep_score": 40, "pep_associate_score": 20, "none_score": 0},
        "screening_risk": {
            "scores": {"CLEAR": 0, "REVIEW_REQUIRED": 25, "HARD_BLOCK": 100},
            "default_score": 0,
        },
        "kyb_discrepancy_risk": {"score_per_discrepancy": 8, "max_score": 40},
        "thresholds": {"low_max": 24, "medium_max": 49, "high_max": 79},
    }


def _service(config: dict | None = None) -> RiskRatingService:
    return RiskRatingService(config or _valid_config())


# ── AC1 — DNFBP US corporation, medium country risk, no PEP -> HIGH + EDD ────


def test_dnfbp_us_corporation_medium_country_risk_no_pep_is_high_and_edd_required():
    service = load_risk_rating_service()
    result = service.calculate(
        entity_type="CORPORATION",
        registration_country="US",
        sector_code="DNFBP",
        declared_monthly_volume_usd=300_000,
        ubo_count=2,
        ubo_pep_statuses=["NOT_PEP", "NOT_PEP"],
        screening_result="CLEAR",
        kyb_discrepancies=None,
    )

    assert result.risk_rating == OnboardingRiskRating.HIGH
    assert result.edd_required is True
    assert result.edd_reason is not None
    assert "DNFBP" in result.edd_reason

    sector_factor = next(f for f in result.factors if f["factor"] == "sector_code")
    assert sector_factor["value"] == "DNFBP"
    assert sector_factor["score"] > 0


# ── AC2 — standard low-volume non-DNFBP company -> LOW ───────────────────────


def test_standard_low_volume_non_dnfbp_company_is_low_risk():
    service = load_risk_rating_service()
    result = service.calculate(
        entity_type="CORPORATION",
        registration_country="US",
        sector_code="PROFESSIONAL_SERVICES",
        declared_monthly_volume_usd=20_000,
        ubo_count=1,
        ubo_pep_statuses=["NOT_PEP"],
        screening_result="CLEAR",
        kyb_discrepancies=None,
    )

    assert result.risk_rating == OnboardingRiskRating.LOW
    assert result.edd_required is False
    assert result.edd_reason is None


# ── AC3 — PEP UBO -> HIGH or CRITICAL, PEP factor named ──────────────────────


def test_pep_ubo_is_high_or_critical_with_pep_factor_named():
    service = load_risk_rating_service()
    result = service.calculate(
        entity_type="CORPORATION",
        registration_country="US",
        sector_code="PROFESSIONAL_SERVICES",
        declared_monthly_volume_usd=20_000,
        ubo_count=2,
        ubo_pep_statuses=["NOT_PEP", "PEP"],
        screening_result="CLEAR",
        kyb_discrepancies=None,
    )

    assert result.risk_rating in (OnboardingRiskRating.HIGH, OnboardingRiskRating.CRITICAL)
    assert result.edd_required is True
    assert result.edd_reason is not None
    assert "politically exposed" in result.edd_reason.lower()

    pep_factor = next(f for f in result.factors if f["factor"] == "pep_status")
    assert pep_factor["value"] is True
    assert pep_factor["score"] > 0


def test_pep_associate_scores_less_than_full_pep():
    service = _service()
    associate = service.calculate(
        entity_type="CORPORATION",
        registration_country="GB",
        sector_code=None,
        declared_monthly_volume_usd=1_000,
        ubo_count=1,
        ubo_pep_statuses=["PEP_ASSOCIATE"],
        screening_result="CLEAR",
    )
    full_pep = service.calculate(
        entity_type="CORPORATION",
        registration_country="GB",
        sector_code=None,
        declared_monthly_volume_usd=1_000,
        ubo_count=1,
        ubo_pep_statuses=["PEP"],
        screening_result="CLEAR",
    )
    assert associate.score < full_pep.score


# ── AC4 — thresholds read from configuration, not hardcoded ─────────────────


def test_thresholds_are_read_from_configuration_not_hardcoded():
    config = _valid_config()
    inputs = {
        "entity_type": "CORPORATION",
        "registration_country": "US",  # medium band = 15
        "sector_code": None,  # 0
        "declared_monthly_volume_usd": 20_000,  # 0
        "ubo_count": 1,  # 0
        "ubo_pep_statuses": ["NOT_PEP"],  # 0
        "screening_result": "CLEAR",  # 0
        "kyb_discrepancies": None,  # 0
    }
    # Composite score is 15 (country risk only). With the default thresholds
    # (low_max=24) that is LOW.
    baseline = RiskRatingService(deepcopy(config)).calculate(**inputs)
    assert baseline.score == 15
    assert baseline.risk_rating == OnboardingRiskRating.LOW

    # Lower low_max below the score purely via config -- no code change -- and
    # the same inputs must now rate MEDIUM instead of LOW.
    tightened = deepcopy(config)
    tightened["thresholds"]["low_max"] = 5
    result = RiskRatingService(tightened).calculate(**inputs)
    assert result.score == 15
    assert result.risk_rating == OnboardingRiskRating.MEDIUM


def test_adding_a_new_country_via_config_without_code_changes():
    config = _valid_config()
    config["country_risk"]["fatf_black_list"].append("XX")
    result = RiskRatingService(config).calculate(
        entity_type="CORPORATION",
        registration_country="xx",  # lower-case on purpose: normalisation
        sector_code=None,
        declared_monthly_volume_usd=0,
        ubo_count=0,
        ubo_pep_statuses=None,
        screening_result=None,
    )
    country_factor = next(f for f in result.factors if f["factor"] == "registration_country")
    assert country_factor["value"] == "XX"
    assert country_factor["score"] == config["country_risk"]["fatf_black_list_score"]


# ── AC5 — determinism ─────────────────────────────────────────────────────


def test_calculation_is_deterministic():
    service = load_risk_rating_service()
    kwargs = {
        "entity_type": "PARTNERSHIP",
        "registration_country": "IN",
        "sector_code": "DNFBP",
        "declared_monthly_volume_usd": 750_000,
        "ubo_count": 4,
        "ubo_pep_statuses": ["NOT_PEP", "PEP_ASSOCIATE", "NOT_PEP", "NOT_PEP"],
        "screening_result": "REVIEW_REQUIRED",
        "kyb_discrepancies": ["BusinessName MISMATCH in MCA", "Address MISMATCH in GSTIN"],
    }

    first = service.calculate(**kwargs)
    second = service.calculate(**kwargs)

    assert first.score == second.score
    assert first.risk_rating == second.risk_rating
    assert first.factors == second.factors
    assert first.edd_required == second.edd_required
    assert first.edd_reason == second.edd_reason
    assert first.to_risk_rating_factors_json() == second.to_risk_rating_factors_json()


# ── VASP / crypto sector scores critical on its own ──────────────────────────


def test_vasp_sector_alone_produces_critical_rating():
    service = _service()
    result = service.calculate(
        entity_type="CORPORATION",
        registration_country="GB",  # lowest-risk band
        sector_code="VASP",
        declared_monthly_volume_usd=0,
        ubo_count=0,
        ubo_pep_statuses=None,
        screening_result="CLEAR",
    )
    assert result.risk_rating == OnboardingRiskRating.CRITICAL
    assert result.edd_required is True


# ── kyb_discrepancies contribute score, capped ───────────────────────────────


def test_kyb_discrepancies_increase_score_and_are_capped():
    service = _service()
    base = service.calculate(
        entity_type="CORPORATION",
        registration_country="GB",
        sector_code=None,
        declared_monthly_volume_usd=0,
        ubo_count=0,
        ubo_pep_statuses=None,
        screening_result="CLEAR",
        kyb_discrepancies=None,
    )
    with_discrepancies = service.calculate(
        entity_type="CORPORATION",
        registration_country="GB",
        sector_code=None,
        declared_monthly_volume_usd=0,
        ubo_count=0,
        ubo_pep_statuses=None,
        screening_result="CLEAR",
        kyb_discrepancies=["a", "b", "c"],
    )
    assert with_discrepancies.score == base.score + 24  # 3 * 8

    many_discrepancies = service.calculate(
        entity_type="CORPORATION",
        registration_country="GB",
        sector_code=None,
        declared_monthly_volume_usd=0,
        ubo_count=0,
        ubo_pep_statuses=None,
        screening_result="CLEAR",
        kyb_discrepancies=["a"] * 20,
    )
    assert many_discrepancies.score == base.score + 40  # capped at max_score


# ── default GitOps config sanity ─────────────────────────────────────────────


def test_default_config_file_exists_and_parseable():
    service = load_risk_rating_service()
    assert service.config is not None
    assert service.config.get("version") == "1.0"


def test_service_exported_from_module_facade():
    assert FacadeRiskRatingService is RiskRatingService


# ── malformed configuration is rejected explicitly ───────────────────────────


def test_missing_top_level_key_raises():
    config = _valid_config()
    del config["thresholds"]
    with pytest.raises(RiskRatingConfigurationError, match="missing top-level key"):
        RiskRatingService(config)


def test_thresholds_out_of_order_raises():
    config = _valid_config()
    config["thresholds"] = {"low_max": 50, "medium_max": 10, "high_max": 79}
    with pytest.raises(RiskRatingConfigurationError, match="low_max < medium_max < high_max"):
        RiskRatingService(config)


def test_band_without_null_terminal_raises():
    config = _valid_config()
    config["volume_risk"]["bands"][-1]["max_usd"] = 999_999
    with pytest.raises(RiskRatingConfigurationError, match="unbounded catch-all"):
        RiskRatingService(config)


def test_country_risk_missing_key_raises():
    config = _valid_config()
    del config["country_risk"]["fatf_black_list"]
    with pytest.raises(RiskRatingConfigurationError, match="missing key"):
        RiskRatingService(config)


def test_default_band_not_in_band_scores_raises():
    config = _valid_config()
    config["country_risk"]["default_band"] = "NOT_A_BAND"
    with pytest.raises(RiskRatingConfigurationError, match="default_band"):
        RiskRatingService(config)


def test_non_mapping_config_raises():
    with pytest.raises(RiskRatingConfigurationError, match="expected a mapping"):
        RiskRatingService(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_missing_config_file_raises_structured_exception(tmp_path):
    non_existent = tmp_path / "does_not_exist.yaml"
    with pytest.raises(RiskRatingConfigurationError):
        load_risk_rating_config(config_path=non_existent)


def test_non_mapping_config_file_raises_structured_exception(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RiskRatingConfigurationError):
        load_risk_rating_config(config_path=bad)
