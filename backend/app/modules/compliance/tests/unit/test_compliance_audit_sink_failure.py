from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import OperationalError

from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.required_action import RequiredAction
from app.modules.compliance.tests.fixtures.rate_providers import UnavailableRateProvider

AS_OF = date(2026, 8, 12)
INR_THRESHOLD = 415_000_000


class ListRepository:
    def __init__(self, rules: list[ComplianceRule]) -> None:
        self._rules = rules

    async def list_rules(self) -> list[ComplianceRule]:
        return list(self._rules)


class ExplodingAuditSink:
    """A sink that always fails, recording that it was asked."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[dict] = []

    async def record_threshold_rate_unavailable(self, **kwargs) -> None:
        self.calls.append(kwargs)
        raise self.error


INR_RULE = ComplianceRule(
    rule_id="INR_LARGE_VALUE",
    description="Large value in INR",
    amount_threshold=INR_THRESHOLD,
    amount_threshold_currency="INR",
    required_action=RequiredAction.MANUAL_REVIEW,
    action_reason="Settlement meets the INR large-value threshold",
    effective_from=date(2024, 1, 1),
)


def _facts(amount_minor: int = 1) -> ComplianceFacts:
    return ComplianceFacts(
        send_amount_minor=amount_minor, send_asset_code="USD", as_of_date=AS_OF
    )


#: One from each branch of the sink's error handling: an operational failure the
#: code expects, and a defect it does not.
SINK_FAILURES = [
    pytest.param(
        OperationalError("INSERT", {}, Exception("connection reset")),
        id="database-unreachable",
    ),
    pytest.param(ConnectionError("audit service unreachable"), id="connection-error"),
    pytest.param(TimeoutError("audit write timed out"), id="timeout"),
    pytest.param(TypeError("payload is not serialisable"), id="programming-error"),
    pytest.param(RuntimeError("something nobody anticipated"), id="unanticipated"),
]


@pytest.mark.parametrize("failure", SINK_FAILURES)
async def test_an_audit_sink_failure_does_not_raise(failure):
    """Whatever the sink does, the caller gets a decision rather than an
    exception — including for a programming error, which is logged loudly but
    must not propagate."""
    result = await evaluate_settlement_compliance(
        _facts(),
        ListRepository([INR_RULE]),
        UnavailableRateProvider(),
        audit_sink=ExplodingAuditSink(failure),
    )

    assert result is not None


@pytest.mark.parametrize("failure", SINK_FAILURES)
async def test_the_fail_safe_still_fires_when_the_audit_write_fails(failure):
    """The whole point. One cent cannot really breach an INR 4.15m threshold, but
    with no rate the platform cannot know that — and a failed audit write must
    not quietly turn that escalation back into a clean settlement."""
    result = await evaluate_settlement_compliance(
        _facts(),
        ListRepository([INR_RULE]),
        UnavailableRateProvider(),
        audit_sink=ExplodingAuditSink(failure),
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == ("INR_LARGE_VALUE",)


async def test_the_sink_was_actually_asked_before_it_failed():
    """Guards against the test passing because the sink was never called."""
    sink = ExplodingAuditSink(ConnectionError("down"))

    await evaluate_settlement_compliance(
        _facts(), ListRepository([INR_RULE]), UnavailableRateProvider(), audit_sink=sink
    )

    assert len(sink.calls) == 1
    assert sink.calls[0]["from_asset_code"] == "USD"
    assert sink.calls[0]["to_asset_code"] == "INR"
    assert sink.calls[0]["rule_ids"] == ("INR_LARGE_VALUE",)


async def test_a_failing_sink_does_not_change_the_decision():
    """Byte-for-byte the same answer as a healthy sink would have produced. The
    audit trail explains a decision; it never participates in one."""
    healthy = await evaluate_settlement_compliance(
        _facts(), ListRepository([INR_RULE]), UnavailableRateProvider()
    )
    broken = await evaluate_settlement_compliance(
        _facts(),
        ListRepository([INR_RULE]),
        UnavailableRateProvider(),
        audit_sink=ExplodingAuditSink(ConnectionError("down")),
    )

    assert healthy == broken


async def test_a_programming_error_in_the_sink_is_logged_not_swallowed(caplog):
    """Not re-raised — that would destroy the decision — but not indistinguishable
    from an outage either. It gets its own event name and an error level, so a
    defect in the sink is findable."""
    await evaluate_settlement_compliance(
        _facts(),
        ListRepository([INR_RULE]),
        UnavailableRateProvider(),
        audit_sink=ExplodingAuditSink(TypeError("payload is not serialisable")),
    )

    assert "compliance_threshold_rate_unavailable_audit_error" in caplog.text
    assert "TypeError" in caplog.text


async def test_an_operational_failure_is_reported_as_a_warning(caplog):
    """The expected branch: a database that is briefly unreachable is not a
    defect, and must not be reported as one or the real defects drown."""
    await evaluate_settlement_compliance(
        _facts(),
        ListRepository([INR_RULE]),
        UnavailableRateProvider(),
        audit_sink=ExplodingAuditSink(ConnectionError("down")),
    )

    assert "compliance_threshold_rate_unavailable_audit_failed" in caplog.text
    assert "compliance_threshold_rate_unavailable_audit_error" not in caplog.text
