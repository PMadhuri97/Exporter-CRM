"""Enumerations for the ongoing-due-diligence lifecycle.

`RiskRating` in `customers.py` is the onboarding-era rating and carries
`ENHANCED`; the periodic-review programme rates on a different ladder whose top
band is `PROHIBITED`. They are distinct types with distinct members, so the
review ladder gets its own enum and its own Postgres type rather than widening
one shared type into a superset that lets either context store a value the other
cannot act on.
"""
import enum


class ReviewRiskRating(str, enum.Enum):
    """Risk band that drives review cadence."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class ScheduleStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    SUSPENDED_PENDING_OFFBOARDING = "SUSPENDED_PENDING_OFFBOARDING"


class TriggerSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewAction(str, enum.Enum):
    IMMEDIATE_REVIEW = "IMMEDIATE_REVIEW"
    ACCELERATE_SCHEDULE = "ACCELERATE_SCHEDULE"
    FLAG_AT_NEXT_REVIEW = "FLAG_AT_NEXT_REVIEW"
    NO_ACTION = "NO_ACTION"


class RestrictionLevel(str, enum.Enum):
    """Graduated restriction ladder, ordered least to most restrictive.

    The binary of full access or full suspension is too blunt for a customer who
    is actively moving money: interrupting a live relationship has commercial
    cost, so the level chosen is the least that contains the concern.

    The bands are provisional pending the restriction story that consumes them;
    a band added later is an enum value addition, not a data migration.
    """

    MONITORING_ONLY = "MONITORING_ONLY"
    NEW_CORRIDOR_BLOCKED = "NEW_CORRIDOR_BLOCKED"
    LIMIT_REDUCED = "LIMIT_REDUCED"
    OUTBOUND_BLOCKED = "OUTBOUND_BLOCKED"
    FULL_BLOCK = "FULL_BLOCK"


class ReviewType(str, enum.Enum):
    PERIODIC = "PERIODIC"
    EVENT_TRIGGERED = "EVENT_TRIGGERED"
    AD_HOC = "AD_HOC"
    REMEDIATION_FOLLOWUP = "REMEDIATION_FOLLOWUP"


class ReviewStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    VERIFICATION_RUNNING = "VERIFICATION_RUNNING"
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewOutcome(str, enum.Enum):
    NO_CHANGE = "NO_CHANGE"
    RATING_CHANGED = "RATING_CHANGED"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    REFERRED_TO_OFFBOARDING = "REFERRED_TO_OFFBOARDING"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"


class SnapshotReason(str, enum.Enum):
    ONBOARDING_COMPLETED = "ONBOARDING_COMPLETED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    REMEDIATION_COMPLETED = "REMEDIATION_COMPLETED"
    MANUAL_CAPTURE = "MANUAL_CAPTURE"


class ChangeType(str, enum.Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    # A review that confirms nothing changed is a positive finding. Without this
    # member a record cannot distinguish "checked, all well" from "not checked".
    UNCHANGED_BUT_REVERIFIED = "UNCHANGED_BUT_REVERIFIED"


class Materiality(str, enum.Enum):
    MATERIAL = "MATERIAL"
    NOTABLE = "NOTABLE"
    IMMATERIAL = "IMMATERIAL"


class CustomerStatus(str, enum.Enum):
    """A customer's standing, and therefore what they may do.

    `RESTRICTED` is graduated — see `RestrictionLevel`. The pair exists because a
    review that concludes a customer should be restricted, with no mechanism to
    restrict them, has achieved nothing.
    """

    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    PENDING_OFFBOARDING = "PENDING_OFFBOARDING"
    OFFBOARDED = "OFFBOARDED"


class EntitlementType(str, enum.Enum):
    CORRIDOR_ACCESS = "CORRIDOR_ACCESS"
    TRANSACTION_LIMIT = "TRANSACTION_LIMIT"
    AGGREGATE_LIMIT = "AGGREGATE_LIMIT"
    PRODUCT_ACCESS = "PRODUCT_ACCESS"
    ASSET_ACCESS = "ASSET_ACCESS"


class LimitPeriod(str, enum.Enum):
    PER_TRANSACTION = "PER_TRANSACTION"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class EntitlementSource(str, enum.Enum):
    ONBOARDING = "ONBOARDING"
    REVIEW_OUTCOME = "REVIEW_OUTCOME"
    MANUAL_GRANT = "MANUAL_GRANT"
    RESTRICTION_APPLIED = "RESTRICTION_APPLIED"


class AttestationStatus(str, enum.Enum):
    PENDING = "PENDING"
    PARTIALLY_RESPONDED = "PARTIALLY_RESPONDED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
