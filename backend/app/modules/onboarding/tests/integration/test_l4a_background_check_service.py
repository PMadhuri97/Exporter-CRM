"""``BackgroundCheckService`` against a real database — Developer 4A, 4A-3 and 4A-4.

The pure rules are proved without a session in
``tests/unit/test_l4a_background_check_rules.py``. This file proves what only a
database can: the row lock, one transaction per move, the supersession chain, the
history row, and that a refusal leaves nothing behind.

Every test mints its own company, so nothing here depends on or damages shared rows.
The seam is a **fake** ``ComplianceInputsReader`` by default — the service must work
against the Protocol, not against Dev4B's implementation — with a separate section
proving it also works against the real ``ComplianceInputsService``.

**Maker-checker (Developer 1, plan P3-1d).** With maker-checker on — the default, and
how this suite runs — ``CLEAR``, ``FLAGGED`` and ``ON_HOLD`` take two people. These
tests are about the move mechanism, so they make those moves through
``TwoPersonService``: its ``clear``/``flag``/``hold``/``record_decision`` propose as the
caller and approve as a **second** compliance user, exactly the two acts the API takes.
Nothing here is a single-user path; maker-checker itself is proved in
``test_dev1_maker_checker.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.background_check_views import CLEAR_POLICY, ClearPolicy
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ScreeningItemInput,
    VerificationInput,
)
from app.modules.onboarding.domain.entities.background_check_decision import (
    BackgroundCheckDecision,
    BackgroundCheckEvidence,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckDecidedByKind,
    BackgroundCheckDecisionSource,
    BackgroundCheckEvidenceKind,
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.crm_document import CrmDocument
from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.storage import DocumentScanStatus
from app.modules.onboarding.exceptions import (
    BackgroundCheckMoveNotAllowedError,
    BackgroundCheckPrerequisitesUnmetError,
    BackgroundCheckProposalOpenError,
    BackgroundCheckReasonRequiredError,
    BackgroundCheckRiskNotAllowedError,
    BackgroundCheckRiskRequiredError,
    BackgroundCheckRoleNotAllowedError,
    BackgroundCheckStateChangedError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories import (
    BackgroundCheckDecisionRepository,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

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

#: A policy of these tests' own, so they pin the move mechanism rather than the
#: settled D1–D4 answers — those are `CLEAR_POLICY`, exercised through `_settled`
#: below and, end to end with nothing substituted, by `test_customer_promotion.py`
#: and `test_crm_end_to_end.py`. It is deliberately more lenient than the shipped
#: policy (`REVIEW` and placeholders do not block).
TEST_POLICY = ClearPolicy(
    pending_verification_statuses=frozenset({"PENDING"}),
    placeholder_counts_as_pending=False,
    answered_screening_statuses=frozenset({"PASSED", "EXEMPT"}),
    evidence_required=True,
)


class ReaderFailedError(Exception):
    """Raised by the fake to prove the service does not swallow a reader failure."""


@dataclass
class FakeReader:
    """A ``ComplianceInputsReader`` the tests control completely.

    Records its calls, so a test can prove the service reads company inputs and
    **never** buyer checks (§6.2 invariant 4, architecture §3.5).
    """

    screening: dict[str, str | None] | None = None
    verifications: tuple[VerificationInput, ...] = ()
    raises: Exception | None = None
    company_calls: list[uuid.UUID] = field(default_factory=list)
    buyer_calls: list[uuid.UUID] = field(default_factory=list)

    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs:
        self.company_calls.append(company_id)
        if self.raises is not None:
            raise self.raises
        answers = self.screening if self.screening is not None else dict.fromkeys(CATALOGUE, "PASSED")
        return CompanyComplianceInputs(
            company_id=company_id,
            screening_catalogue=CATALOGUE,
            screening_items=tuple(
                ScreeningItemInput(
                    item_key=key,
                    screening_review_item_id=None,
                    status=answers.get(key),
                    reviewed_by="compliance-user" if answers.get(key) else None,
                    reviewed_at=datetime.now(UTC) if answers.get(key) else None,
                )
                for key in CATALOGUE
            ),
            verifications=self.verifications,
        )

    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]:
        self.buyer_calls.append(deal_buyer_id)
        return ()


#: The second compliance user who approves what the tests propose (P3-1d).
CHECKER = "second-compliance-user"


class TwoPersonService(BackgroundCheckService):
    """``BackgroundCheckService`` whose approval-needing moves (IQ-1) are the two acts
    maker-checker requires, in one call: the caller proposes, ``CHECKER`` approves.
    Every refusal a move gives still comes from the proposal (premise, legality, role,
    text, risk, prerequisites), before anything is written."""

    async def _two_person(
        self,
        company_id: uuid.UUID,
        *,
        to_value: State,
        reason: str | None,
        risk: BackgroundCheckRisk | None,
        actor_id: str,
        actor_role: UserRole,
        seen_value: State | None = None,
    ):
        proposal = await self.propose(
            company_id,
            to_value=to_value,
            reason=reason,
            risk=risk,
            actor_id=actor_id,
            actor_role=actor_role,
            seen_value=seen_value,
        )
        approved = await self.approve(
            company_id, proposal.id, actor_id=CHECKER, actor_role=UserRole.COMPLIANCE
        )
        return approved.decision

    async def clear(self, company_id, *, risk, reason, actor_id, actor_role):
        return await self._two_person(
            company_id, to_value=State.CLEAR, reason=reason, risk=risk,
            actor_id=actor_id, actor_role=actor_role,
        )

    async def flag(self, company_id, *, reason, actor_id, actor_role):
        return await self._two_person(
            company_id, to_value=State.FLAGGED, reason=reason, risk=None,
            actor_id=actor_id, actor_role=actor_role,
        )

    async def hold(self, company_id, *, reason, actor_id, actor_role):
        return await self._two_person(
            company_id, to_value=State.ON_HOLD, reason=reason, risk=None,
            actor_id=actor_id, actor_role=actor_role,
        )

    async def record_decision(
        self, company_id, *, to_value, reason, risk, actor_id, actor_role, seen_value=None
    ):
        if self.needs_approval(to_value):
            return await self._two_person(
                company_id, to_value=to_value, reason=reason, risk=risk,
                actor_id=actor_id, actor_role=actor_role, seen_value=seen_value,
            )
        return await super().record_decision(
            company_id, to_value=to_value, reason=reason, risk=risk,
            actor_id=actor_id, actor_role=actor_role, seen_value=seen_value,
        )


def _service(db, reader: FakeReader | None = None) -> BackgroundCheckService:
    return TwoPersonService(db, reader=reader or FakeReader(), clear_policy=TEST_POLICY)


def _settled(db, reader: FakeReader | None = None) -> BackgroundCheckService:
    """A service running the **shipped** policy, for tests about the settled answers."""
    return TwoPersonService(db, reader=reader or FakeReader(), clear_policy=CLEAR_POLICY)


def _pinned_documents(view) -> set[uuid.UUID]:
    return {
        item.crm_document_id
        for item in view.evidence
        if item.kind is BackgroundCheckEvidenceKind.DOCUMENT
    }


async def _document(company_id: uuid.UUID, scan_status: DocumentScanStatus) -> uuid.UUID:
    """One real `crm_document` row on the company — Developer 3B's table."""
    document_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            CrmDocument(
                id=document_id,
                company_id=company_id,
                deal_id=None,
                category=DocumentCategory.ENTITY_KYC,
                document_type="certificate_of_incorporation",
                source=DocumentSource.INTERNAL,
                file_name="evidence.pdf",
                content_type="application/pdf",
                size_bytes=11,
                storage_key=f"test/company/{company_id}/internal/{document_id}.pdf",
                uploaded_by="compliance-user",
                uploaded_at=datetime.now(UTC),
                scan_status=scan_status,
                scanner_name="pass-through",
            )
        )
        await db.commit()
    return document_id


