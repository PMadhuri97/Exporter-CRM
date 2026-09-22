from __future__ import annotations

from collections.abc import Sequence

from app.modules.compliance.domain.entities.compliance import ScreeningStatus, ScreeningType
from app.modules.customers import RiskRating
from app.shared.value_objects import to_decimal

_PROVIDER_MAP: dict[ScreeningType, str] = {
    ScreeningType.SANCTIONS_OFAC: "MOCK_OFAC_v1",
    ScreeningType.SANCTIONS_UN: "MOCK_UN_v1",
    ScreeningType.SANCTIONS_EU: "MOCK_EU_v1",
    ScreeningType.SANCTIONS_RBI: "MOCK_RBI_v1",
    ScreeningType.AML_RISK: "ANER_AML_ENGINE_v1",
    ScreeningType.DNFBP: "ANER_DNFBP_v1",
}

def score_aml_risk(
    risk_rating: RiskRating,
    amount_minor: int,
    currency: str,
    *,
    registry_reasons: Sequence[str] = (),
    registry_rule_ids: Sequence[str] = (),
) -> tuple[ScreeningStatus, dict]:
    amount_str = str(to_decimal(amount_minor, currency))

    reasons: list[str] = []
    if risk_rating in (RiskRating.HIGH, RiskRating.ENHANCED):
        reasons.append(f"Customer risk rating is {risk_rating.value}")
    reasons.extend(registry_reasons)

    manual_review = bool(reasons)
    status = ScreeningStatus.MANUAL_REVIEW if manual_review else ScreeningStatus.PASS
    return status, {
        "provider": _PROVIDER_MAP[ScreeningType.AML_RISK],
        "risk_rating": risk_rating.value,
        "amount": amount_str,
        "manual_review": manual_review,
        "reasons": reasons,
        "rule_ids": list(registry_rule_ids),
    }
