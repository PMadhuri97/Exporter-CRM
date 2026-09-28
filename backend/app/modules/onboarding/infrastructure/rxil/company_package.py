"""RXIL company package -> the CRM's ``PartnerCompanyIntake`` (L2-12).
**Owner: Developer 2. The format is provisional.**

RXIL's integration specification has not been published (architecture §11:
"Awaited. Intake built as provisional."), so this file is the **only** place
that knows what an RXIL package looks like. When the real format arrives, this
file changes — the field names, ``_CRITERION_KEYS`` and ``_RESULT_VALUES`` —
and nothing past ``parse_rxil_company_package`` does: company identity,
matching, qualification and the journey are the CRM's, applied by
``PartnerIntakeService``.

It parses the company half of a package only. RXIL's own check results (KYC,
AML/CFT, invoice duplication, vessel tracking, …) belong to the background
check — Developer 4's RXIL results intake (L4-10) — and are not read here.

The provisional package, as JSON::

    {
      "package_id": "RXIL-2026-000123",            # optional; makes a repeat a no-op
      "exporter": {
        "legal_name": "…", "country": "IN",         # required
        "pan": "…", "gstins": ["…"], "iec": "…", "cin": "…",
        "industry": "…", "website": "…"
      },
      "qualification": {
        "decision": "QUALIFIED",                    # required; RXIL only sends qualified exporters
        "method": "MANUAL" | "AUTOMATED",           # optional, default MANUAL
        "note": "…",
        "criteria": [                               # optional
          {"criterion": "revenue", "result": "PASS", "value": "…",
           "evidence": "…", "evidence_refs": [{"type": "document", "ref": "…"}],
           "reason": "…", "confidence": 0.92, "method": "AUTOMATED"}
        ]
      }
    }

**Nothing is recomputed**: each criterion result is carried over exactly as
given — result, value, evidence, reason, confidence, method. Only where RXIL
gives a ``PASS``/``FAIL`` with no evidence at all does the result get an
evidence note saying so, because the CRM refuses an unevidenced ``PASS``/``FAIL``
and the honest evidence is "RXIL said so".

**Never trusted from a package:** who recorded or decided anything, and
ownership. The actor is the signed-in user who submits the package; any such
field in the payload is simply not read.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.onboarding.domain.company_intake import (
    PartnerCompanyIntake,
    PartnerQualification,
    check_identity,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionResultValue,
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
)
from app.modules.onboarding.domain.qualification_views import EvidenceRef, ResultEntry
from app.modules.onboarding.exceptions import PartnerPackageInvalidError

PARTNER = "RXIL"

#: RXIL criterion names -> the CRM's criterion keys. Identity for now; the
#: place to map RXIL's names once its specification is known.
_CRITERION_KEYS: dict[str, str] = {
    key: key
    for key in (
        "revenue", "years_in_business", "export_history", "export_licence",
        "industry", "geography", "deal_size",
    )
}

#: RXIL result values -> the CRM's.
_RESULT_VALUES: dict[str, CriterionResultValue] = {
    "PASS": CriterionResultValue.PASS,
    "FAIL": CriterionResultValue.FAIL,
    "UNKNOWN": CriterionResultValue.UNKNOWN,
}
_DECISIONS: dict[str, QualificationOutcomeValue] = {
    "QUALIFIED": QualificationOutcomeValue.QUALIFIED,
    "NOT_QUALIFIED": QualificationOutcomeValue.NOT_QUALIFIED,
}
_METHODS: dict[str, DecidedByKind] = {
    "MANUAL": DecidedByKind.MANUAL,
    "AUTOMATED": DecidedByKind.AUTOMATED,
}
_REF_TYPES = frozenset({"document", "verification_result", "url", "partner_reference"})


class _Problems:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, code: str, message: str) -> None:
        self.items.append({"code": code, "message": message})


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_rxil_company_package(payload: Any) -> PartnerCompanyIntake:
    """Read an RXIL package into the CRM's terms, or raise
    ``PartnerPackageInvalidError`` listing every problem found."""
    problems = _Problems()
    if not isinstance(payload, dict):
        problems.add("MALFORMED_PACKAGE", "the package must be a JSON object")
        raise PartnerPackageInvalidError(PARTNER, problems.items)

    package_id = _text(payload.get("package_id"))
    exporter = payload.get("exporter")
    qualification = payload.get("qualification")
    if not isinstance(exporter, dict):
        problems.add("MISSING_EXPORTER", "the package has no exporter object")
        exporter = {}
    if not isinstance(qualification, dict):
        problems.add("MISSING_QUALIFICATION", "the package has no qualification object")
        qualification = {}

    gstins = exporter.get("gstins")
    if gstins is None and exporter.get("gstin") is not None:
        gstins = [exporter["gstin"]]
    if gstins is not None and not isinstance(gstins, list):
        problems.add("INVALID_GSTIN", "gstins must be a list")
        gstins = None
    identity, reasons = check_identity(
        name=_text(exporter.get("legal_name")),
        country=_text(exporter.get("country")),
        pan=_text(exporter.get("pan")),
        gstins=[str(g) for g in gstins or []],
        iec=_text(exporter.get("iec")),
        cin=_text(exporter.get("cin")),
    )
    for reason in reasons:
        problems.add(reason.code, reason.message)

    decision = _DECISIONS.get(str(qualification.get("decision", "")).strip().upper())
    if decision is None:
        problems.add("INVALID_DECISION", "qualification.decision must be QUALIFIED or NOT_QUALIFIED")
    method = _METHODS.get(str(qualification.get("method", "MANUAL")).strip().upper())
    if method is None:
        problems.add("INVALID_METHOD", "qualification.method must be MANUAL or AUTOMATED")

    results = _parse_criteria(qualification.get("criteria") or [], package_id, problems)

    if problems.items:
        raise PartnerPackageInvalidError(PARTNER, problems.items)
    return PartnerCompanyIntake(
        source=QualificationSource.RXIL,
        identity=identity,  # type: ignore[arg-type]
        qualification=PartnerQualification(
            outcome=decision,  # type: ignore[arg-type]
            decided_by_kind=method,  # type: ignore[arg-type]
            results=tuple(results),
            note=_text(qualification.get("note")),
        ),
        external_reference=package_id,
        industry=_text(exporter.get("industry")),
        website=_text(exporter.get("website")),
    )


def _parse_criteria(items: Any, package_id: str | None, problems: _Problems) -> list[ResultEntry]:
    if not isinstance(items, list):
        problems.add("INVALID_CRITERIA", "qualification.criteria must be a list")
        return []
    results: list[ResultEntry] = []
    for position, item in enumerate(items, start=1):
        where = f"qualification.criteria[{position}]"
        if not isinstance(item, dict):
            problems.add("INVALID_CRITERIA", f"{where} must be an object")
            continue
        name = _text(item.get("criterion"))
        key = _CRITERION_KEYS.get(name or "")
        if key is None:
            problems.add("UNKNOWN_CRITERION", f"{where}: no CRM criterion for {name!r}")
            continue
        result = _RESULT_VALUES.get(str(item.get("result", "")).strip().upper())
        if result is None:
            problems.add("INVALID_RESULT", f"{where}: result must be PASS, FAIL or UNKNOWN")
            continue
        method = item.get("method")
        kind = _METHODS.get(str(method).strip().upper()) if method is not None else None
        if method is not None and kind is None:
            problems.add("INVALID_METHOD", f"{where}: method must be MANUAL or AUTOMATED")
            continue
        confidence = None
        if item.get("confidence") is not None:
            try:
                confidence = Decimal(str(item["confidence"]))
            except InvalidOperation:
                problems.add("INVALID_CONFIDENCE", f"{where}: confidence must be a number")
                continue
        refs: list[EvidenceRef] = []
        for ref in item.get("evidence_refs") or []:
            if (
                not isinstance(ref, dict)
                or ref.get("type") not in _REF_TYPES
                or not _text(ref.get("ref"))
            ):
                problems.add(
                    "INVALID_EVIDENCE",
                    f"{where}: each evidence reference needs a type ({sorted(_REF_TYPES)}) and a ref",
                )
                continue
            refs.append(EvidenceRef(type=ref["type"], ref=_text(ref["ref"])))  # type: ignore[arg-type]
        evidence = _text(item.get("evidence"))
        if evidence is None and not refs and result is not CriterionResultValue.UNKNOWN:
            where_from = f" in package {package_id}" if package_id else ""
            evidence = f"As supplied by RXIL{where_from}; RXIL gave no further evidence."
        results.append(
            ResultEntry(
                criterion_key=key,
                result=result,
                observed_value=_text(item.get("value")),
                evidence_note=evidence,
                evidence_refs=tuple(refs),
                reason=_text(item.get("reason")),
                confidence=confidence,
                decided_by_kind=kind,
            )
        )
    return results


__all__ = ["parse_rxil_company_package"]
