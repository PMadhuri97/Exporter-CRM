"""The background check's pure rules — Developer 4A, 4A-3 and 4A-4.

No database and no session: the move table, the evidence selection and A3's `CLEAR`
prerequisites are pure functions, which is the point of the 4A ↔ 4B seam returning
facts rather than judgements (`4a/4b-task.md` §6.2 invariant 1). The service's use of
them, under a row lock and in one transaction, is proved in the integration files.

Most prerequisite tests drive the mechanism through an **explicit policy** rather than
the shipped one, so they pin the mechanism rather than the answer — which is what let
them be written while D1–D4 were open, and what keeps them meaningful if an answer is
revisited. `test_the_shipped_policy_carries_the_settled_answers` is the exception: it pins the
D1–D4 answers of 28 September 2026, so changing one is deliberate and arrives with a
failing test.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_EVIDENCE_RECORDED,
    CLEAR_NO_CHECKS_PENDING,
    CLEAR_POLICY,
    CLEAR_RISK_REQUIRED,
    CLEAR_SCREENING_ANSWERED,
    ClearPolicy,
    DocumentInput,
    EvidenceSelection,
    evaluate_clear_prerequisites,
    select_evidence,
)
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ScreeningItemInput,
    VerificationInput,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.platform.authentication.models import UserRole

State = BackgroundCheckState

CATALOGUE = (
    "sanctions",
    "pep",
    "adverse_media",
    "ownership",
    "jurisdiction",
    "sector",
    "litigation",
    "regulatory",
)

#: An explicit policy for the tests, so no test depends on an unanswered decision.
TEST_POLICY = ClearPolicy(
    pending_verification_statuses=frozenset({"PENDING"}),
    placeholder_counts_as_pending=False,
    answered_screening_statuses=frozenset({"PASSED", "EXEMPT", "FAILED"}),
    evidence_required=True,
)


def _verification(
    *,
    status: str = "PASSED",
    is_placeholder: bool = False,
    review_id: uuid.UUID | None = None,
) -> VerificationInput:
    return VerificationInput(
        verification_result_id=uuid.uuid4(),
        verification_type="GST",
        entity_type="EXPORTER",
        provider="manual",
        status=status,
        risk_level=None,
        performed_at=datetime.now(UTC),
        is_placeholder=is_placeholder,
        latest_review_id=review_id,
        latest_review_status=None,
        latest_reviewed_at=None,
        evidence_document_ids=(),
    )


def _inputs(
    *,
    screening: dict[str, str | None] | None = None,
    verifications: tuple[VerificationInput, ...] = (),
    company_id: uuid.UUID | None = None,
) -> CompanyComplianceInputs:
    """Inputs with every catalogue key present, as the seam guarantees (§6.3)."""
    answers = screening or dict.fromkeys(CATALOGUE, "PASSED")
    return CompanyComplianceInputs(
        company_id=company_id or uuid.uuid4(),
        screening_catalogue=CATALOGUE,
        screening_items=tuple(
            ScreeningItemInput(
                item_key=key,
                screening_review_item_id=uuid.uuid4() if answers.get(key) else None,
                status=answers.get(key),
                reviewed_by="compliance-user" if answers.get(key) else None,
                reviewed_at=datetime.now(UTC) if answers.get(key) else None,
            )
            for key in CATALOGUE
        ),
        verifications=verifications,
    )


# ── The move table (4A-3) ────────────────────────────────────────────────────


class TestAllowedMoves:
    """The rules as data. Contract §3, per move and per role."""

    def test_operations_may_start_a_check_and_nothing_else_from_not_started(self):
        moves = BackgroundCheckService.allowed_moves(State.NOT_STARTED, UserRole.OPERATIONS)
        assert [move.to for move in moves] == [State.IN_REVIEW]
        # Move 1 is the only move that needs no text.
        assert moves[0].reason_required is False
        assert moves[0].risk_required is False

    def test_operations_may_not_clear_flag_or_ask_for_more(self):
        # The refusal that matters: the route serving move 1 also serves move 5, so a
        # route-level role check alone would let operations flag a company.
        assert BackgroundCheckService.allowed_moves(State.IN_REVIEW, UserRole.OPERATIONS) == []

    def test_operations_may_record_what_arrived(self):
        moves = BackgroundCheckService.allowed_moves(State.MORE_INFO, UserRole.OPERATIONS)
        assert [move.to for move in moves] == [State.IN_REVIEW]
        # The architecture requires the note even though `history-row.md` §4 omits it (D14).
        assert moves[0].reason_required is True

    @pytest.mark.parametrize("role", [UserRole.COMPLIANCE, UserRole.ADMIN])
    def test_compliance_and_admin_get_the_same_moves(self, role):
        moves = BackgroundCheckService.allowed_moves(State.IN_REVIEW, role)
        assert {move.to for move in moves} == {State.CLEAR, State.MORE_INFO, State.FLAGGED}

    def test_only_clear_requires_a_risk_rating(self):
        moves = BackgroundCheckService.allowed_moves(State.IN_REVIEW, UserRole.COMPLIANCE)
        by_value = {move.to: move for move in moves}
        assert by_value[State.CLEAR].risk_required is True
        assert by_value[State.FLAGGED].risk_required is False
        assert by_value[State.MORE_INFO].risk_required is False

    @pytest.mark.parametrize("role", [UserRole.DEVELOPER, UserRole.API_USER])
    @pytest.mark.parametrize("current", list(State))
    def test_developer_and_api_user_make_no_move_from_anywhere(self, role, current):
        assert BackgroundCheckService.allowed_moves(current, role) == []

    def test_a_cleared_company_is_never_flagged_directly(self):
        # Architecture §4.2: new information about a cleared company goes through a
        # reopen, so that the reason is on the record.
        for role in (UserRole.COMPLIANCE, UserRole.ADMIN):
            offered = {
                move.to for move in BackgroundCheckService.allowed_moves(State.CLEAR, role)
            }
            assert State.FLAGGED not in offered

    def test_no_move_leads_back_to_not_started(self):
        # A check that has begun has begun; there is no "un-start".
        for current in State:
            for role in UserRole:
                offered = {
                    move.to for move in BackgroundCheckService.allowed_moves(current, role)
                }
                assert State.NOT_STARTED not in offered

    def test_no_move_ends_where_it_started(self):
        # A move to the value already held would record nothing (contract §3).
        for current in State:
            for role in UserRole:
                for move in BackgroundCheckService.allowed_moves(current, role):
                    assert move.to is not current

    def test_the_reopen_and_reassess_rows_are_offered(self):
        """4A-5's three moves. Each needs a reason and none takes a risk rating.

        This replaced a 4A-3 test that pinned their *absence*; that test failing was
        the intended signal that this phase had arrived.
        """
        for current in (State.CLEAR, State.FLAGGED, State.ON_HOLD):
            offered = {
                move.to: move
                for move in BackgroundCheckService.allowed_moves(current, UserRole.COMPLIANCE)
            }
            assert State.IN_REVIEW in offered
            assert offered[State.IN_REVIEW].reason_required is True
            assert offered[State.IN_REVIEW].risk_required is False

    def test_operations_may_not_reopen_or_reassess(self):
        for current in (State.CLEAR, State.FLAGGED, State.ON_HOLD):
            assert BackgroundCheckService.allowed_moves(current, UserRole.OPERATIONS) == []

    def test_a_company_on_hold_is_only_offered_a_reassessment(self):
        offered = {
            move.to for move in BackgroundCheckService.allowed_moves(
                State.ON_HOLD, UserRole.COMPLIANCE
            )
        }
        assert offered == {State.IN_REVIEW}


# ── The evidence selection (4A-3) ────────────────────────────────────────────


class TestSelectEvidence:
    def test_it_pins_every_verification_result_with_its_review(self):
        review_id = uuid.uuid4()
        check = _verification(review_id=review_id)
        selection = select_evidence(_inputs(verifications=(check,)))
        assert selection.verifications == ((check.verification_result_id, review_id),)

    def test_a_result_with_no_review_pins_a_null_review_id(self):
        # The seam reports `latest_review_id = None` until Dev4B's 4B-2 lands
        # (contract §6.1), and the column is nullable for exactly that reason.
        check = _verification(review_id=None)
        selection = select_evidence(_inputs(verifications=(check,)))
        assert selection.verifications == ((check.verification_result_id, None),)

    def test_it_pins_the_screening_rows_that_exist(self):
        selection = select_evidence(_inputs())
        assert len(selection.screening_items) == len(CATALOGUE)

    def test_an_item_never_answered_has_no_row_to_pin(self):
        inputs = _inputs(screening={**dict.fromkeys(CATALOGUE, "PASSED"), "pep": None})
        selection = select_evidence(inputs)
        assert len(selection.screening_items) == len(CATALOGUE) - 1

    def test_it_pins_the_company_documents_that_passed_the_scan(self):
        # D4, settled 28 Sep 2026: the company's own AVAILABLE documents.
        available = DocumentInput(uuid.uuid4(), "AVAILABLE")
        selection = select_evidence(_inputs(), (available,))
        assert selection.documents == (available.document_id,)

    @pytest.mark.parametrize(
        "status", ["PENDING_SCAN", "QUARANTINED", "SCAN_FAILED"]
    )
    def test_it_never_pins_a_document_that_cannot_be_served(self, status):
        # Pinning one would name evidence nobody can open
        # (`storage-and-documents.md` §4).
        blocked = DocumentInput(uuid.uuid4(), status)
        assert select_evidence(_inputs(), (blocked,)).documents == ()

    def test_it_pins_no_documents_when_the_company_has_none(self):
        assert select_evidence(_inputs(), ()).documents == ()

    def test_the_document_rule_keeps_only_the_servable_ones(self):
        good, bad = uuid.uuid4(), uuid.uuid4()
        selection = select_evidence(
            _inputs(),
            (DocumentInput(good, "AVAILABLE"), DocumentInput(bad, "QUARANTINED")),
        )
        assert selection.documents == (good,)

    def test_a_company_with_no_inputs_yields_an_empty_snapshot(self):
        # The normal case for move 1, and legitimate: a snapshot may be empty.
        empty = CompanyComplianceInputs(
            company_id=uuid.uuid4(),
            screening_catalogue=CATALOGUE,
            screening_items=tuple(
                ScreeningItemInput(key, None, None, None, None) for key in CATALOGUE
            ),
            verifications=(),
        )
        assert select_evidence(empty).count == 0

    def test_the_count_covers_all_three_kinds(self):
        selection = EvidenceSelection(
            verifications=((uuid.uuid4(), None), (uuid.uuid4(), None)),
            screening_items=(uuid.uuid4(),),
            documents=(uuid.uuid4(),),
        )
        assert selection.count == 4


# ── A3's CLEAR prerequisites (4A-4) ──────────────────────────────────────────


class TestClearPrerequisites:
    """The rule is pure, and it names every unmet prerequisite, not just the first."""

    def _evaluate(self, inputs, *, risk=BackgroundCheckRisk.LOW, evidence=None):
        return evaluate_clear_prerequisites(
            inputs,
            risk=risk,
            evidence=evidence if evidence is not None else select_evidence(inputs),
            policy=TEST_POLICY,
        )

    def test_everything_in_order_is_met(self):
        assert self._evaluate(_inputs(verifications=(_verification(),))).met

    def test_a_missing_risk_rating_is_unmet(self):
        result = self._evaluate(_inputs(verifications=(_verification(),)), risk=None)
        assert CLEAR_RISK_REQUIRED in result.unmet

    @pytest.mark.parametrize("risk", list(BackgroundCheckRisk))
    def test_every_risk_value_satisfies_the_risk_prerequisite(self, risk):
        result = self._evaluate(_inputs(verifications=(_verification(),)), risk=risk)
        assert CLEAR_RISK_REQUIRED not in result.unmet

    def test_a_pending_check_is_unmet(self):
        inputs = _inputs(verifications=(_verification(status="PENDING"),))
        assert CLEAR_NO_CHECKS_PENDING in self._evaluate(inputs).unmet

    def test_an_unanswered_screening_item_is_unmet(self):
        inputs = _inputs(screening={**dict.fromkeys(CATALOGUE, "PASSED"), "sanctions": None})
        assert CLEAR_SCREENING_ANSWERED in self._evaluate(inputs).unmet

    def test_a_needs_review_item_is_unmet(self):
        inputs = _inputs(
            screening={**dict.fromkeys(CATALOGUE, "PASSED"), "pep": "NEEDS_REVIEW"}
        )
        assert CLEAR_SCREENING_ANSWERED in self._evaluate(inputs).unmet

    def test_an_empty_snapshot_is_unmet_when_the_policy_requires_evidence(self):
        inputs = _inputs()
        assert CLEAR_EVIDENCE_RECORDED in self._evaluate(
            inputs, evidence=EvidenceSelection()
        ).unmet

    def test_it_reports_every_unmet_prerequisite_at_once(self):
        # So the screen lists what is outstanding rather than revealing it one
        # refusal at a time.
        inputs = _inputs(
            screening=dict.fromkeys(CATALOGUE, None),
            verifications=(_verification(status="PENDING"),),
        )
        result = self._evaluate(inputs, risk=None, evidence=EvidenceSelection())
        assert set(result.unmet) == {
            CLEAR_RISK_REQUIRED,
            CLEAR_NO_CHECKS_PENDING,
            CLEAR_SCREENING_ANSWERED,
            CLEAR_EVIDENCE_RECORDED,
        }

    def test_the_catalogue_size_comes_from_the_seam_not_from_a_constant(self):
        """"All eight items" is the seam's catalogue, however long it happens to be.

        If Dev4B's catalogue ever changes length, the rule must follow it rather than
        compare against a hard-coded eight.
        """
        nine = (*CATALOGUE, "extra")
        inputs = CompanyComplianceInputs(
            company_id=uuid.uuid4(),
            screening_catalogue=nine,
            screening_items=tuple(
                ScreeningItemInput(key, uuid.uuid4(), "PASSED", "u", datetime.now(UTC))
                for key in CATALOGUE  # the ninth is absent
            ),
            verifications=(),
        )
        result = evaluate_clear_prerequisites(
            inputs,
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs),
            policy=TEST_POLICY,
        )
        assert CLEAR_SCREENING_ANSWERED in result.unmet

    def test_the_policy_decides_what_pending_means(self):
        """D2 is a policy field, so the mechanism runs under either answer."""
        inputs = _inputs(verifications=(_verification(status="REVIEW"),))
        lenient = evaluate_clear_prerequisites(
            inputs,
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs),
            policy=TEST_POLICY,
        )
        strict = evaluate_clear_prerequisites(
            inputs,
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs),
            policy=ClearPolicy(
                pending_verification_statuses=frozenset({"PENDING", "REVIEW"}),
                placeholder_counts_as_pending=False,
                answered_screening_statuses=TEST_POLICY.answered_screening_statuses,
                evidence_required=True,
            ),
        )
        assert CLEAR_NO_CHECKS_PENDING not in lenient.unmet
        assert CLEAR_NO_CHECKS_PENDING in strict.unmet

    def test_the_policy_decides_whether_a_placeholder_is_pending(self):
        inputs = _inputs(verifications=(_verification(is_placeholder=True),))
        assert CLEAR_NO_CHECKS_PENDING not in self._evaluate(inputs).unmet
        strict = evaluate_clear_prerequisites(
            inputs,
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs),
            policy=ClearPolicy(
                pending_verification_statuses=TEST_POLICY.pending_verification_statuses,
                placeholder_counts_as_pending=True,
                answered_screening_statuses=TEST_POLICY.answered_screening_statuses,
                evidence_required=True,
            ),
        )
        assert CLEAR_NO_CHECKS_PENDING in strict.unmet

    def test_the_policy_decides_whether_failed_counts_as_answered(self):
        """D3 is a policy field, so the mechanism runs under either answer.

        The settled answer is the strict one — `TestClearPrerequisites` above pins it
        through `CLEAR_POLICY`; this test proves the *mechanism* is not hard-wired to it.
        """
        inputs = _inputs(screening={**dict.fromkeys(CATALOGUE, "PASSED"), "pep": "FAILED"})
        assert CLEAR_SCREENING_ANSWERED not in self._evaluate(inputs).unmet
        strict = evaluate_clear_prerequisites(
            inputs,
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs),
            policy=ClearPolicy(
                pending_verification_statuses=TEST_POLICY.pending_verification_statuses,
                placeholder_counts_as_pending=False,
                answered_screening_statuses=frozenset({"PASSED", "EXEMPT"}),
                evidence_required=True,
            ),
        )
        assert CLEAR_SCREENING_ANSWERED in strict.unmet

    def test_the_shipped_policy_carries_the_settled_answers(self):
        """D1–D4 as decided on 28 September 2026 (`background-check.md` §14).

        Pinned so that changing any of them is deliberate and arrives with a failing
        test, rather than quietly altering what "cleared" means for every company.
        """
        # D2: pending unless terminal with a real provider.
        assert CLEAR_POLICY.pending_verification_statuses == {"PENDING", "REVIEW"}
        assert CLEAR_POLICY.placeholder_counts_as_pending is True
        # D3: "answered" means answered satisfactorily — a FAILED item blocks CLEAR.
        assert CLEAR_POLICY.answered_screening_statuses == {"PASSED", "EXEMPT"}
        assert "FAILED" not in CLEAR_POLICY.answered_screening_statuses
        # D4: a cleared company must rest on something recorded.
        assert CLEAR_POLICY.evidence_required is True
        # D2, clarified in the PR review: an ACCEPTED or REJECTED review finishes a
        # REVIEW result; an ESCALATED one does not.
        assert CLEAR_POLICY.concluding_review_statuses == {"ACCEPTED", "REJECTED"}

    def test_the_rule_reads_nothing_but_its_arguments(self):
        """Pure: the same arguments give the same answer, with no session in sight."""
        inputs = _inputs(verifications=(_verification(),))
        first = self._evaluate(inputs)
        second = self._evaluate(inputs)
        assert first == second


# ── D2: a review finishes a REVIEW result ────────────────────────────────────


def _reviewed(status: str, review_status: str | None, *, placeholder: bool = False):
    return dataclasses.replace(
        _verification(status=status, is_placeholder=placeholder),
        latest_review_status=review_status,
    )


def _settled_unmet(*checks: VerificationInput) -> tuple[str, ...]:
    inputs = _inputs(verifications=checks)
    return evaluate_clear_prerequisites(
        inputs,
        risk=BackgroundCheckRisk.LOW,
        evidence=select_evidence(inputs),
        policy=CLEAR_POLICY,
    ).unmet


class TestAReviewFinishesAReviewResult:
    """`VerificationService.review` records `review_status` and never changes
    `status`, so a `REVIEW` result stays `REVIEW` after compliance has dealt with it.
    Read as pending for ever, it would make the company impossible to clear."""

    @pytest.mark.parametrize("review_status", ["ACCEPTED", "REJECTED"])
    def test_a_finished_review_concludes_a_review_result(self, review_status):
        assert _settled_unmet(_reviewed("REVIEW", review_status)) == ()

    @pytest.mark.parametrize("review_status", [None, "ESCALATED"])
    def test_an_unreviewed_or_escalated_review_result_is_still_pending(self, review_status):
        assert _settled_unmet(_reviewed("REVIEW", review_status)) == (CLEAR_NO_CHECKS_PENDING,)

    def test_an_unreviewed_pending_result_is_still_pending(self):
        """`PENDING` cannot be reviewed (the service refuses), so it waits for the
        provider exactly as before."""
        assert _settled_unmet(_reviewed("PENDING", None)) == (CLEAR_NO_CHECKS_PENDING,)

    def test_a_reviewed_placeholder_is_still_pending(self):
        """A placeholder never ran; accepting it does not make it a result."""
        assert _settled_unmet(_reviewed("PASSED", "ACCEPTED", placeholder=True)) == (
            CLEAR_NO_CHECKS_PENDING,
        )

    def test_the_default_policy_field_is_the_strict_reading(self):
        """A policy that does not name concluding reviews treats none as concluding."""
        inputs = _inputs(verifications=(_reviewed("REVIEW", "ACCEPTED"),))
        strict = evaluate_clear_prerequisites(
            inputs,
            risk=BackgroundCheckRisk.LOW,
            evidence=select_evidence(inputs),
            policy=ClearPolicy(
                pending_verification_statuses=frozenset({"PENDING", "REVIEW"}),
                placeholder_counts_as_pending=True,
                answered_screening_statuses=frozenset({"PASSED", "EXEMPT"}),
                evidence_required=True,
            ),
        )
        assert strict.unmet == (CLEAR_NO_CHECKS_PENDING,)


# ── The evidence view kinds line up with the entity's check constraint ───────


def test_every_evidence_kind_is_covered_by_the_selection():
    """A kind the selection can never produce would be dead schema."""
    produced = {
        BackgroundCheckEvidenceKind.VERIFICATION_RESULT,
        BackgroundCheckEvidenceKind.SCREENING_ITEM,
        BackgroundCheckEvidenceKind.DOCUMENT,
    }
    assert produced == set(BackgroundCheckEvidenceKind)
