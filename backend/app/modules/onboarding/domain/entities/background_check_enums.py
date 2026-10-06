"""The background check's vocabularies.

Each Python enum maps to one Postgres type created by ``onboarding_0015_bg_check``,
and the values are ``docs/contracts/background-check.md``'s. Pure: no I/O, no model.
"""

from __future__ import annotations

import enum


class BackgroundCheckState(str, enum.Enum):
    """The gauge: "is it safe and lawful to work with them?" (architecture §3.3).

    ``onboarding.background_check_enum``. Carried on ``exporter_profile.background_check``
    and on every decision's ``from_value`` / ``to_value``. The only legal moves between
    these are the nine in the contract's §3, enforced by the service and by
    ``ck_background_check_decision_move``.
    """

    NOT_STARTED = "NOT_STARTED"
    IN_REVIEW = "IN_REVIEW"
    CLEAR = "CLEAR"
    MORE_INFO = "MORE_INFO"
    FLAGGED = "FLAGGED"
    ON_HOLD = "ON_HOLD"


class BackgroundCheckRisk(str, enum.Enum):
    """The CRM risk scale (decision 6), set by compliance on a decision.

    ``onboarding.background_check_risk_enum`` — a type the background check owns
    (settled 28 Sep 2026). It is deliberately **not** ``VerificationRiskLevel`` /
    ``verification_risk_level_enum``, which belongs to verification, so neither
    migration depends on the other's schema. "Prohibited" is not a risk; it is
    ``FLAGGED``.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BackgroundCheckDecidedByKind(str, enum.Enum):
    """Whether a person or the platform made a decision — ``criterion-result.md``'s words.

    ``onboarding.background_check_decided_by_kind_enum``. Always ``MANUAL`` in the
    prototype: the only automatic move (the start on RXIL results) is blocked on the
    RXIL results contract.
    """

    MANUAL = "MANUAL"
    AUTOMATED = "AUTOMATED"


class BackgroundCheckDecisionSource(str, enum.Enum):
    """Where a decision came from. ``onboarding.background_check_decision_source_enum``.

    ``RXIL`` is reserved for the blocked RXIL results intake and nothing writes it.
    """

    MANUAL = "MANUAL"
    RXIL = "RXIL"


class BackgroundCheckEvidenceKind(str, enum.Enum):
    """What one evidence-snapshot row pins. ``onboarding.background_check_evidence_kind_enum``.

    Each kind sets exactly its own id column (``ck_background_check_evidence_kind``).
    """

    DOCUMENT = "DOCUMENT"
    VERIFICATION_RESULT = "VERIFICATION_RESULT"
    SCREENING_ITEM = "SCREENING_ITEM"


__all__ = [
    "BackgroundCheckDecidedByKind",
    "BackgroundCheckDecisionSource",
    "BackgroundCheckEvidenceKind",
    "BackgroundCheckRisk",
    "BackgroundCheckState",
]