async def _state(company_id: uuid.UUID) -> State:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(ExporterProfile.background_check).where(
                ExporterProfile.customer_id == company_id
            )
        )


async def _decisions(company_id: uuid.UUID) -> list[BackgroundCheckDecision]:
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await BackgroundCheckDecisionRepository(db).list_for_company(company_id)
        return rows


async def _history(company_id: uuid.UUID) -> list:
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            company_id, dimension="background_check"
        )
        return rows


async def _started(reader: FakeReader | None = None) -> uuid.UUID:
    """A company whose check is `IN_REVIEW` — the start of most moves."""
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        await _service(db, reader).start_review(
            company_id, actor_id="ops-user", actor_role=UserRole.OPERATIONS
        )
    return company_id


async def _flagged(reader: FakeReader | None = None) -> uuid.UUID:
    company_id = await _started(reader)
    async with db_services.AsyncSessionLocal() as db:
        await _service(db, reader).flag(
            company_id,
            reason="adverse media",
            actor_id="compliance-user",
            actor_role=UserRole.COMPLIANCE,
        )
    return company_id


# ── Every legal forward move (4A-3) ──────────────────────────────────────────


class TestLegalMoves:
    async def test_a_new_company_starts_at_not_started(self):
        # The column's default, so there is no `background_check_initial` history row
        # to write — the precedent `ConversationService` set (contract §3).
        company_id = await make_company()
        assert await _state(company_id) is State.NOT_STARTED
        assert await _decisions(company_id) == []
        assert await _history(company_id) == []

    async def test_move_1_starts_the_review(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).start_review(
                company_id, actor_id="ops-user", actor_role=UserRole.OPERATIONS
            )
        assert await _state(company_id) is State.IN_REVIEW
        assert view.from_value is State.NOT_STARTED
        assert view.to_value is State.IN_REVIEW
        # The only move with no text, and the first decision in the chain.
        assert view.reason is None
        assert view.supersedes_decision_id is None

    async def test_move_3_asks_for_more_information(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).request_more_info(
                company_id,
                note="need the 2025 audited accounts",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.MORE_INFO
        assert view.reason == "need the 2025 audited accounts"

    async def test_move_4_records_what_arrived(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).request_more_info(
                company_id,
                note="need the accounts",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        async with db_services.AsyncSessionLocal() as db:
            # OPERATIONS may make this one — it is the second of their two moves.
            await _service(db).record_more_info(
                company_id,
                note="accounts received",
                actor_id="ops-user",
                actor_role=UserRole.OPERATIONS,
            )
        assert await _state(company_id) is State.IN_REVIEW

    async def test_move_5_flags(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id,
                reason="sanctions hit on a director",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.FLAGGED

    async def test_move_6_holds_a_flagged_company(self):
        company_id = await _flagged()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).hold(
                company_id,
                reason="awaiting the regulator",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.ON_HOLD

    async def test_the_text_is_stored_once_and_copied_to_history(self):
        # Contract §4: stored on the decision, copied to the history row.
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id,
                reason="  adverse media  ",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        [decision] = [d for d in await _decisions(company_id) if d.to_value is State.FLAGGED]
        assert decision.reason == "adverse media"  # trimmed
        rows = await _history(company_id)
        assert rows[0].reason == "adverse media"

    async def test_the_actor_is_recorded_and_the_kind_is_manual(self):
        company_id = await _started()
        [decision] = await _decisions(company_id)
        assert decision.decided_by == "ops-user"
        # Nothing writes AUTOMATED: the one automatic move is blocked on D12.
        assert decision.decided_by_kind is BackgroundCheckDecidedByKind.MANUAL
        assert decision.source is BackgroundCheckDecisionSource.MANUAL


# ── Every illegal move (4A-3) ────────────────────────────────────────────────


class TestIllegalMoves:
    async def test_a_move_from_the_wrong_state_is_refused(self):
        company_id = await make_company()  # still NOT_STARTED
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckMoveNotAllowedError):
                await _service(db).flag(
                    company_id,
                    reason="r",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.NOT_STARTED

    async def test_starting_a_check_twice_is_refused(self):
        # A move to the value already held would record nothing (contract §3).
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckMoveNotAllowedError):
                await _service(db).start_review(
                    company_id, actor_id="ops-user", actor_role=UserRole.OPERATIONS
                )

    async def test_holding_a_company_that_is_not_flagged_is_refused(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckMoveNotAllowedError):
                await _service(db).hold(
                    company_id,
                    reason="r",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )

    async def test_an_unknown_company_is_a_404(self):
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(ExporterProfileNotFoundError):
                await _service(db).start_review(
                    uuid.uuid4(), actor_id="ops-user", actor_role=UserRole.OPERATIONS
                )

    async def test_a_refused_move_writes_no_decision_and_no_history(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckMoveNotAllowedError):
                await _service(db).flag(
                    company_id,
                    reason="r",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _decisions(company_id) == []
        assert await _history(company_id) == []


# ── Role refusals, per move (4A-3) ───────────────────────────────────────────


class TestRoles:
    async def test_operations_may_not_flag(self):
        # The refusal that matters most: one route serves several moves, so a
        # route-level check alone would let operations flag a company.
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).flag(
                    company_id,
                    reason="r",
                    actor_id="ops-user",
                    actor_role=UserRole.OPERATIONS,
                )
        assert await _state(company_id) is State.IN_REVIEW

    async def test_operations_may_not_ask_for_more_information(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).request_more_info(
                    company_id, note="n", actor_id="ops-user", actor_role=UserRole.OPERATIONS
                )

    @pytest.mark.parametrize("role", [UserRole.DEVELOPER, UserRole.API_USER])
    async def test_developer_and_api_user_make_no_move(self, role):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).start_review(
                    company_id, actor_id="someone", actor_role=role
                )
        assert await _decisions(company_id) == []

    async def test_a_role_refusal_writes_nothing(self):
        company_id = await _started()
        before = len(await _decisions(company_id))
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).flag(
                    company_id, reason="r", actor_id="ops", actor_role=UserRole.OPERATIONS
                )
        assert len(await _decisions(company_id)) == before
        assert len(await _history(company_id)) == before


