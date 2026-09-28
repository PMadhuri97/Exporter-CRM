"""Enums for qualification — **owner: Developer 2** (L2-09, L2-10,
``docs/contracts/criterion-result.md``).

Qualification is its own gauge. None of these values is shared with the
screening checklist (``NEEDS_REVIEW``/``PASSED``/``FAILED``/``EXEMPT``) or the
background check: the sets are deliberately different so a value can never be
read as belonging to the other list (contract §1).
"""

import enum


class QualificationState(str, enum.Enum):
    """The company's qualification gauge (contract §4)."""

    NOT_YET_REVIEWED = "NOT_YET_REVIEWED"
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class QualificationOutcomeValue(str, enum.Enum):
    """What a reviewer decides. ``NOT_YET_REVIEWED`` is never decided: it is
    only the gauge's value before the first decision."""

    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class CriterionKind(str, enum.Enum):
    NUMBER_THRESHOLD = "NUMBER_THRESHOLD"
    YES_NO = "YES_NO"
    ALLOWED_VALUES = "ALLOWED_VALUES"


class ThresholdComparison(str, enum.Enum):
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


class CriterionResultValue(str, enum.Enum):
    """``UNKNOWN`` means "could not establish", not "not yet looked at"."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class QualificationSource(str, enum.Enum):
    """Where a result or outcome came from."""

    MANUAL = "MANUAL"
    IMPORT = "IMPORT"
    RXIL = "RXIL"
    AUTOMATED = "AUTOMATED"


class DecidedByKind(str, enum.Enum):
    """Whether a person or a computer decided (architecture §2.6: manual
    first, automation later, and every decision records which)."""

    MANUAL = "MANUAL"
    AUTOMATED = "AUTOMATED"
