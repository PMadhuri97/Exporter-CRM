"""Enums for the company record (EXP-1): ``ExporterProfile`` — **owner:
Developer 2** (architecture §8.1, §9.2).

The activity-log enum (``ExporterActivityType``) used to live here too; L2-01
moved it to ``engagement_enums.py``, which Developer 3 owns.

Kept in their own file rather than added to ``orchestration_enums.py`` or the
legacy ``enums.py``: none of these concepts belong to a single verification
journey (``OnboardingRequestStatus``'s domain) or to the pre-Epic-4.1 case/KYC
design (``enums.py``'s domain) — they describe the enduring exporter
relationship those journeys attach to.

The old ten-status ``ExporterLifecycleStatus`` was retired in L2-04 (migration
0020): the journey is ``ExporterJourney``, beside the qualification gauge and
the ``ExporterMarker``. Its values survive as strings in the history log.
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


class ExporterMarker(str, enum.Enum):
    """A commercial pause or ending, kept apart from the journey (decision 3,
    ``docs/contracts/company-record.md`` §3.3). Not a lifecycle stage, and not
    a compliance hold: a compliance concern belongs on the background check.
    ``PAUSED`` and ``ENDED`` always carry a reason."""

    NONE = "NONE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class ExporterJourney(str, enum.Enum):
    """The company's main journey (architecture §3.2): forward only, and never
    moved by hand — each move follows from a qualification outcome or a
    background-check decision (``docs/contracts/company-record.md`` §3.1).

    Added in migration 0017; the ten-status ``ExporterLifecycleStatus`` it
    replaces was retired in L2-04 (migration 0020)."""

    LEAD = "LEAD"
    PROSPECT = "PROSPECT"
    CUSTOMER = "CUSTOMER"
