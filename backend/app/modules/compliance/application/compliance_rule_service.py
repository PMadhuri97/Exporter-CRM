"""Resolve the obligations the rule registry imposes on one settlement.

The registry stores what the platform's compliance position is; this module
reads it and asks the evaluator what that position means for one settlement on
one date.

It sits apart from ``rule_engine`` on purpose. The evaluation is pure and is
tested to stay that way — its import closure is asserted in
``tests/unit/test_compliance_rule_evaluation.py``, because a decision is
reproducible only while it is reached from the facts and rules it was handed.
Reading the registry and fetching a rate are exactly the impurities that guard
exists to keep out, so they live here and the evaluator is handed rules and
already-converted amounts.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.modules.compliance.application.rule_engine import (
    ComplianceActionSet,
    evaluate_compliance_rules,
)
from app.modules.compliance.application.threshold_conversion import convert_minor_units
from app.modules.compliance.domain.entities.compliance_rule import (
    ComplianceRule as ComplianceRuleRow,
)
from app.modules.compliance.domain.jurisdiction import ResolvingJurisdiction
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.ports import (
    ComplianceAuditSink,
    ComplianceRuleRepository,
    IndicativeRateProvider,
)
from app.modules.compliance.domain.required_action import RequiredAction
from app.shared.value_objects import CURRENCY_REGISTRY, CurrencyRegistry

logger = structlog.get_logger(__name__)

_STORED_RULE_PRIORITY = 0


@dataclass(frozen=True)
class _StoredRule:
    rule_id: str
    priority: int
    sector_risk_tier: str | None
    classification_label: str | None
    purpose_code: str | None
    corridor_id: str | None
    amount_threshold_minor: int | None
    threshold_asset_code: str | None
    required_action: RequiredAction
    reason: str
    effective_from: date
    effective_to: date | None


def _as_rule(row: ComplianceRuleRow) -> _StoredRule:
    return _StoredRule(
        rule_id=row.rule_id,
        priority=_STORED_RULE_PRIORITY,
        # Carried as the enum's value rather than the enum: the facts hold a
        # plain string and the comparison is exact.
        sector_risk_tier=(
            row.sector_risk_tier_match.value if row.sector_risk_tier_match is not None else None
        ),
        classification_label=row.sector_classification_label_match,
        purpose_code=row.purpose_code_category_match,
        corridor_id=row.corridor_match,
        amount_threshold_minor=row.amount_threshold,
        threshold_asset_code=row.amount_threshold_currency,
        # Carried straight through. Every action the column can hold reaches the
        # evaluator without this adapter naming any of them, so a new member of
        # the enum needs no change here.
        required_action=row.required_action,
        reason=row.action_reason,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
    )


def _threshold_currencies_needing_a_rate(
    facts: ComplianceFacts, rules: Iterable[_StoredRule]
) -> list[str]:
    """The currencies a rate is actually required for.

    A rule with no threshold is not constrained by amount, and a threshold in
    the settlement's own currency is already comparable — neither needs a rate,
    and neither is listed here. In the Walk phase every rule and every
    settlement is denominated in USD, so this returns nothing and no FX call is
    made at all.

    Sorted, and one entry per currency however many rules share it: the number
    of rate lookups an evaluation makes should follow from the registry, not
    from the order rows came back in.
    """
    return sorted(
        {
            rule.threshold_asset_code
            for rule in rules
            if rule.amount_threshold_minor is not None
            and rule.threshold_asset_code is not None
            and rule.threshold_asset_code != facts.send_asset_code
        }
    )


def _rules_priced_in(asset_code: str, rules: Iterable[_StoredRule]) -> tuple[str, ...]:
    """The rules whose threshold is denominated in ``asset_code``.

    These are the rules a missing rate leaves unchecked, and naming them is what
    lets a reviewer see what the fail-safe actually waved through rather than
    only that some rate was unavailable.
    """
    return tuple(
        sorted(
            rule.rule_id
            for rule in rules
            if rule.amount_threshold_minor is not None and rule.threshold_asset_code == asset_code
        )
    )


#: Failures that mean the audit trail is unreachable rather than misused. These
#: are operational and expected under load or partial outage; the compliance
#: decision continues without them and the warning is the record.
_EXPECTED_SINK_FAILURES = (SQLAlchemyError, ConnectionError, TimeoutError, OSError)


async def _report_rate_unavailable(
    audit_sink: ComplianceAuditSink | None,
    from_asset_code: str,
    to_asset_code: str,
    reason: str,
    error_type: str | None = None,
    rule_ids: tuple[str, ...] = (),
) -> None:
    """Record that a threshold was let through unchecked.

    Two destinations because they answer to different readers. The log line is
    for whoever is debugging a rate feed; the audit event is for the compliance
    team, who have to be able to find every settlement that was escalated
    without its threshold actually being evaluated.

    A sink that fails must not take the evaluation with it: losing the record is
    bad, and failing the decision that the record explains is worse. But the two
    kinds of failure are not logged alike — an unreachable database is
    operational and expected, while a TypeError in the sink is a defect that
    would otherwise hide behind the same warning forever.
    """
    logger.warning(
        "compliance_threshold_rate_unavailable",
        from_asset_code=from_asset_code,
        to_asset_code=to_asset_code,
        reason=reason,
        error_type=error_type,
        rule_ids=list(rule_ids),
    )
    if audit_sink is None:
        return
    try:
        await audit_sink.record_threshold_rate_unavailable(
            from_asset_code=from_asset_code,
            to_asset_code=to_asset_code,
            reason=reason,
            error_type=error_type,
            rule_ids=rule_ids,
        )
    except _EXPECTED_SINK_FAILURES as exc:
        logger.warning(
            "compliance_threshold_rate_unavailable_audit_failed",
            from_asset_code=from_asset_code,
            to_asset_code=to_asset_code,
            rule_ids=list(rule_ids),
            error=str(exc),
            error_type=type(exc).__name__,
        )
    except Exception as exc:  # noqa: BLE001 — the decision must survive; see below
        # Not swallowed: logged at error with a full traceback and its own event
        # name, so a defect in the sink is findable rather than indistinguishable
        # from a database being briefly unreachable. Still not re-raised — the
        # compliance decision is already correct and losing it would turn a
        # recorded fail-safe into no answer at all.
        logger.error(
            "compliance_threshold_rate_unavailable_audit_error",
            from_asset_code=from_asset_code,
            to_asset_code=to_asset_code,
            rule_ids=list(rule_ids),
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )


async def _value_in_threshold_currencies(
    facts: ComplianceFacts,
    rules: Iterable[_StoredRule],
    rate_provider: IndicativeRateProvider | None,
    registry: CurrencyRegistry,
    audit_sink: ComplianceAuditSink | None = None,
) -> dict[str, int]:
    """The settlement's value in each currency a threshold is set in.

    A currency is absent from the result when its rate could not be obtained,
    which the evaluator reads as the threshold being met. That is the safe
    direction: a failed lookup escalates a payment to review rather than quietly
    excusing it from one, and the warning below is what makes the escalation
    explicable afterwards.
    """
    # Materialised because the rules are now walked more than once: to decide
    # which currencies need a rate, and again to name the rules each failing
    # currency left unchecked. A one-shot iterable would come back empty the
    # second time.
    rules = list(rules)

    wanted = _threshold_currencies_needing_a_rate(facts, rules)
    if not wanted:
        return {}

    converted: dict[str, int] = {}
    for asset_code in wanted:
        if rate_provider is None:
            await _report_rate_unavailable(
                audit_sink,
                facts.send_asset_code,
                asset_code,
                "no_indicative_rate_provider_supplied",
                rule_ids=_rules_priced_in(asset_code, rules),
            )
            continue
        try:
            rate = await rate_provider.get_indicative_rate(facts.send_asset_code, asset_code)
            converted[asset_code] = convert_minor_units(
                facts.send_amount_minor,
                facts.send_asset_code,
                asset_code,
                rate,
                registry=registry,
            )
        except Exception as exc:
            # Deliberately broad. Whatever a provider raises — an unsupported
            # pair, a timeout, a currency the registry does not hold — the
            # answer is the same, and an evaluation must not fail because a
            # rate could not be fetched.
            await _report_rate_unavailable(
                audit_sink,
                facts.send_asset_code,
                asset_code,
                str(exc),
                error_type=type(exc).__name__,
                rule_ids=_rules_priced_in(asset_code, rules),
            )
    return converted


async def evaluate_settlement_compliance(
    facts: ComplianceFacts,
    repository: ComplianceRuleRepository,
    rate_provider: IndicativeRateProvider | None = None,
    *,
    registry: CurrencyRegistry = CURRENCY_REGISTRY,
    resolving_jurisdiction: ResolvingJurisdiction | None = None,
    audit_sink: ComplianceAuditSink | None = None,
) -> ComplianceActionSet:
    """Return the obligations the registry imposes on ``facts``.

    Reads the registry, values the settlement in every currency a threshold is
    set in, and evaluates. Given the same rules and the same rates the answer is
    the same every time.

    ``rate_provider`` is injected and typed only as the port this module owns,
    so nothing here depends on how a rate is obtained. Passing none is not an
    error: it is indistinguishable from a provider that cannot answer, and is
    handled the same way.

    The decision itself writes nothing. The one exception is the fail-safe: when
    a rate cannot be obtained, ``audit_sink`` records that a threshold went
    unchecked. That is not a record of the decision but of a control that could
    not be applied, and it is written into the caller's transaction without
    committing it — the session still belongs to the caller.

    ``resolving_jurisdiction`` is established by the caller, which owns the
    classification lookup, and is carried into the result unchanged.

    Effectivity is judged on ``facts.as_of_date``, never today. Re-running an
    evaluation must not change what a payment was obliged to do when the money
    moved.
    """
    rows = await repository.list_rules()
    rules = [_as_rule(row) for row in rows]
    converted = await _value_in_threshold_currencies(
        facts, rules, rate_provider, registry, audit_sink
    )
    return evaluate_compliance_rules(
        facts, rules, converted, resolving_jurisdiction=resolving_jurisdiction
    )
