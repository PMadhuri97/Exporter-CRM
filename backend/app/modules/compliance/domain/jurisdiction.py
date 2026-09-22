"""Which regulatory authority a sector classification comes from.

Two values, not one. ``FATF`` and ``US_IN`` are both jurisdictions in the loose
sense, but one is an international framework and the other a corridor, and the
difference decides which of them wins when both classify the same sector. A
single string would carry the name and lose the precedence level — leaving a
compliance officer told that "US_IN" drove a decision without being told that a
corridor rule outranked the framework's.

Free of infrastructure so the pure evaluator can carry the resolved value into
its result. See ``domain.required_action`` for the same reasoning.
"""

import enum
from dataclasses import dataclass


class JurisdictionType(str, enum.Enum):
    """The precedence ladder S0T2 resolves against, most specific last.

    Declared in increasing order of specificity, which is the order a resolver
    must prefer them in reverse: a corridor classification beats a country's,
    and a country's beats the framework baseline.
    """

    FRAMEWORK = "framework"
    COUNTRY = "country"
    CORRIDOR = "corridor"


@dataclass(frozen=True)
class ResolvingJurisdiction:
    """The authority whose classification actually governed a sector.

    Returned rather than inferred. When a settlement is flagged for enhanced due
    diligence, "which jurisdiction said so" is part of the answer, and no caller
    can reconstruct it from the tier and label alone.
    """

    type: JurisdictionType
    value: str

    def __str__(self) -> str:
        return f"{self.type.value}:{self.value}"
