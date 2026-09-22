"""Enumerations for the compliance case management schema (Epic 4.3).

Every enum here is deliberately its own type, scoped to the `cases` schema, even
where the label set overlaps something that already exists elsewhere:

- `compliance.compliance_cases` (see `app/modules/compliance/domain/entities/
  compliance.py`) already defines a `CaseType` and a `CaseStatus`. That table is
  a narrower, older mechanism — `AppendOnlyModel`, keyed only to
  `payments.transactions`, with three statuses and no assignment, SLA, or
  resolution model. It cannot represent an onboarding review, a reconciliation
  break, or a webhook delivery failure, which is exactly the gap Epic 4.3
  closes. The two `CaseType` / `CaseStatus` pairs are unrelated vocabularies
  that happen to share a name; they are not variants of one enum and must not
  be merged or cross-referenced. Anyone importing `CaseType` needs to import it
  from the right module — `app.modules.cases` for a Case Management Console
  case, `app.modules.compliance` for a transaction-screening case.
- `CaseSeverity`'s members match `customers.review_trigger_severity_enum`
  (CRITICAL/HIGH/MEDIUM/LOW) letter for letter. Reusing that type would let this
  schema's severity column silently depend on a migration owned by another
  module; each schema owns its own copy of a ladder this generic, following the
  precedent `customers_0002_review_lifecycle` sets for `review_risk_rating_enum`
  vs. the onboarding-era `risk_rating_enum`.
- `ActorType` here is CASE-context (compliance officer / operations officer /
  system / external approver), distinct from `audit.actor_type_enum` (system /
  compliance officer / API client) — different membership, so it cannot be the
  same type.
"""
import enum


class CaseType(str, enum.Enum):
    SCREENING_REVIEW = "SCREENING_REVIEW"
    TRANSACTION_FLAG = "TRANSACTION_FLAG"
    RECONCILIATION_BREAK = "RECONCILIATION_BREAK"
    RECONCILIATION_TIMEOUT = "RECONCILIATION_TIMEOUT"
    # A case exists because RXIL data has arrived but required documents/checks
    # aren't all in yet — a holding state, not yet reviewable. Added in
    # cases_0002_intake_type (ANER-4.3-S2). Excluded from the
    # SLA policy for the same reason MANUAL is (see EXPECTED_CASE_TYPES in
    # infrastructure/sla_config_loader.py) and carries no `sla_deadline` until
    # it transitions to ONBOARDING_REVIEW —
    # application/case_transition_service.py's `transition_case_to_review` is
    # the only way that happens, exactly once per case.
    ONBOARDING_INTAKE = "ONBOARDING_INTAKE"
    ONBOARDING_REVIEW = "ONBOARDING_REVIEW"
    TRAVEL_RULE_REVIEW = "TRAVEL_RULE_REVIEW"
    ON_CHAIN_ESCALATION = "ON_CHAIN_ESCALATION"
    WEBHOOK_DELIVERY_FAILURE = "WEBHOOK_DELIVERY_FAILURE"
    MANUAL = "MANUAL"


class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    PENDING_EXTERNAL = "PENDING_EXTERNAL"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    CLOSED_WITHOUT_ACTION = "CLOSED_WITHOUT_ACTION"


#: Statuses from which a case never reopens on its own. `is_sla_breached`
#: (application/sla_service.py) treats a case in either status as permanently
#: not breaching, regardless of how far past `sla_deadline` it is.
TERMINAL_CASE_STATUSES = frozenset({CaseStatus.RESOLVED, CaseStatus.CLOSED_WITHOUT_ACTION})


class CaseSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ResolutionAction(str, enum.Enum):
    APPROVE_TRANSACTION = "APPROVE_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    APPROVE_ONBOARDING = "APPROVE_ONBOARDING"
    REJECT_ONBOARDING = "REJECT_ONBOARDING"
    APPROVE_RECALL = "APPROVE_RECALL"
    MANUAL_RESOLUTION = "MANUAL_RESOLUTION"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"


