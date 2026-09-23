"""cases — public facade.

ANER-4.3-S1T1 (schema), S1T2 (SLA configuration and deadline calculation),
S2/S2T2 (the `ONBOARDING_INTAKE` -> `ONBOARDING_REVIEW` case_type transition
and Epic-4-only evidence aggregation of RXIL's own outputs), and now
S3T1/S3T2/S3T3/S4T2 are implemented: case assignment, the general
`case_status` lifecycle transition graph, case notes, and an onboarding-review
maker-checker resolution stand-in (`CaseLifecycleService`, `CaseNoteService`
— see `application/case_lifecycle_service.py`'s module docstring for the
maker-checker disclaimer and the exact transition table implemented). Out of
scope and deliberately absent: the case creation event consumer (S2T1), team
/queue routing (S3T1's routing-config half — see `CaseLifecycleService.
assign_case`'s docstring), case-type-specific resolution workflows for
anything other than `onboarding_review` (S4T1/S4T3/S4T4), SLA monitoring and
auto-escalation (S5T2), query interfaces (S5T1/S6T1), and any cross-epic
evidence pulls (Epics 2.x/3.x/5.x). There is no `api/` package and this
module is not wired into `app/api/rest/router.py` or `app/bootstrap.py`'s
event-consumer registration.
"""
from app.modules.cases.application.case_lifecycle_service import (
    MIN_SUBSTANTIVE_NOTE_LENGTH,
    CaseLifecycleService,
)
from app.modules.cases.application.case_note_service import MAX_NOTE_LENGTH, CaseNoteService
from app.modules.cases.application.case_query_service import (
    CaseDetail,
    CaseQueryService,
    EvidenceItemView,
)
from app.modules.cases.application.case_transition_service import CaseTransitionService
from app.modules.cases.application.evidence_aggregation_service import (
    EvidenceAggregationService,
)
from app.modules.cases.application.sla_service import SlaCalculationService, SlaTarget
from app.modules.cases.config import REQUIRE_TWO_PERSON_RESOLUTION
from app.modules.cases.domain.entities.case_evidence_item import CaseEvidenceItem
from app.modules.cases.domain.entities.case_timeline_event import CaseTimelineEvent
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import (
    TERMINAL_CASE_STATUSES,
    ActorType,
    CaseSeverity,
    CaseStatus,
    CaseType,
    EvidenceType,
    ResolutionAction,
    TimelineEventType,
)
from app.modules.cases.infrastructure.sla_config_loader import build_sla_calculation_service

# Re-exported for the onboarding module's case bridge (onboarding/application/
# case_bridge_service.py) — the first caller outside this module. No logic
# lives here; the import-linter contract `cases-internals-are-private` allows
# other modules this facade and nothing below it.
__all__ = [
    "MAX_NOTE_LENGTH",
    "MIN_SUBSTANTIVE_NOTE_LENGTH",
    "REQUIRE_TWO_PERSON_RESOLUTION",
    "TERMINAL_CASE_STATUSES",
    "ActorType",
    "CaseDetail",
    "CaseEvidenceItem",
    "CaseLifecycleService",
    "CaseNoteService",
    "CaseQueryService",
    "CaseSeverity",
    "CaseStatus",
    "CaseTimelineEvent",
    "CaseTransitionService",
    "CaseType",
    "ComplianceCase",
    "EvidenceAggregationService",
    "EvidenceItemView",
    "EvidenceType",
    "ResolutionAction",
    "SlaCalculationService",
    "SlaTarget",
    "TimelineEventType",
    "build_sla_calculation_service",
]
