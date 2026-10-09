"""Answering a qualification criterion automatically.

An administrator may give a criterion an **auto source** — where its answer can be read
from. Each source fits one kind of criterion:

| Source | Kind | Rule |
|---|---|---|
| ``IEC_VERIFICATION`` | yes/no | Pass if a passed IEC verification exists |
| ``YEARS_ESTABLISHED`` | number | Years since ``year_established``, or the incorporation year in the CIN |
| ``INDUSTRY`` | allowed values | The company's industry is one of them |
| ``EXPORT_MARKETS`` | allowed values | Any of the company's export markets is one of them |
| ``TRADE_HISTORY`` | yes/no | Pass if at least one export is recorded |
| ``DEAL_VALUE`` | number | The largest deal value (in the criterion's unit, when that is a currency) |

These functions only judge; they never decide that nothing is known. ``None`` means
"no answer to give" — the evaluator then writes nothing, rather than an Unknown.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable
from decimal import Decimal

from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    ThresholdComparison,
)


class AutoSource(str, enum.Enum):
    IEC_VERIFICATION = "IEC_VERIFICATION"
    YEARS_ESTABLISHED = "YEARS_ESTABLISHED"
    INDUSTRY = "INDUSTRY"
    EXPORT_MARKETS = "EXPORT_MARKETS"
    TRADE_HISTORY = "TRADE_HISTORY"
    DEAL_VALUE = "DEAL_VALUE"


#: The kind of criterion each source can answer.
SOURCE_KIND: dict[AutoSource, CriterionKind] = {
    AutoSource.IEC_VERIFICATION: CriterionKind.YES_NO,
    AutoSource.YEARS_ESTABLISHED: CriterionKind.NUMBER_THRESHOLD,
    AutoSource.INDUSTRY: CriterionKind.ALLOWED_VALUES,
    AutoSource.EXPORT_MARKETS: CriterionKind.ALLOWED_VALUES,
    AutoSource.TRADE_HISTORY: CriterionKind.YES_NO,
    AutoSource.DEAL_VALUE: CriterionKind.NUMBER_THRESHOLD,
}

#: The sources a recorded verification can change. Re-answering one whose verification
#: did not change writes nothing (the same answer is never written twice).
VERIFICATION_SOURCES: frozenset[AutoSource] = frozenset({AutoSource.IEC_VERIFICATION})

#: What each source is called where a person reads a result: "Auto · IEC check".
SOURCE_LABEL: dict[AutoSource, str] = {
    AutoSource.IEC_VERIFICATION: "IEC check",
    AutoSource.YEARS_ESTABLISHED: "Year established",
    AutoSource.INDUSTRY: "Company industry",
    AutoSource.EXPORT_MARKETS: "Export markets",
    AutoSource.TRADE_HISTORY: "Trade history",
    AutoSource.DEAL_VALUE: "Deal value",
}

#: A CIN: L/U, five industry digits, a state, the **incorporation year**, a type, a number.
_CIN = re.compile(r"^[LU]\d{5}[A-Z]{2}(\d{4})[A-Z]{3}\d{6}$")


def incorporation_year(cin: str | None) -> int | None:
    match = _CIN.match((cin or "").strip().upper())
    return int(match.group(1)) if match else None


def threshold_result(
    value: Decimal | int | None, comparison: ThresholdComparison | None, threshold: Decimal | None
) -> CriterionResultValue | None:
    if value is None or comparison is None or threshold is None:
        return None
    ok = Decimal(value) >= threshold if comparison is ThresholdComparison.AT_LEAST else Decimal(value) <= threshold
    return CriterionResultValue.PASS if ok else CriterionResultValue.FAIL


def allowed_result(
    values: Iterable[str | None], allowed: Iterable[str] | None
) -> CriterionResultValue | None:
    """PASS when any value is allowed (case and spacing ignored); ``None`` when there is
    nothing to compare."""
    given = [" ".join(v.lower().split()) for v in values if v and v.strip()]
    if not given or not allowed:
        return None
    permitted = {" ".join(a.lower().split()) for a in allowed}
    return CriterionResultValue.PASS if any(v in permitted for v in given) else CriterionResultValue.FAIL


__all__ = [
    "SOURCE_KIND",
    "SOURCE_LABEL",
    "VERIFICATION_SOURCES",
    "AutoSource",
    "allowed_result",
    "incorporation_year",
    "threshold_result",
]
