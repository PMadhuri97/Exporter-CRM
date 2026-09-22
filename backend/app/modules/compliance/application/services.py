"""
ComplianceService — runs KYB validation, mock sanctions screening,
DNFBP detection, AML risk scoring, and the maker-checker approval workflow.

All screening results and approval records are append-only (DB trigger enforced).
Status transitions are written atomically with status-history entries.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import ActorType, AuditService
from app.modules.compliance.api.schemas import (
    ApprovalResult,
    ApprovalsStateResponse,
    ApprovalSubmittedResponse,
    ScreeningResult,
    ScreeningRunResponse,
    SubmitApprovalRequest,
)
from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.application.rule_engine import ComplianceActionSet
from app.modules.compliance.application.sector_risk_service import (
    get_sector_risk_classification,
)
from app.modules.compliance.domain.entities.compliance import (
    ApprovalDecision,
    ApproverRole,
    CaseType,
    ComplianceApproval,
    ComplianceCase,
    ComplianceScreening,
    ScreeningStatus,
    ScreeningType,
)
from app.modules.compliance.domain.policies import screening as policies
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.required_action import RequiredAction
from app.modules.compliance.infrastructure import screening as sanctions
from app.modules.compliance.infrastructure.compliance_audit_sink import (
    AuditServiceComplianceAuditSink,
)
from app.modules.compliance.infrastructure.compliance_rule_repository import (
    SQLAlchemyComplianceRuleRepository,
)
from app.modules.compliance.infrastructure.repository import (
    ApprovalRepository,
    CaseRepository,
    ScreeningRepository,
)
from app.modules.compliance.infrastructure.sector_risk_repository import (
    SQLAlchemySectorRiskRepository,
)
from app.modules.customers import CustomerRepository
from app.modules.payments import (
    StatusHistoryRepository,
    Transaction,
    TransactionRepository,
    TransactionStatus,
    TransactionStatusHistory,
)
from app.platform.authentication.models import User
from app.shared.exceptions import AnerBaseException, NotFoundError

if TYPE_CHECKING:
    from app.temporal._actor import TemporalActor

logger = structlog.get_logger(__name__)


class ComplianceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._tx_repo = TransactionRepository(db)
        self._history_repo = StatusHistoryRepository(db)
        self._customer_repo = CustomerRepository(db)
        self._screening_repo = ScreeningRepository(db)
        self._approval_repo = ApprovalRepository(db)
        self._case_repo = CaseRepository(db)
        self._sector_repo = SQLAlchemySectorRiskRepository(db)
        self._rule_repo = SQLAlchemyComplianceRuleRepository(db)
        self._audit = AuditService(db)

    # ── The compliance position, as reference data ────────────────────────────

    async def _evaluate_rules(
        self,
        tx: Transaction,
        *,
        sector_risk_tier: str | None = None,
        classification_label: str | None = None,
    ) -> ComplianceActionSet:
        facts = ComplianceFacts(
            send_amount_minor=int(tx.amount),
            send_asset_code=tx.source_currency,
            as_of_date=tx.created_at.date(),
            sector_risk_tier=sector_risk_tier,
            classification_label=classification_label,
        )
        return await evaluate_settlement_compliance(
            facts,
            self._rule_repo,
            audit_sink=AuditServiceComplianceAuditSink(self._db),
        )

    # ── Screening ─────────────────────────────────────────────────────────────

    async def run_screening(
        self, transaction_id: uuid.UUID, actor: User | TemporalActor
    ) -> ScreeningRunResponse:
        tx = await self._tx_repo.get_by_transaction_id(transaction_id)
        if tx is None:
            raise NotFoundError(f"Transaction {transaction_id} not found")

        if tx.status != TransactionStatus.INITIATED:
            raise AnerBaseException(
                detail=f"Transaction is in status {tx.status.value}; screening can only run on INITIATED transactions",
                error_code="ALREADY_SCREENED",
                status_code=409,
            )

        sender = await self._customer_repo.get_by_customer_id(tx.sender_customer_id)
        beneficiary = await self._customer_repo.get_by_customer_id(tx.beneficiary_customer_id)
        if sender is None or beneficiary is None:
            raise NotFoundError("Sender or beneficiary customer record not found")

        # ── KYB validation (pre-screening gate) ───────────────────────────────
        from app.modules.customers import KYBStatus

        kyb_fail_reason: str | None = None
        if sender.kyb_status != KYBStatus.VERIFIED:
            kyb_fail_reason = f"Sender KYB status is {sender.kyb_status.value}; VERIFIED required"
        elif beneficiary.kyb_status != KYBStatus.VERIFIED:
            kyb_fail_reason = (
                f"Beneficiary KYB status is {beneficiary.kyb_status.value}; VERIFIED required"
            )

        if kyb_fail_reason:
            tx = await self._transition(
                tx,
                TransactionStatus.VALIDATION_FAILED,
                actor_id=actor.id,
                reason=kyb_fail_reason,
            )
            await self._audit.record(
                "compliance.kyb.validation.failed",
                transaction_id=transaction_id,
                actor_id=actor.id,
                actor_type=ActorType.COMPLIANCE_OFFICER,
                payload={"reason": kyb_fail_reason},
            )
            return ScreeningRunResponse(
                transaction_id=transaction_id,
                transaction_status=tx.status,
                edd_required=False,
                screenings=[],
            )

        # ── Sanctions screening (OFAC, UN, EU, RBI) ──────────────────────────
        sanctions_types = [
            ScreeningType.SANCTIONS_OFAC,
            ScreeningType.SANCTIONS_UN,
            ScreeningType.SANCTIONS_EU,
            ScreeningType.SANCTIONS_RBI,
        ]
        screening_records: list[ComplianceScreening] = []
        blocked = False

        for stype in sanctions_types:
            for entity in (sender, beneficiary):
                status, payload = sanctions.screen_entity_sanctions(entity.entity_name, stype)
                record = await self._screening_repo.create(
                    ComplianceScreening(
                        transaction_id=transaction_id,
                        screening_type=stype,
                        status=status,
                        provider=payload.get("provider"),
                        result_payload=payload,
                    )
                )
                screening_records.append(record)
                if status == ScreeningStatus.FAIL:
                    blocked = True

        if blocked:
            await self._case_repo.create(
                ComplianceCase(
                    transaction_id=transaction_id,
                    case_type=CaseType.SANCTIONS_HIT,
                )
            )
            tx = await self._transition(
                tx,
                TransactionStatus.BLOCKED,
                actor_id=actor.id,
                reason="Sanctions screening hit — transaction blocked",
            )
            await self._audit.record(
                "compliance.transaction.blocked",
                transaction_id=transaction_id,
                actor_id=actor.id,
                actor_type=ActorType.COMPLIANCE_OFFICER,
                payload={"reason": "Sanctions screening hit"},
            )
            return self._build_screening_response(tx, screening_records)
        as_of_date = tx.created_at.date()
        edd_required = False
        for entity in (sender, beneficiary):
            if not entity.sector_classification:
                continue

            resolution = await get_sector_risk_classification(
                entity.sector_classification,
                None,
                None,
                as_of_date,
                self._sector_repo,
            )
            actions = await self._evaluate_rules(
                tx,
                sector_risk_tier=resolution.risk_tier.value,
                classification_label=resolution.classification_label,
            )
            if actions.edd_required:
                edd_required = True
                dnfbp_record = await self._screening_repo.create(
                    ComplianceScreening(
                        transaction_id=transaction_id,
                        screening_type=ScreeningType.DNFBP,
                        status=ScreeningStatus.MANUAL_REVIEW,
                        provider=policies._PROVIDER_MAP[ScreeningType.DNFBP],
                        result_payload={
                            "entity": entity.entity_name,
                            "sector_classification": entity.sector_classification,
                            # Which authority decided this, not merely that it
                            # was decided — the question a compliance officer
                            # asks when a settlement is flagged.
                            "jurisdiction_type": resolution.jurisdiction_type.value
                            if resolution.jurisdiction_type
                            else None,
                            "jurisdiction_value": resolution.jurisdiction_value,
                            "risk_tier": resolution.risk_tier.value,
                            "classification_label": resolution.classification_label,
                            "edd_triggered": True,
                            "rule_ids": list(actions.edd_trigger_rules),
                            "reasons": list(
                                actions.reasons_for(RequiredAction.EDD_REQUIRED)
                            ),
                        },
                    )
                )
                screening_records.append(dnfbp_record)
                await self._case_repo.create(
                    ComplianceCase(
                        transaction_id=transaction_id,
                        case_type=CaseType.DNFBP_EDD,
                    )
                )

        # ── AML risk scoring ──────────────────────────────────────────────────
        # Use the higher risk rating between sender and beneficiary
        from app.modules.customers import RiskRating

        _rating_order = [RiskRating.LOW, RiskRating.MEDIUM, RiskRating.HIGH, RiskRating.ENHANCED]
        higher_rating = max(
            sender.risk_rating,
            beneficiary.risk_rating,
            key=lambda r: _rating_order.index(r),
        )
        amount_actions = await self._evaluate_rules(tx)
        aml_status, aml_payload = policies.score_aml_risk(
            higher_rating,
            int(tx.amount),
            tx.source_currency,
            registry_reasons=amount_actions.reasons_for(RequiredAction.MANUAL_REVIEW),
            registry_rule_ids=amount_actions.rules_for(RequiredAction.MANUAL_REVIEW),
        )
        aml_record = await self._screening_repo.create(
            ComplianceScreening(
                transaction_id=transaction_id,
                screening_type=ScreeningType.AML_RISK,
                status=aml_status,
                provider=policies._PROVIDER_MAP[ScreeningType.AML_RISK],
                result_payload=aml_payload,
            )
        )
        screening_records.append(aml_record)

        # ── Transition to UNDER_REVIEW ────────────────────────────────────────
        tx = await self._transition(
            tx,
            TransactionStatus.UNDER_REVIEW,
            actor_id=actor.id,
            reason="Compliance screening passed; awaiting maker-checker approval",
        )
        await self._audit.record(
            "compliance.screening.completed",
            transaction_id=transaction_id,
            actor_id=actor.id,
            actor_type=ActorType.COMPLIANCE_OFFICER,
            payload={
                "edd_required": edd_required,
                "aml_status": aml_status.value,
                "total_screenings": len(screening_records),
            },
        )
        return self._build_screening_response(tx, screening_records, edd_required=edd_required)

    # ── Maker-Checker Approvals ────────────────────────────────────────────────

    async def submit_approval(
        self, request: SubmitApprovalRequest, approver: User
    ) -> ApprovalSubmittedResponse:
        tx = await self._tx_repo.get_by_transaction_id(request.transaction_id)
        if tx is None:
            raise NotFoundError(f"Transaction {request.transaction_id} not found")

        if tx.status != TransactionStatus.UNDER_REVIEW:
            raise AnerBaseException(
                detail=f"Transaction status is {tx.status.value}; approvals can only be submitted for UNDER_REVIEW transactions",
                error_code="INVALID_STATUS",
                status_code=422,
            )

        existing = await self._approval_repo.list_by_transaction(request.transaction_id)
        if len(existing) >= 2:
            raise AnerBaseException(
                detail="Both MAKER and CHECKER approvals have already been recorded for this transaction",
                error_code="APPROVAL_ALREADY_COMPLETE",
                status_code=409,
            )

        if len(existing) == 0:
            role = ApproverRole.MAKER
        else:
            # CHECKER path — ensure a different person
            maker = existing[0]
            if maker.approver_user_id == approver.id:
                raise AnerBaseException(
                    detail="The same user cannot be both MAKER and CHECKER on the same transaction",
                    error_code="DUPLICATE_APPROVER",
                    status_code=409,
                )
            role = ApproverRole.CHECKER

        try:
            record = await self._approval_repo.create(
                ComplianceApproval(
                    transaction_id=request.transaction_id,
                    approver_role=role,
                    approver_user_id=approver.id,
                    decision=request.decision,
                    notes=request.notes,
                )
            )
        except IntegrityError:
            await self._db.rollback()
            raise AnerBaseException(
                detail="The same user cannot be both MAKER and CHECKER on the same transaction",
                error_code="DUPLICATE_APPROVER",
                status_code=409,
            )

        event_type = f"compliance.{role.value.lower()}.{request.decision.value.lower()}"
        await self._audit.record(
            event_type,
            transaction_id=request.transaction_id,
            actor_id=approver.id,
            actor_type=ActorType.COMPLIANCE_OFFICER,
            payload={
                "role": role.value,
                "decision": request.decision.value,
                "notes": request.notes,
            },
        )

        # ── Status transitions triggered by approval outcome ──────────────────
        if request.decision == ApprovalDecision.REJECTED:
            tx = await self._transition(
                tx,
                TransactionStatus.DECLINED,
                actor_id=approver.id,
                reason=f"{role.value} rejected: {request.notes or 'No reason given'}",
            )
            await self._audit.record(
                "compliance.transaction.declined",
                transaction_id=request.transaction_id,
                actor_id=approver.id,
                actor_type=ActorType.COMPLIANCE_OFFICER,
                payload={"rejected_by_role": role.value},
            )
        elif role == ApproverRole.CHECKER and request.decision == ApprovalDecision.APPROVED:
            tx = await self._transition(
                tx,
                TransactionStatus.APPROVED,
                actor_id=approver.id,
                reason="Maker-checker approval complete",
            )
            await self._audit.record(
                "compliance.transaction.approved",
                transaction_id=request.transaction_id,
                actor_id=approver.id,
                actor_type=ActorType.COMPLIANCE_OFFICER,
                payload={},
            )

            # ── Broadcast: Compliance Approved (aner.compliance.events) ────────
            from app.platform.messaging.producer import EventProducer

            await EventProducer().compliance_approved(
                transaction_id=request.transaction_id,
                approval_id=str(record.id),
                approver_role=role.value,
            )

        # ── Temporal signal (best-effort, never fails the approval) ──────────────
        from app.platform.configuration.config import settings as _settings

        if _settings.TEMPORAL_ENABLED:
            await self._send_approval_signal(
                transaction_id=request.transaction_id,
                role=role,
                decision=request.decision.value,
                approver_id=str(approver.id),
                notes=request.notes or "",
            )

        return ApprovalSubmittedResponse(
            approval_id=record.id,
            approver_role=role,
            decision=request.decision,
            created_at=record.created_at.isoformat(),
        )

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_approvals(self, transaction_id: uuid.UUID) -> ApprovalsStateResponse:
        tx = await self._tx_repo.get_by_transaction_id(transaction_id)
        if tx is None:
            raise NotFoundError(f"Transaction {transaction_id} not found")

        records = await self._approval_repo.list_by_transaction(transaction_id)
        return ApprovalsStateResponse(
            transaction_id=transaction_id,
            transaction_status=tx.status,
            approvals=[
                ApprovalResult(
                    approval_id=r.id,
                    approver_role=r.approver_role,
                    decision=r.decision,
                    notes=r.notes,
                    created_at=r.created_at.isoformat(),
                )
                for r in records
            ],
        )

    async def get_screenings(self, transaction_id: uuid.UUID) -> ScreeningRunResponse:
        tx = await self._tx_repo.get_by_transaction_id(transaction_id)
        if tx is None:
            raise NotFoundError(f"Transaction {transaction_id} not found")

        records = await self._screening_repo.list_by_transaction(transaction_id)
        edd_required = any(r.screening_type == ScreeningType.DNFBP for r in records)
        return self._build_screening_response(tx, list(records), edd_required=edd_required)

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _transition(
        self,
        tx: Transaction,
        to_status: TransactionStatus,
        *,
        actor_id: uuid.UUID | None,
        reason: str,
    ) -> Transaction:
        from_status = tx.status
        tx = await self._tx_repo.update(tx, status=to_status)
        await self._history_repo.create(
            TransactionStatusHistory(
                transaction_id=tx.transaction_id,
                from_status=from_status,
                to_status=to_status,
                actor_id=actor_id,
                reason=reason,
            )
        )
        logger.info(
            "transaction_status_transition",
            transaction_id=str(tx.transaction_id),
            from_status=from_status.value,
            to_status=to_status.value,
        )
        return tx

    async def _send_approval_signal(
        self,
        *,
        transaction_id: uuid.UUID,
        role: ApproverRole,
        decision: str,
        approver_id: str,
        notes: str,
    ) -> None:
        """Send compliance approval signal to the running SettlementWorkflow. Best-effort."""
        try:
            from app.platform.workflow.adapters.client import get_temporal_client
            from app.shared.contracts.signals import ApprovalSignalPayload

            signal_name = (
                "compliance_maker_approved"
                if role == ApproverRole.MAKER
                else "compliance_checker_approved"
            )
            client = await get_temporal_client()
            handle = client.get_workflow_handle(str(transaction_id))
            await handle.signal(
                signal_name,
                ApprovalSignalPayload(
                    decision=decision,
                    approver_id=approver_id,
                    notes=notes,
                ),
            )
            logger.info(
                "temporal_approval_signal_sent",
                transaction_id=str(transaction_id),
                signal=signal_name,
                decision=decision,
            )
        except Exception as exc:
            logger.warning(
                "temporal_approval_signal_failed",
                transaction_id=str(transaction_id),
                error=str(exc),
            )

    @staticmethod
    def _build_screening_response(
        tx: Transaction,
        records: list[ComplianceScreening],
        edd_required: bool = False,
    ) -> ScreeningRunResponse:
        return ScreeningRunResponse(
            transaction_id=tx.transaction_id,
            transaction_status=tx.status,
            edd_required=edd_required,
            screenings=[
                ScreeningResult(
                    screening_id=r.id,
                    screening_type=r.screening_type,
                    status=r.status,
                    provider=r.provider,
                    result_payload=r.result_payload,
                    created_at=r.created_at.isoformat(),
                )
                for r in records
            ],
        )
