from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.modules.compliance.domain.policies.effectivity import is_effective_at
from app.modules.compliance.domain.required_action import RequiredAction


class MatchableRule(Protocol):
    @property
    def rule_id(self) -> str: ...

    @property
    def priority(self) -> int: ...

    @property
    def sector_risk_tier(self) -> str | None: ...

    @property
    def classification_label(self) -> str | None: ...

    @property
    def purpose_code(self) -> str | None: ...

    @property
    def corridor_id(self) -> str | None: ...

    @property
    def amount_threshold_minor(self) -> int | None: ...

    @property
    def threshold_asset_code(self) -> str | None: ...

    @property
    def required_action(self) -> RequiredAction: ...

    @property
    def reason(self) -> str: ...

    @property
    def effective_from(self) -> date: ...

    @property
    def effective_to(self) -> date | None: ...


@dataclass(frozen=True)
class ComplianceFacts:
    send_amount_minor: int
    send_asset_code: str
    as_of_date: date
    sector_risk_tier: str | None = None
    classification_label: str | None = None
    purpose_code: str | None = None
    corridor_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.as_of_date, date) or isinstance(self.as_of_date, datetime):
            raise ValueError(f"as_of_date must be a date, got {self.as_of_date!r}")
        if not self.send_asset_code:
            raise ValueError("send_asset_code must be a non-empty string")
        # bool is a subclass of int, and True would silently compare as 1 against
        # a threshold rather than being rejected as the wrong kind of value.
        if not isinstance(self.send_amount_minor, int) or isinstance(self.send_amount_minor, bool):
            raise ValueError(
                "send_amount_minor must be an integer number of minor units, "
                f"got {self.send_amount_minor!r}"
            )
        if self.send_amount_minor < 0:
            raise ValueError(
                f"send_amount_minor must not be negative, got {self.send_amount_minor}"
            )


def matches_condition(condition: str | None, fact: str | None) -> bool:
    if condition is None:
        return True
    return condition == fact


def amount_against_threshold(
    rule: MatchableRule,
    facts: ComplianceFacts,
    converted_amounts: Mapping[str, int] | None,
) -> int | None:
    if rule.amount_threshold_minor is None:
        return facts.send_amount_minor
    if rule.threshold_asset_code == facts.send_asset_code:
        return facts.send_amount_minor
    if converted_amounts is None or rule.threshold_asset_code is None:
        return None
    return converted_amounts.get(rule.threshold_asset_code)


def matches_threshold(threshold_minor: int | None, amount_minor: int | None) -> bool:
    if threshold_minor is None:
        return True
    if amount_minor is None:
        return True
    return amount_minor >= threshold_minor


def rule_matches(
    rule: MatchableRule,
    facts: ComplianceFacts,
    converted_amounts: Mapping[str, int] | None = None,
) -> bool:
    return (
        is_effective_at(rule.effective_from, rule.effective_to, facts.as_of_date)
        and matches_condition(rule.sector_risk_tier, facts.sector_risk_tier)
        and matches_condition(rule.classification_label, facts.classification_label)
        and matches_condition(rule.purpose_code, facts.purpose_code)
        and matches_condition(rule.corridor_id, facts.corridor_id)
        and matches_threshold(
            rule.amount_threshold_minor,
            amount_against_threshold(rule, facts, converted_amounts),
        )
    )