# ── Text and risk (4A-3, 4A-4) ───────────────────────────────────────────────


class TestRequiredText:
    @pytest.mark.parametrize("blank", [None, "", "   ", "\n\t"])
    async def test_flagging_without_a_reason_is_refused(self, blank):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckReasonRequiredError):
                await _service(db).flag(
                    company_id,
                    reason=blank,
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.IN_REVIEW
        assert len(await _decisions(company_id)) == 1  # only the start

    async def test_recording_what_arrived_without_a_note_is_refused(self):
        """The architecture requires this note; `history-row.md` §4 omits it (D14)."""
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).request_more_info(
                company_id,
                note="need accounts",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckReasonRequiredError):
                await _service(db).record_more_info(
                    company_id, note="  ", actor_id="ops", actor_role=UserRole.OPERATIONS
                )
        assert await _state(company_id) is State.MORE_INFO

    async def test_the_start_needs_no_text(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).start_review(
                company_id, actor_id="ops-user", actor_role=UserRole.OPERATIONS
            )
        assert view.reason is None


# ── One transaction per move (contract §9) ───────────────────────────────────


class TestOneTransaction:
    async def test_the_value_decision_evidence_and_history_land_together(self):
        reader = FakeReader(verifications=())
        company_id = await _started(reader)
        decisions = await _decisions(company_id)
        history = await _history(company_id)
        assert len(decisions) == 1
        assert len(history) == 1
        assert await _state(company_id) is State.IN_REVIEW

    async def test_history_is_written_exactly_once_per_move(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id,
                reason="r",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        rows = await _history(company_id)
        assert len(rows) == 2
        # The entity's columns are `from_status`/`to_status`; only the API view
        # renames them to `from_value`/`to_value`.
        assert [(r.from_status, r.to_status) for r in rows][::-1] == [
            ("NOT_STARTED", "IN_REVIEW"),
            ("IN_REVIEW", "FLAGGED"),
        ]

    async def test_the_history_row_carries_the_decision_id_and_evidence_count(self):
        # Contract §8: ids, never evidence content or PII.
        company_id = await _started()
        [decision] = await _decisions(company_id)
        [row] = await _history(company_id)
        assert row.event_metadata["decision_id"] == str(decision.id)
        assert row.event_metadata["supersedes_decision_id"] is None
        assert row.event_metadata["evidence_count"] == 0
        assert row.event_metadata["source"] == "background_check_service.start_review"
        assert row.dimension == "background_check"

    async def test_a_failure_after_the_decision_rolls_everything_back(self):
        """A history failure must take the value, the decision and the evidence with it
        — and, for an approval, the resolution: the proposal stays open."""
        company_id = await _started()

        class BoomError(Exception):
            pass

        async with db_services.AsyncSessionLocal() as db:
            proposal = await _service(db).propose(
                company_id,
                to_value=State.FLAGGED,
                reason="r",
                risk=None,
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        async with db_services.AsyncSessionLocal() as db:
            service = _service(db)

            async def explode(*args, **kwargs):
                raise BoomError

            service._history.record = explode  # type: ignore[method-assign]
            with pytest.raises(BoomError):
                await service.approve(
                    company_id, proposal.id, actor_id=CHECKER, actor_role=UserRole.COMPLIANCE
                )
            await db.rollback()
        async with db_services.AsyncSessionLocal() as db:
            still_open = await BackgroundCheckService(db).open_proposal(company_id)
        assert still_open is not None and still_open[0].id == proposal.id

        # Nothing of the flag survives: not the value, not the decision, not history.
        assert await _state(company_id) is State.IN_REVIEW
        assert len(await _decisions(company_id)) == 1
        assert len(await _history(company_id)) == 1

    async def test_a_reader_failure_propagates_and_writes_nothing(self):
        # The seam never swallows, and neither does this service (background-check.md §12.1).
        company_id = await _started()
        reader = FakeReader(raises=ReaderFailedError("provider down"))
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(ReaderFailedError):
                await _service(db, reader).flag(
                    company_id,
                    reason="r",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.IN_REVIEW
        assert len(await _decisions(company_id)) == 1


# ── The supersession chain (contract §5.4) ───────────────────────────────────


class TestChain:
    async def test_each_decision_supersedes_the_one_before(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id, reason="r", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).hold(
                company_id, reason="r2", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        rows = await _decisions(company_id)  # newest first
        assert [r.to_value for r in rows] == [State.ON_HOLD, State.FLAGGED, State.IN_REVIEW]
        assert rows[0].supersedes_decision_id == rows[1].id
        assert rows[1].supersedes_decision_id == rows[2].id
        assert rows[2].supersedes_decision_id is None

    async def test_the_first_decision_is_the_only_one_with_no_predecessor(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id, reason="r", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        rows = await _decisions(company_id)
        assert sum(1 for r in rows if r.supersedes_decision_id is None) == 1

    async def test_an_earlier_decision_is_untouched_by_a_later_one(self):
        """Append-only: the previous decision is byte-identical afterwards."""
        company_id = await _started()
        [first] = await _decisions(company_id)
        before = (first.id, first.from_value, first.to_value, first.reason, first.decided_at)

        async with db_services.AsyncSessionLocal() as db:
            await _service(db).flag(
                company_id, reason="r", actor_id="c", actor_role=UserRole.COMPLIANCE
            )

        rows = await _decisions(company_id)
        again = next(r for r in rows if r.id == first.id)
        assert (again.id, again.from_value, again.to_value, again.reason, again.decided_at) == before

    async def test_two_concurrent_moves_serialise_and_only_one_wins(self):
        """The company row lock is what stops a fork, before the unique index has to.

        Two sessions try to flag the same `IN_REVIEW` company at once. The lock makes
        the second wait; by the time it reads, the first has either proposed (one open
        proposal per company) or been approved (the company is `FLAGGED`), so its move
        is refused. The chain never forks.
        """
        company_id = await _started()

        async def flag(actor: str):
            async with db_services.AsyncSessionLocal() as db:
                return await _service(db).flag(
                    company_id,
                    reason=f"by {actor}",
                    actor_id=actor,
                    actor_role=UserRole.COMPLIANCE,
                )

        results = await asyncio.gather(flag("a"), flag("b"), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(failures) == 1
        assert isinstance(
            failures[0], BackgroundCheckMoveNotAllowedError | BackgroundCheckProposalOpenError
        )

        rows = await _decisions(company_id)
        assert [r.to_value for r in rows] == [State.FLAGGED, State.IN_REVIEW]
        # One successor per decision: the chain is a line, not a tree.
        assert len({r.supersedes_decision_id for r in rows if r.supersedes_decision_id}) == 1
        assert len(await _history(company_id)) == 2

    async def test_the_database_refuses_a_forked_chain_even_without_the_service(self):
        """`uq_background_check_decision_supersedes` is the backstop under the lock."""
        company_id = await _started()
        [first] = await _decisions(company_id)
        async with db_services.AsyncSessionLocal() as db:
            repo = BackgroundCheckDecisionRepository(db)
            await repo.record(
                BackgroundCheckDecision(
                    company_id=company_id,
                    from_value=State.IN_REVIEW,
                    to_value=State.FLAGGED,
                    decided_by="c",
                    decided_by_kind=BackgroundCheckDecidedByKind.MANUAL,
                    source=BackgroundCheckDecisionSource.MANUAL,
                    reason="one",
                    supersedes_decision_id=first.id,
                )
            )
            await db.commit()
        with pytest.raises(Exception):  # IntegrityError — a second successor
            async with db_services.AsyncSessionLocal() as db:
                repo = BackgroundCheckDecisionRepository(db)
                await repo.record(
                    BackgroundCheckDecision(
                        company_id=company_id,
                        from_value=State.IN_REVIEW,
                        to_value=State.MORE_INFO,
                        decided_by="c",
                        decided_by_kind=BackgroundCheckDecidedByKind.MANUAL,
                        source=BackgroundCheckDecisionSource.MANUAL,
                        reason="two",
                        supersedes_decision_id=first.id,
                    )
                )
                await db.commit()


# ── The evidence snapshot (contract §6) ──────────────────────────────────────


class TestEvidence:
    async def test_every_decision_takes_a_snapshot_not_only_clear(self):
        # The architecture says "each decision" (contract §6).
        company_id = await make_company()
        reader = FakeReader()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db, reader).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        # The fake reports no screening row ids, so this snapshot is legitimately empty.
        assert view.evidence == ()
        assert reader.company_calls == [company_id]

    async def test_a_snapshot_pins_the_verification_results_it_relied_on(self):
        check = VerificationInput(
            verification_result_id=uuid.uuid4(),
            verification_type="GST",
            entity_type="EXPORTER",
            provider="manual",
            status="PASSED",
            risk_level=None,
            performed_at=datetime.now(UTC),
            is_placeholder=False,
            latest_review_id=None,
            latest_review_status=None,
            latest_reviewed_at=None,
            evidence_document_ids=(),
        )
        company_id = await make_company()
        # The pinned id must be a real `verification_result` row: the foreign key is
        # RESTRICT, so evidence cannot point at something that does not exist.
        async with db_services.AsyncSessionLocal() as db:
            exists = await db.scalar(
                text("SELECT id FROM onboarding.verification_result LIMIT 1")
            )
        if exists is None:
            pytest.skip("no verification_result row available to pin")
        check = VerificationInput(**{**check.__dict__, "verification_result_id": exists})

        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db, FakeReader(verifications=(check,))).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        assert len(view.evidence) == 1
        assert view.evidence[0].kind is BackgroundCheckEvidenceKind.VERIFICATION_RESULT
        assert view.evidence[0].verification_result_id == exists

        async with db_services.AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(BackgroundCheckEvidence).where(
                            BackgroundCheckEvidence.decision_id == view.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].verification_result_id == exists

    async def test_a_company_with_no_documents_pins_none(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        assert all(
            item.kind is not BackgroundCheckEvidenceKind.DOCUMENT for item in view.evidence
        )

    async def test_it_pins_the_company_documents_that_passed_the_scan(self):
        """D4, settled 28 Sep 2026: the company's own `AVAILABLE` documents.

        Through Developer 3B's real `crm_document` rows and their real foreign key —
        there is no second document system (contract §6).
        """
        company_id = await make_company()
        available = await _document(company_id, DocumentScanStatus.AVAILABLE)
        quarantined = await _document(company_id, DocumentScanStatus.QUARANTINED)

        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )

        pinned = _pinned_documents(view)
        assert pinned == {available}
        # Never served, so never named as evidence.
        assert quarantined not in pinned

    @pytest.mark.parametrize(
        "status",
        [DocumentScanStatus.PENDING_SCAN, DocumentScanStatus.SCAN_FAILED],
    )
    async def test_it_never_pins_a_document_that_cannot_be_served(self, status):
        company_id = await make_company()
        blocked = await _document(company_id, status)
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        assert blocked not in _pinned_documents(view)

    async def test_a_pinned_document_cannot_then_be_deleted(self):
        """`RESTRICT`: evidence cannot vanish from under a decision (contract §6)."""
        company_id = await make_company()
        document_id = await _document(company_id, DocumentScanStatus.AVAILABLE)
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        with pytest.raises(Exception):  # ForeignKeyViolation
            async with db_services.AsyncSessionLocal() as db:
                await db.execute(
                    text("DELETE FROM onboarding.crm_document WHERE id = :id"),
                    {"id": document_id},
                )
                await db.commit()

    async def test_more_than_one_page_of_documents_is_pinned(self):
        """`list_for_owner` pages at 50; a snapshot must not stop at the first page.

        An append-only row cannot be corrected afterwards, so a silently truncated
        snapshot would be permanent.
        """
        company_id = await make_company()
        expected = set()
        for _ in range(55):
            expected.add(await _document(company_id, DocumentScanStatus.AVAILABLE))
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        assert _pinned_documents(view) == expected

    async def test_the_gauge_never_reads_buyer_checks(self):
        """A buyer's problems stay on the buyer (architecture §3.5, §6.2 invariant 4)."""
        reader = FakeReader()
        await _started(reader)
        assert reader.buyer_calls == []


# ── CLEAR (4A-4) ─────────────────────────────────────────────────────────────


class TestClear:
    async def test_clearing_without_a_risk_rating_is_refused(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRiskRequiredError):
                await _service(db).clear(
                    company_id,
                    risk=None,
                    reason="all checks in order",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.IN_REVIEW
        assert len(await _decisions(company_id)) == 1

    async def test_clearing_without_a_reason_is_refused(self):
        """Architecture §4.1 step 9 requires it; `history-row.md` §4 omits it (D14)."""
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckReasonRequiredError):
                await _service(db).clear(
                    company_id,
                    risk=BackgroundCheckRisk.LOW,
                    reason=None,
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )

    async def test_operations_may_not_clear(self):
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).clear(
                    company_id,
                    risk=BackgroundCheckRisk.LOW,
                    reason="looks fine",
                    actor_id="ops-user",
                    actor_role=UserRole.OPERATIONS,
                )
        assert await _state(company_id) is State.IN_REVIEW

    async def test_a_pending_check_blocks_the_clear_and_is_named(self):
        pending = VerificationInput(
            verification_result_id=uuid.uuid4(),
            verification_type="GST",
            entity_type="EXPORTER",
            provider="manual",
            status="PENDING",
            risk_level=None,
            performed_at=datetime.now(UTC),
            is_placeholder=False,
            latest_review_id=None,
            latest_review_status=None,
            latest_reviewed_at=None,
            evidence_document_ids=(),
        )
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as raised:
                await _service(db, FakeReader(verifications=(pending,))).clear(
                    company_id,
                    risk=BackgroundCheckRisk.LOW,
                    reason="ready",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert "no_checks_pending" in raised.value.extensions["unmet"]
        assert await _state(company_id) is State.IN_REVIEW

    async def test_an_unanswered_screening_item_blocks_the_clear(self):
        reader = FakeReader(screening={**dict.fromkeys(CATALOGUE, "PASSED"), "pep": None})
        company_id = await _started(reader)
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as raised:
                await _service(db, reader).clear(
                    company_id,
                    risk=BackgroundCheckRisk.LOW,
                    reason="ready",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert "screening_items_answered" in raised.value.extensions["unmet"]

    async def test_a_blocked_clear_writes_nothing(self):
        reader = FakeReader(screening=dict.fromkeys(CATALOGUE, None))
        company_id = await _started(reader)
        before = len(await _decisions(company_id))
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckPrerequisitesUnmetError):
                await _service(db, reader).clear(
                    company_id,
                    risk=BackgroundCheckRisk.LOW,
                    reason="ready",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert len(await _decisions(company_id)) == before
        assert len(await _history(company_id)) == before

    async def test_clear_prerequisites_reads_without_locking_or_writing(self):
        reader = FakeReader(screening=dict.fromkeys(CATALOGUE, None))
        company_id = await _started(reader)
        async with db_services.AsyncSessionLocal() as db:
            unmet = await _service(db, reader).clear_prerequisites(company_id)
        assert "screening_items_answered" in unmet
        # Advisory only: it wrote nothing.
        assert len(await _decisions(company_id)) == 1

    async def test_a_company_meeting_every_prerequisite_is_cleared(self):
        """The settled rule, end to end: eight items PASSED, no pending check, evidence."""
        company_id = await make_company()
        await _document(company_id, DocumentScanStatus.AVAILABLE)
        reader = FakeReader()  # all eight PASSED, no verifications
        async with db_services.AsyncSessionLocal() as db:
            await _service(db, reader).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db, reader).clear(
                company_id,
                risk=BackgroundCheckRisk.MEDIUM,
                reason="all eight items answered, no checks outstanding",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.CLEAR
        assert view.risk_rating is BackgroundCheckRisk.MEDIUM
        # The clearing decision names the evidence it rested on.
        assert view.evidence

    async def test_a_failed_screening_item_blocks_the_clear(self):
        """D3, settled: a company with a failed item is FLAGGED, not CLEAR."""
        company_id = await make_company()
        await _document(company_id, DocumentScanStatus.AVAILABLE)
        reader = FakeReader(
            screening={**dict.fromkeys(CATALOGUE, "PASSED"), "pep": "FAILED"}
        )
        async with db_services.AsyncSessionLocal() as db:
            await _settled(db, reader).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as raised:
                await _settled(db, reader).clear(
                    company_id,
                    risk=BackgroundCheckRisk.HIGH,
                    reason="mitigated",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert "screening_items_answered" in raised.value.extensions["unmet"]

    async def test_a_company_with_no_evidence_at_all_cannot_be_cleared(self):
        """D4, settled: a cleared company must rest on something recorded."""
        company_id = await make_company()  # no documents
        reader = FakeReader()  # the fake reports no screening row ids either
        async with db_services.AsyncSessionLocal() as db:
            await _service(db, reader).start_review(
                company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
            )
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as raised:
                await _service(db, reader).clear(
                    company_id,
                    risk=BackgroundCheckRisk.LOW,
                    reason="nothing to go on",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert "evidence_recorded" in raised.value.extensions["unmet"]

    async def test_the_journey_is_never_touched_by_a_background_check_move(self):
        """The gauge is not the journey (company-record §3.1, A5)."""
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            before = await db.scalar(
                select(ExporterProfile.journey).where(
                    ExporterProfile.customer_id == company_id
                )
            )
            await _service(db).flag(
                company_id, reason="r", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        async with db_services.AsyncSessionLocal() as db:
            after = await db.scalar(
                select(ExporterProfile.journey).where(
                    ExporterProfile.customer_id == company_id
                )
            )
        assert after == before


# ── Against the real seam, not the fake ──────────────────────────────────────


class TestAgainstTheRealReader:
    """The service must work against Dev4B's implementation, not only the Protocol."""

    async def test_a_move_succeeds_reading_through_compliance_inputs_service(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            service = BackgroundCheckService(
                db, reader=ComplianceInputsService(db), clear_policy=TEST_POLICY
            )
            view = await service.start_review(
                company_id, actor_id="ops-user", actor_role=UserRole.OPERATIONS
            )
        assert await _state(company_id) is State.IN_REVIEW
        assert view.to_value is State.IN_REVIEW

    async def test_the_default_reader_is_the_real_one(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            service = BackgroundCheckService(db)
            assert isinstance(service._reader, ComplianceInputsService)
            await service.start_review(
                company_id, actor_id="ops-user", actor_role=UserRole.OPERATIONS
            )
        assert await _state(company_id) is State.IN_REVIEW

    async def test_a_fresh_company_has_eight_unanswered_screening_items(self):
        """The seam's empty value (background-check.md §12.1), and what it means for CLEAR."""
        company_id = await _started()
        async with db_services.AsyncSessionLocal() as db:
            service = BackgroundCheckService(
                db, reader=ComplianceInputsService(db), clear_policy=TEST_POLICY
            )
            unmet = await service.clear_prerequisites(company_id)
        assert "screening_items_answered" in unmet

# ── Reopen and reassessment (4A-5) ───────────────────────────────────────────


async def _cleared(reader: FakeReader | None = None) -> uuid.UUID:
    """A company whose check is `CLEAR`, with real evidence behind it."""
    reader = reader or FakeReader()
    company_id = await make_company()
    await _document(company_id, DocumentScanStatus.AVAILABLE)
    async with db_services.AsyncSessionLocal() as db:
        await _service(db, reader).start_review(
            company_id, actor_id="ops", actor_role=UserRole.OPERATIONS
        )
    async with db_services.AsyncSessionLocal() as db:
        await _service(db, reader).clear(
            company_id,
            risk=BackgroundCheckRisk.LOW,
            reason="everything in order",
            actor_id="compliance-user",
            actor_role=UserRole.COMPLIANCE,
        )
    return company_id


class TestReopen:
    async def test_a_cleared_company_can_be_reopened(self):
        company_id = await _cleared()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).reopen(
                company_id,
                reason="new adverse media surfaced",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.IN_REVIEW
        assert view.from_value is State.CLEAR
        assert view.reason == "new adverse media surfaced"

    async def test_a_reopen_without_a_reason_is_refused(self):
        company_id = await _cleared()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckReasonRequiredError):
                await _service(db).reopen(
                    company_id,
                    reason="   ",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.CLEAR

    async def test_operations_may_not_reopen(self):
        company_id = await _cleared()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).reopen(
                    company_id,
                    reason="r",
                    actor_id="ops-user",
                    actor_role=UserRole.OPERATIONS,
                )
        assert await _state(company_id) is State.CLEAR

    async def test_a_cleared_company_cannot_be_flagged_directly(self):
        """Architecture §4.2: new information goes through a reopen, then FLAGGED.

        The point is the record: a reopen forces the reason onto the chain before
        anything is concluded.
        """
        company_id = await _cleared()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckMoveNotAllowedError):
                await _service(db).flag(
                    company_id,
                    reason="sanctions hit",
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.CLEAR

    async def test_the_clearing_decision_is_byte_identical_after_a_reopen(self):
        """Direct SQL, not the ORM: the row itself must be untouched.

        Read through psycopg rather than the session that wrote it, so a cached or
        refreshed instance cannot make an edited row look unchanged.
        """
        company_id = await _cleared()

        async with db_services.AsyncSessionLocal() as db:
            before = (
                await db.execute(
                    text(
                        "SELECT id, from_value::text, to_value::text, decided_by, "
                        "reason, risk_rating::text, decided_at, supersedes_decision_id "
                        "FROM onboarding.background_check_decision "
                        "WHERE company_id = :c AND to_value = 'CLEAR'"
                    ),
                    {"c": company_id},
                )
            ).one()

        async with db_services.AsyncSessionLocal() as db:
            await _service(db).reopen(
                company_id,
                reason="reassessing",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )

        async with db_services.AsyncSessionLocal() as db:
            after = (
                await db.execute(
                    text(
                        "SELECT id, from_value::text, to_value::text, decided_by, "
                        "reason, risk_rating::text, decided_at, supersedes_decision_id "
                        "FROM onboarding.background_check_decision "
                        "WHERE company_id = :c AND to_value = 'CLEAR'"
                    ),
                    {"c": company_id},
                )
            ).one()

        assert tuple(after) == tuple(before)

    async def test_the_reopen_supersedes_the_clearing_decision(self):
        company_id = await _cleared()
        clearing = next(d for d in await _decisions(company_id) if d.to_value is State.CLEAR)
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).reopen(
                company_id,
                reason="reassessing",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert view.supersedes_decision_id == clearing.id
        # Still one chain, not a tree.
        rows = await _decisions(company_id)
        successors = [r.supersedes_decision_id for r in rows if r.supersedes_decision_id]
        assert len(successors) == len(set(successors))

    async def test_reopening_a_customer_does_not_demote_the_journey(self):
        """A `CUSTOMER` whose check is reopened stays `CUSTOMER` (company-record §3.1, A5).

        The company is inserted at `CUSTOMER` directly: Developer 2's promotion (L2-11)
        does not exist, and Dev4A must not invent it.
        """
        company_id = await _cleared()
        async with db_services.AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE onboarding.exporter_profile SET journey = 'CUSTOMER' "
                    "WHERE customer_id = :c"
                ),
                {"c": company_id},
            )
            await db.commit()

        async with db_services.AsyncSessionLocal() as db:
            await _service(db).reopen(
                company_id,
                reason="periodic reassessment",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )

        async with db_services.AsyncSessionLocal() as db:
            journey = await db.scalar(
                text(
                    "SELECT journey::text FROM onboarding.exporter_profile "
                    "WHERE customer_id = :c"
                ),
                {"c": company_id},
            )
        assert journey == "CUSTOMER"
        assert await _state(company_id) is State.IN_REVIEW

    async def test_a_reopened_company_can_be_cleared_again(self):
        """The chain keeps going: reopen, then clear, then reopen."""
        reader = FakeReader()
        company_id = await _cleared(reader)
        async with db_services.AsyncSessionLocal() as db:
            await _service(db, reader).reopen(
                company_id, reason="look again", actor_id="c", actor_role=UserRole.COMPLIANCE
            )
        async with db_services.AsyncSessionLocal() as db:
            await _service(db, reader).clear(
                company_id,
                risk=BackgroundCheckRisk.HIGH,
                reason="reviewed, still acceptable",
                actor_id="c",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.CLEAR
        rows = await _decisions(company_id)
        assert [r.to_value for r in rows] == [
            State.CLEAR,
            State.IN_REVIEW,
            State.CLEAR,
            State.IN_REVIEW,
        ]
        # The new clearing decision carries the new risk; the old one still carries LOW.
        clears = [r for r in rows if r.to_value is State.CLEAR]
        assert clears[0].risk_rating is BackgroundCheckRisk.HIGH
        assert clears[1].risk_rating is BackgroundCheckRisk.LOW


class TestReassess:
    async def test_a_flagged_company_can_be_reassessed(self):
        company_id = await _flagged()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).reassess(
                company_id,
                reason="the director resigned",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.IN_REVIEW
        assert view.from_value is State.FLAGGED

    async def test_a_company_on_hold_can_be_reassessed(self):
        company_id = await _flagged()
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).hold(
                company_id, reason="awaiting regulator", actor_id="c",
                actor_role=UserRole.COMPLIANCE,
            )
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).reassess(
                company_id,
                reason="the regulator replied",
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert await _state(company_id) is State.IN_REVIEW
        assert view.from_value is State.ON_HOLD

    async def test_a_reassessment_without_a_reason_is_refused(self):
        company_id = await _flagged()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckReasonRequiredError):
                await _service(db).reassess(
                    company_id, reason=None, actor_id="c", actor_role=UserRole.COMPLIANCE
                )
        assert await _state(company_id) is State.FLAGGED

    async def test_operations_may_not_reassess(self):
        company_id = await _flagged()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRoleNotAllowedError):
                await _service(db).reassess(
                    company_id, reason="r", actor_id="ops", actor_role=UserRole.OPERATIONS
                )

    async def test_reassessing_a_company_that_is_neither_flagged_nor_on_hold_is_refused(self):
        company_id = await _started()  # IN_REVIEW
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckMoveNotAllowedError):
                await _service(db).reassess(
                    company_id, reason="r", actor_id="c", actor_role=UserRole.COMPLIANCE
                )

    async def test_the_flag_decision_is_unchanged_after_a_reassessment(self):
        company_id = await _flagged()
        flagged = next(d for d in await _decisions(company_id) if d.to_value is State.FLAGGED)
        before = (flagged.id, flagged.reason, flagged.decided_at)
        async with db_services.AsyncSessionLocal() as db:
            await _service(db).reassess(
                company_id, reason="looking again", actor_id="c",
                actor_role=UserRole.COMPLIANCE,
            )
        again = next(d for d in await _decisions(company_id) if d.id == flagged.id)
        assert (again.id, again.reason, again.decided_at) == before

    async def test_the_whole_move_table_is_now_covered(self):
        """All nine of contract §3 are reachable through the service.

        The counterpart of 4A-3's `test_the_reopen_and_reassess_rows_are_not_offered_yet`,
        which this phase deliberately replaced.
        """
        from app.modules.onboarding.application.background_check_service import _MOVES
        from app.modules.onboarding.domain.entities.background_check_decision import LEGAL_MOVES

        assert set(_MOVES) == set(LEGAL_MOVES)


# ── Risk belongs to CLEAR only (PR review, 28 Sep 2026) ──────────────────────


class TestRiskOnlyOnClear:
    """Risk is compliance's rating at the moment of clearing (contract §7). A rating on
    any other move would become what the reader reports as the company's risk, and
    an OPERATIONS start could set it."""

    async def test_operations_cannot_set_a_risk_by_starting_a_check(self):
        company_id = await make_company()
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRiskNotAllowedError):
                await _service(db).record_decision(
                    company_id,
                    to_value=State.IN_REVIEW,
                    reason=None,
                    risk=BackgroundCheckRisk.CRITICAL,
                    actor_id="ops-user",
                    actor_role=UserRole.OPERATIONS,
                )
        assert await _state(company_id) is State.NOT_STARTED
        assert await _decisions(company_id) == []
        assert await _history(company_id) == []

    @pytest.mark.parametrize("to_value", [State.MORE_INFO, State.FLAGGED])
    async def test_compliance_cannot_attach_a_risk_to_a_non_clear_move(self, to_value):
        company_id = await _started()
        before = len(await _decisions(company_id))
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckRiskNotAllowedError):
                await _service(db).record_decision(
                    company_id,
                    to_value=to_value,
                    reason="because",
                    risk=BackgroundCheckRisk.HIGH,
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                )
        assert await _state(company_id) is State.IN_REVIEW
        assert len(await _decisions(company_id)) == before


# ── The caller's premise: a stale screen cannot become a different act ──────


class TestSeenValue:
    """Four moves share the destination `IN_REVIEW`. Without `seen_value`, a
    reassessment sent from a screen still showing `FLAGGED` would reopen a company
    someone had cleared in the meantime."""

    async def test_a_stale_reassessment_does_not_reopen_a_clearance(self):
        company_id = await _cleared()
        before = await _decisions(company_id)
        async with db_services.AsyncSessionLocal() as db:
            with pytest.raises(BackgroundCheckStateChangedError) as caught:
                await _service(db).record_decision(
                    company_id,
                    to_value=State.IN_REVIEW,
                    reason="reassessing the flag",
                    risk=None,
                    actor_id="compliance-user",
                    actor_role=UserRole.COMPLIANCE,
                    seen_value=State.FLAGGED,
                )
        assert caught.value.error_code == "BACKGROUND_CHECK_STATE_CHANGED"
        assert await _state(company_id) is State.CLEAR
        assert len(await _decisions(company_id)) == len(before)

    async def test_a_matching_premise_makes_the_move(self):
        company_id = await _flagged()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).record_decision(
                company_id,
                to_value=State.IN_REVIEW,
                reason="reassessing the flag",
                risk=None,
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
                seen_value=State.FLAGGED,
            )
        assert view.from_value is State.FLAGGED
        assert await _state(company_id) is State.IN_REVIEW

    async def test_without_a_premise_the_move_is_resolved_from_the_current_value(self):
        """`seen_value` is optional: server code and older clients keep working."""
        company_id = await _cleared()
        async with db_services.AsyncSessionLocal() as db:
            view = await _service(db).record_decision(
                company_id,
                to_value=State.IN_REVIEW,
                reason="new adverse media",
                risk=None,
                actor_id="compliance-user",
                actor_role=UserRole.COMPLIANCE,
            )
        assert view.from_value is State.CLEAR
