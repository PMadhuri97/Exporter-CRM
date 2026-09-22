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
from app.modules.cases.application.case_lifecycle_service import CaseLifecycleService
from app.modules.cases.application.case_note_service import CaseNoteService
from app.modules.cases.application.case_transition_service import CaseTransitionService
from app.modules.cases.application.evidence_aggregation_service import (
    EvidenceAggregationService,
)
from app.modules.cases.application.sla_service import SlaCalculationService, SlaTarget
from app.modules.cases.domain.entities.enums import (
    CaseSeverity,
    CaseStatus,
    CaseType,
    EvidenceType,
)

__all__ = [
    "CaseLifecycleService",
    "CaseNoteService",
    "CaseSeverity",
    "CaseStatus",
    "CaseTransitionService",
    "CaseType",
    "EvidenceAggregationService",
    "EvidenceType",
    "SlaCalculationService",
    "SlaTarget",
]
