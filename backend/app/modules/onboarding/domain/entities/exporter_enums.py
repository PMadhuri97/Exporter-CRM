"""Enums for the company record (EXP-1): ``ExporterProfile`` — **owner:
Developer 2** (architecture §8.1, §9.2).

The activity-log enum (``ExporterActivityType``) used to live here too; L2-01
moved it to ``engagement_enums.py``, which Developer 3 owns.

Kept in their own file rather than added to ``orchestration_enums.py`` or the
legacy ``enums.py``: none of these concepts belong to a single verification
journey (``OnboardingRequestStatus``'s domain) or to the pre-Epic-4.1 case/KYC
design (``enums.py``'s domain) — they describe the enduring exporter
relationship those journeys attach to. See ``exporter_profile.py``'s module
docstring for why ``ExporterLifecycleStatus`` is a genuinely separate state
machine from ``OnboardingRequestStatus``, not a superset or a rename.
"""

import enum


class ExporterSource(str, enum.Enum):
    """How this exporter relationship originated. Immutable once set on
    ``ExporterProfile.source`` (both a service-layer guard and a DB trigger —
    see the migration and ``exceptions.ExporterSourceAlreadySetError``): this
    is an audit-relevant fact about how the relationship began, the same
    reasoning ``ComplianceCase.resolved_by`` is guarded for.
    """

    MANUAL = "MANUAL"
    SALES = "SALES"
    REFERRAL = "REFERRAL"
    RXIL = "RXIL"
    PARTNER = "PARTNER"
    API = "API"
    BROKER = "BROKER"
    EVENT = "EVENT"
    EXISTING_CUSTOMER = "EXISTING_CUSTOMER"


class ExporterLifecycleStatus(str, enum.Enum):
    """The exporter *relationship's* lifecycle — deliberately separate from
    ``OnboardingRequestStatus``, which tracks a single verification pass. A
    customer can be ``ACTIVE`` here across many historical
    ``OnboardingRequest`` rows (re-verification, renewed KYB, a second
    financing product), each of which runs its own ``OnboardingRequestStatus``
    from ``DRAFT`` to a terminal state independently of where this status sits.
    """

    LEAD = "LEAD"
    CONTACTED = "CONTACTED"
    DATA_COLLECTION = "DATA_COLLECTION"
    VERIFICATION_IN_PROGRESS = "VERIFICATION_IN_PROGRESS"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    ONBOARDED = "ONBOARDED"
    FINANCING_ELIGIBLE = "FINANCING_ELIGIBLE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"
