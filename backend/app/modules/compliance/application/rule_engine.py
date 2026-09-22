from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.modules.compliance.domain.jurisdiction import ResolvingJurisdiction
from app.modules.compliance.domain.policies.rule_matching import (
    ComplianceFacts,
    MatchableRule,
    rule_matches,
)
from app.modules.compliance.domain.required_action import RequiredAction


@dataclass(frozen=True)
class FiredAction:
    """One obligation, the rule that imposed it, and why.

    The three travel together because a settlement can carry several
    obligations from several rules, and a regulator asking "why is this payment
    under manual review?" needs the rule and the reason for *that* obligation —
    not the list of everything that fired. Holding them as parallel sequences
    would leave the association to be re-derived by index, which is exactly the
    kind of coupling that goes wrong once one rule imposes two things or two
    rules impose one.
    """

    action: RequiredAction
    rule_id: str
    reason: str


@dataclass(frozen=True)
class ComplianceActionSet:
    """Everything the rule registry decided about one settlement.

    ``fired`` is the whole decision; every other member is derived from it, so
    there is one place a new action can appear and no accessor that has to be
    widened when the vocabulary grows.

    ``resolving_jurisdiction`` is the authority whose sector classification fed
    the decision, as the type/value pair S0T2 returns. It is carried here rather
    than left to the caller to re-derive because the record of *which regime*
    deemed a sector high-risk is part of the decision, not context around it —
    the same sector carries different classifications in different
    jurisdictions. ``None`` means no classification was found, which is a
    distinct fact from a sector rated ``standard`` by someone.
    """

    fired: tuple[FiredAction, ...] = ()
    resolving_jurisdiction: ResolvingJurisdiction | None = None

    # ── The decision, as the ticket names it ──────────────────────────────────

    @property
    def required_actions(self) -> tuple[RequiredAction, ...]:
        """Every distinct action that fired, in the order the rules fired.

        Distinct: two rules demanding manual review impose it once. Ordered by
        first appearance rather than sorted, so the sequence follows the rules
        that produced it.
        """
        seen: dict[RequiredAction, None] = {}
        for entry in self.fired:
            seen.setdefault(entry.action, None)
        return tuple(seen)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Every distinct rule that fired, in order."""
        seen: dict[str, None] = {}
        for entry in self.fired:
            seen.setdefault(entry.rule_id, None)
        return tuple(seen)

    @property
    def reasons(self) -> tuple[str, ...]:
        """The plain-language reason behind each fired obligation, in order."""
        return tuple(entry.reason for entry in self.fired)

    # ── Asking about one action ───────────────────────────────────────────────

    def requires(self, action: RequiredAction) -> bool:
        return any(entry.action is action for entry in self.fired)

    def rules_for(self, action: RequiredAction) -> tuple[str, ...]:
        return tuple(entry.rule_id for entry in self.fired if entry.action is action)

    def reasons_for(self, action: RequiredAction) -> tuple[str, ...]:
        return tuple(entry.reason for entry in self.fired if entry.action is action)

    # ── Enhanced due diligence ────────────────────────────────────────────────
    #
    # EDD gets named accessors where the other actions do not, because the
    # settlement record has a column for it and S1T2 has to fill that column.
    # They are derived, so they assert nothing the rest of the set does not
    # already say.

    @property
    def edd_required(self) -> bool:
        return self.requires(RequiredAction.EDD_REQUIRED)

    @property
    def edd_trigger_rules(self) -> tuple[str, ...]:
        """Every rule that required due diligence, in order.

        The ticket says ``edd_trigger_rule`` is set from "the rule_id(s) that
        produced the edd_required action" — plural. This is that list.
        """
        return self.rules_for(RequiredAction.EDD_REQUIRED)

    @property
    def edd_trigger_rule(self) -> str | None:
        """The first rule that required due diligence, or None.

        ``settlement.edd_trigger_rule`` is a single ``String(255)`` today, so a
        settlement can name one rule. Which one must not depend on the order the
        registry was read in, and does not: the evaluator orders firing rules
        before building the set. Whether that column should hold all of
        ``edd_trigger_rules`` is S1T2's decision to make and S1T2's schema to
        change — see docs/S0T3-implementation.md.
        """
        rules = self.edd_trigger_rules
        return rules[0] if rules else None


NO_ACTIONS = ComplianceActionSet()


def evaluate_compliance_rules(
    facts: ComplianceFacts,
    rules: Iterable[MatchableRule],
    converted_amounts: Mapping[str, int] | None = None,
    *,
    resolving_jurisdiction: ResolvingJurisdiction | None = None,
) -> ComplianceActionSet:
    """Every obligation the given rules impose on the given facts.

    ``converted_amounts`` is the settlement's value in each currency the caller
    could convert into, and is needed only for a rule whose threshold is set in
    a currency other than the settlement's. Obtaining a rate is I/O and belongs
    to the caller; this stays a function of its arguments so that two runs over
    the same settlement cannot disagree.

    ``resolving_jurisdiction`` is likewise resolved by the caller — establishing
    it is a registry lookup — and is carried into the result unchanged. It does
    not participate in matching: which regime classified the sector decides what
    the tier and label *are*, and the rules match on those.
    """
    firing = sorted(
        (rule for rule in rules if rule_matches(rule, facts, converted_amounts)),
        key=lambda rule: (rule.priority, rule.rule_id),
    )

    return ComplianceActionSet(
        fired=tuple(
            FiredAction(action=rule.required_action, rule_id=rule.rule_id, reason=rule.reason)
            for rule in firing
        ),
        resolving_jurisdiction=resolving_jurisdiction,
    )
