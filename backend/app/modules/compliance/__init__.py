"""Compliance — public facade."""

from app.modules.compliance.application.compliance_rule_service import (
    evaluate_settlement_compliance,
)
from app.modules.compliance.application.rule_engine import ComplianceActionSet, FiredAction
from app.modules.compliance.application.sector_risk_service import is_sector_code_known
from app.modules.compliance.application.services import ComplianceService
from app.modules.compliance.application.settlement_assessment import (
    evaluate_compliance_rules,
)
from app.modules.compliance.application.validation import (
    ExternalPurposeCodeResolution,
    validate_purpose_code,
)
from app.modules.compliance.domain.entities.compliance import (
    ApprovalDecision,
    ApproverRole,
    CaseType,
    ComplianceApproval,
    ComplianceCase,
)
from app.modules.compliance.domain.entities.sector_registry import RiskTier
from app.modules.compliance.domain.jurisdiction import (
    JurisdictionType,
    ResolvingJurisdiction,
)
from app.modules.compliance.domain.policies.rule_matching import ComplianceFacts
from app.modules.compliance.domain.ports import (
    ComplianceAuditSink,
    ComplianceRuleRepository,
    IndicativeRateProvider,
    ResolvedSectorClassification,
    SectorClassificationLookup,
)
from app.modules.compliance.domain.required_action import RequiredAction
from app.modules.compliance.exceptions import (
    AmbiguousPurposeCodeMappingError,
    PurposeCodeError,
    PurposeCodeInputError,
    PurposeCodeNotEffectiveError,
    PurposeCodeNotFoundError,
    PurposeCodeNotValidForCorridorError,
)
from app.modules.compliance.infrastructure.compliance_rule_repository import (
    SQLAlchemyComplianceRuleRepository,
)
from app.modules.compliance.infrastructure.purpose_code_repository import (
    SQLAlchemyPurposeCodeRepository,
)
from app.modules.compliance.infrastructure.repository import ApprovalRepository, CaseRepository
from app.modules.compliance.infrastructure.sector_risk_repository import (
    SQLAlchemySectorRiskRepository,
)

__all__ = [
    "AmbiguousPurposeCodeMappingError",
    "ApprovalDecision",
    "ApprovalRepository",
    "ApproverRole",
    "CaseRepository",
    "CaseType",
    "ComplianceActionSet",
    "ComplianceApproval",
    "ComplianceAuditSink",
    "ComplianceCase",
    "ComplianceFacts",
    "ComplianceRuleRepository",
    "ComplianceService",
    "ExternalPurposeCodeResolution",
    "FiredAction",
    "IndicativeRateProvider",
    "JurisdictionType",
    "PurposeCodeError",
    "PurposeCodeInputError",
    "PurposeCodeNotEffectiveError",
    "PurposeCodeNotFoundError",
    "PurposeCodeNotValidForCorridorError",
    "RequiredAction",
    "ResolvedSectorClassification",
    "ResolvingJurisdiction",
    "RiskTier",
    "SQLAlchemyComplianceRuleRepository",
    "SQLAlchemyPurposeCodeRepository",
    "SQLAlchemySectorRiskRepository",
    "SectorClassificationLookup",
    "evaluate_compliance_rules",
    "evaluate_settlement_compliance",
    "is_sector_code_known",
    "validate_purpose_code",
]