class TimelineEventType(str, enum.Enum):
    CASE_CREATED = "CASE_CREATED"
    ASSIGNED = "ASSIGNED"
    STATUS_CHANGED = "STATUS_CHANGED"
    NOTE_ADDED = "NOTE_ADDED"
    EVIDENCE_UPDATED = "EVIDENCE_UPDATED"
    ESCALATED = "ESCALATED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RECEIVED = "APPROVAL_RECEIVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ActorType(str, enum.Enum):
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    OPERATIONS_OFFICER = "OPERATIONS_OFFICER"
    SYSTEM = "SYSTEM"
    EXTERNAL_APPROVER = "EXTERNAL_APPROVER"


class EvidenceType(str, enum.Enum):
    SCREENING_RESULT = "SCREENING_RESULT"
    KYB_RESULT = "KYB_RESULT"
    ONBOARDING_EVIDENCE = "ONBOARDING_EVIDENCE"
    DECISIONING_RESULT = "DECISIONING_RESULT"
    LIMITS_CHECK = "LIMITS_CHECK"
    FX_RATE_DATA = "FX_RATE_DATA"
    RECONCILIATION_DATA = "RECONCILIATION_DATA"
    TRAVEL_RULE_DATA = "TRAVEL_RULE_DATA"
    ON_CHAIN_ASSESSMENT = "ON_CHAIN_ASSESSMENT"
    REACTOR_INVESTIGATION = "REACTOR_INVESTIGATION"
    SETTLEMENT_RECORD = "SETTLEMENT_RECORD"
    MANUAL_ATTACHMENT = "MANUAL_ATTACHMENT"
    # Five RXIL-specific artifacts added in
    # cases_0004_rxil_evidence (ANER-4.3-S2T2, Epic-4-only slice). RXIL's
    # own KYC and AML/CFT screening outputs are recorded under the existing
    # KYB_RESULT / SCREENING_RESULT values above — they already fit and get no
    # new value here. These five cover artifacts RXIL produces that have no
    # existing home: invoice-duplication-financing checks, vessel tracking,
    # MLETR electronic bills of lading, buyer credit ratings, and insurance
    # certificates.
    DUPLICATION_CHECK = "DUPLICATION_CHECK"
    VESSEL_TRACKING = "VESSEL_TRACKING"
    BILL_OF_LADING = "BILL_OF_LADING"
    BUYER_RATING = "BUYER_RATING"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"


#: `evidence_data` on these evidence types carries personal data (identity
#: documents, screening hits, KYB registry extracts, travel-rule originator/
#: beneficiary details, Reactor wallet-attribution findings) and is documented
#: as "encrypted at rest" per Epic 4.3's spec. See
#: `case_evidence_item.py::CaseEvidenceItem.evidence_data` for the same gap this
#: repository already carries on `onboarding_request.tax_identification_number`
#: and `kyb_vendor_result.raw_vendor_response`: no field-level encryption layer
#: or KMS provider exists in the platform yet, so this is a documented
#: convention, not an enforced one.
#:
#: Of the five RXIL-specific additions (DUPLICATION_CHECK, VESSEL_TRACKING,
#: BILL_OF_LADING, BUYER_RATING, INSURANCE_CERTIFICATE), only BUYER_RATING and
#: INSURANCE_CERTIFICATE are included here: a buyer credit-rating report or an
#: insurance certificate plausibly names individuals (directors, signatories,
#: named insureds/beneficiaries), the same class of risk as a KYB registry
#: extract. DUPLICATION_CHECK (an invoice-number/amount integrity check),
#: VESSEL_TRACKING (AIS/GPS logistics data) and BILL_OF_LADING (a shipping
#: document identifying cargo and corporate shipper/consignee, not a natural
#: person) are not: they are commercial/logistics artifacts with no natural
#: person as their subject.
PII_BEARING_EVIDENCE_TYPES = frozenset({
    EvidenceType.SCREENING_RESULT,
    EvidenceType.KYB_RESULT,
    EvidenceType.ONBOARDING_EVIDENCE,
    EvidenceType.TRAVEL_RULE_DATA,
    EvidenceType.REACTOR_INVESTIGATION,
    EvidenceType.BUYER_RATING,
    EvidenceType.INSURANCE_CERTIFICATE,
})
