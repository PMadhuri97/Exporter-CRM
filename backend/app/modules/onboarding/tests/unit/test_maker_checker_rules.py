"""Maker-checker's pure rules: the required checks, the inputs fingerprint
and the served proposal actions, and the settings guard.

No database: these are the functions the service and the routes call.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_settings import (
    MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS,
    clear_validity,
    enforce_compliance_settings,
    maker_checker_enabled,
    rekyc_due_window,
)
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_AML_PASSED,
    CLEAR_KYB_PASSED,
    CLEAR_POLICY,
    CLEAR_RULES_V3,
    CLEAR_SANCTIONS_PASSED,
    CURRENT_CLEAR_RULES,
    PROPOSAL_APPROVE,
    PROPOSAL_REJECT,
    PROPOSAL_WITHDRAW,
    BackgroundCheckProposalView,
    evaluate_clear_prerequisites,
    inputs_fingerprint,
    proposal_actions,
    required_check_states,
    select_evidence,
)
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ScreeningItemInput,
    VerificationInput,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import Settings

State = BackgroundCheckState
CATALOGUE = ("a", "b")
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _check(
    verification_type: str,
    status: str = "PASSED",
    *,
    review: str | None = None,
    placeholder: bool = False,
    minutes_ago: int = 0,
) -> VerificationInput:
    return VerificationInput(
        verification_result_id=uuid.uuid4(),
        verification_type=verification_type,
        entity_type="EXPORTER",
        provider="manual",
        status=status,
        risk_level=None,
        performed_at=NOW - timedelta(minutes=minutes_ago),
        is_placeholder=placeholder,
        latest_review_id=uuid.uuid4() if review else None,
        latest_review_status=review,
        latest_reviewed_at=NOW if review else None,
        evidence_document_ids=(),
    )


def _inputs(*checks: VerificationInput, cycle: uuid.UUID | None = None) -> CompanyComplianceInputs:
    """Answered screening; ``checks`` newest first (the seam's order)."""
    return CompanyComplianceInputs(
        company_id=uuid.uuid4(),
        screening_catalogue=CATALOGUE,
        screening_items=tuple(
            ScreeningItemInput(
                item_key=key,
                screening_review_item_id=uuid.UUID(int=index + 1),
                status="PASSED",
                reviewed_by="c",
                reviewed_at=NOW,
            )
            for index, key in enumerate(CATALOGUE)
        ),
        verifications=checks,
        current_cycle_id=cycle,
    )


def _unmet(inputs: CompanyComplianceInputs) -> tuple[str, ...]:
    return evaluate_clear_prerequisites(
        inputs,
        risk=BackgroundCheckRisk.LOW,
        evidence=select_evidence(inputs),
        policy=CLEAR_POLICY,
    ).unmet


ALL_PASSED = (_check("KYB"), _check("AML"), _check("SANCTIONS"))


# ── Rule B ────────────────────────────────────────────────────────────


class TestRequiredChecks:
    def test_the_rules_version_moves_to_v3(self):
        assert CURRENT_CLEAR_RULES == CLEAR_RULES_V3 == "clear-2026-10-01-7items-kyb-aml-sanctions"
        assert len(CLEAR_RULES_V3) <= 64  # decision.rules_version is varchar(64)

    def test_all_three_passed_clears(self):
        assert _unmet(_inputs(*ALL_PASSED)) == ()

    def test_each_missing_type_is_named_in_order(self):
        assert _unmet(_inputs()) == (CLEAR_KYB_PASSED, CLEAR_AML_PASSED, CLEAR_SANCTIONS_PASSED)
        assert _unmet(_inputs(_check("KYB"), _check("AML"))) == (CLEAR_SANCTIONS_PASSED,)

    @pytest.mark.parametrize("failing", ["KYB", "AML", "SANCTIONS"])
    def test_a_failed_required_type_is_named(self, failing):
        checks = [_check(t, "FAILED" if t == failing else "PASSED") for t in ("KYB", "AML", "SANCTIONS")]
        assert _unmet(_inputs(*checks)) == (f"{failing.lower()}_passed",)

    def test_review_with_an_accepted_review_counts_as_passed(self):
        """REVIEW with an ACCEPTED review is passed (and no longer pending)."""
        checks = (_check("KYB", "REVIEW", review="ACCEPTED"), _check("AML"), _check("SANCTIONS"))
        assert _unmet(_inputs(*checks)) == ()

    @pytest.mark.parametrize("review", [None, "ESCALATED", "REJECTED"])
    def test_review_without_an_accepted_review_is_not_passed(self, review):
        checks = (_check("KYB", "REVIEW", review=review), _check("AML"), _check("SANCTIONS"))
        assert CLEAR_KYB_PASSED in _unmet(_inputs(*checks))

    def test_a_placeholder_never_counts(self):
        checks = (_check("KYB", placeholder=True), _check("AML"), _check("SANCTIONS"))
        assert CLEAR_KYB_PASSED in _unmet(_inputs(*checks))

    def test_the_latest_result_wins(self):
        failed_then_passed = (_check("KYB"), _check("KYB", "FAILED", minutes_ago=5))
        assert _unmet(_inputs(*failed_then_passed, _check("AML"), _check("SANCTIONS"))) == ()
        passed_then_failed = (_check("KYB", "FAILED"), _check("KYB", minutes_ago=5))
        assert _unmet(_inputs(*passed_then_failed, _check("AML"), _check("SANCTIONS"))) == (
            CLEAR_KYB_PASSED,
        )

    def test_other_types_neither_help_nor_hinder(self):
        checks = (*ALL_PASSED, _check("GST", "FAILED"), _check("PEP"))
        assert _unmet(_inputs(*checks)) == ()

    def test_the_read_model_serves_each_required_type_and_its_state(self):
        states = required_check_states(_inputs(_check("KYB"), _check("AML", "FAILED")))
        assert [(s.verification_type, s.state) for s in states] == [
            ("KYB", "PASSED"),
            ("AML", "FAILED"),
            ("SANCTIONS", "MISSING"),
        ]

    def test_a_policy_without_required_types_requires_none(self):
        policy = dataclasses.replace(CLEAR_POLICY, required_passed_types=())
        inputs = _inputs()
        assert (
            evaluate_clear_prerequisites(
                inputs, risk=BackgroundCheckRisk.LOW, evidence=select_evidence(inputs), policy=policy
            ).unmet
            == ()
        )


# ── The inputs fingerprint ───────────────────────────────────────────


class TestFingerprint:
    def test_it_is_stable_and_order_independent(self):
        a, b = _check("KYB"), _check("AML")
        first = _inputs(a, b)
        second = dataclasses.replace(first, verifications=(b, a))
        assert inputs_fingerprint(first, select_evidence(first)) == inputs_fingerprint(
            second, select_evidence(second)
        )
        assert len(inputs_fingerprint(first, select_evidence(first))) == 64

    def test_a_new_result_a_review_or_a_new_cycle_changes_it(self):
        base = _inputs(_check("KYB"))
        before = inputs_fingerprint(base, select_evidence(base))
        more = dataclasses.replace(base, verifications=(*base.verifications, _check("AML")))
        reviewed = dataclasses.replace(
            base,
            verifications=(
                dataclasses.replace(
                    base.verifications[0],
                    latest_review_id=uuid.uuid4(),
                    latest_review_status="ACCEPTED",
                ),
            ),
        )
        settled = dataclasses.replace(
            base, verifications=(dataclasses.replace(base.verifications[0], status="FAILED"),)
        )
        new_cycle = dataclasses.replace(base, current_cycle_id=uuid.uuid4())
        for changed in (more, reviewed, settled, new_cycle):
            assert inputs_fingerprint(changed, select_evidence(changed)) != before


# ── Proposal actions (role- and user-aware) ──────────────────────────────────


def _proposal(**overrides) -> BackgroundCheckProposalView:
    values = dict(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        based_on_decision_id=uuid.uuid4(),
        from_value=State.IN_REVIEW,
        to_value=State.CLEAR,
        risk_rating=BackgroundCheckRisk.LOW,
        reason="r",
        proposed_by="maker",
        proposed_at=NOW,
        cycle_id=uuid.uuid4(),
        rules_version=CLEAR_RULES_V3,
        evidence_count=3,
    )
    values.update(overrides)
    return BackgroundCheckProposalView(**values)


class TestProposalActions:
    def test_the_proposer_may_only_withdraw(self):
        assert proposal_actions(
            _proposal(), viewer_id="maker", viewer_may_resolve=True, is_stale=False
        ) == (PROPOSAL_WITHDRAW,)

    def test_another_officer_may_approve_or_reject(self):
        assert proposal_actions(
            _proposal(), viewer_id="checker", viewer_may_resolve=True, is_stale=False
        ) == (PROPOSAL_APPROVE, PROPOSAL_REJECT)

    def test_a_stale_proposal_can_only_be_rejected(self):
        assert proposal_actions(
            _proposal(), viewer_id="checker", viewer_may_resolve=True, is_stale=True
        ) == (PROPOSAL_REJECT,)

    def test_the_rm_may_do_nothing(self):
        assert proposal_actions(
            _proposal(), viewer_id="rm", viewer_may_resolve=False, is_stale=False
        ) == ()

    def test_nothing_on_a_resolved_proposal(self):
        assert proposal_actions(
            _proposal(status="APPROVED"), viewer_id="checker", viewer_may_resolve=True, is_stale=False
        ) == ()


class TestAllowedMovesMarkApproval:
    def test_clear_flag_and_hold_are_marked_for_approval(self):
        in_review = {m.to: m.approval_required for m in BackgroundCheckService.allowed_moves(State.IN_REVIEW, UserRole.COMPLIANCE)}
        assert in_review == {State.CLEAR: True, State.MORE_INFO: False, State.FLAGGED: True}
        flagged = {m.to: m.approval_required for m in BackgroundCheckService.allowed_moves(State.FLAGGED, UserRole.COMPLIANCE)}
        assert flagged == {State.ON_HOLD: True, State.IN_REVIEW: False}
        assert not any(
            m.approval_required
            for m in BackgroundCheckService.allowed_moves(State.CLEAR, UserRole.COMPLIANCE)
        )

    def test_with_maker_checker_off_nothing_needs_approval(self, monkeypatch):
        from app.platform.configuration import config

        monkeypatch.setattr(config.settings, "CRM_BACKGROUND_CHECK_MAKER_CHECKER", False)
        assert not maker_checker_enabled()
        assert not any(
            m.approval_required
            for m in BackgroundCheckService.allowed_moves(State.IN_REVIEW, UserRole.COMPLIANCE)
        )
        assert not BackgroundCheckService.needs_approval(State.CLEAR)


# ── The settings and the start-up guard ───────────────────────


class TestSettings:
    def test_the_defaults(self):
        settings = Settings(_env_file=None)
        assert settings.CRM_BACKGROUND_CHECK_MAKER_CHECKER is True
        assert clear_validity(settings) == timedelta(days=365)
        assert rekyc_due_window(settings) == timedelta(days=30)

    # `development` is refused too: it is the default ENVIRONMENT and what `.env.example`
    # (and so the docker-compose UAT stack) sets, so allowing it would make the guard inert.
    @pytest.mark.parametrize(
        "environment", ["production", "uat", "staging", "Production", "development"]
    )
    def test_the_application_refuses_to_start_with_maker_checker_off_outside_local_or_test(
        self, environment
    ):
        settings = Settings(
            _env_file=None, ENVIRONMENT=environment, CRM_BACKGROUND_CHECK_MAKER_CHECKER=False
        )
        with pytest.raises(RuntimeError, match="CRM_BACKGROUND_CHECK_MAKER_CHECKER is off"):
            enforce_compliance_settings(settings)

    @pytest.mark.parametrize("environment", sorted(MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS))
    def test_it_may_be_off_in_local_and_test(self, environment):
        enforce_compliance_settings(
            Settings(
                _env_file=None, ENVIRONMENT=environment, CRM_BACKGROUND_CHECK_MAKER_CHECKER=False
            )
        )

    def test_on_is_accepted_everywhere(self):
        enforce_compliance_settings(Settings(_env_file=None, ENVIRONMENT="production"))

    def test_the_default_environment_does_not_allow_it_off(self):
        """A server started with no ENVIRONMENT set must still refuse 'off'. The
        default is read from the field, not the process, so an exported ENVIRONMENT in
        the shell running the tests cannot change what is checked."""
        default = Settings.model_fields["ENVIRONMENT"].default
        assert default.strip().lower() not in MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS
        with pytest.raises(RuntimeError, match="CRM_BACKGROUND_CHECK_MAKER_CHECKER is off"):
            enforce_compliance_settings(
                Settings(
                    _env_file=None, ENVIRONMENT=default, CRM_BACKGROUND_CHECK_MAKER_CHECKER=False
                )
            )

    @pytest.mark.parametrize(
        ("name", "value"),
        [("CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS", 0), ("CRM_REKYC_DUE_WINDOW_DAYS", -1)],
    )
    def test_an_out_of_range_duration_refuses_start(self, name, value):
        with pytest.raises(RuntimeError, match=name):
            enforce_compliance_settings(Settings(_env_file=None, **{name: value}))
