"""Evidence on a verification result, and the rule for a manual result
(``docs/contracts/verification-and-screening.md`` §3, §8).

Pure: no I/O. The shape mirrors the qualification contract's evidence
(``criterion-result.md``): a note and/or references ``{type, ref}``. A verification
result accepts two reference types — ``document`` (a ``crm_document.id``) and ``url``.
Whether a ``document`` reference exists and belongs to the result's subject is checked
against the database by ``VerificationService``; this module only says what a manual
outcome must carry.

A ``url`` reference must be an absolute ``http`` or ``https`` link with a host. It is
stored as given and shown to other staff as a link, so anything else — a
``javascript:`` or ``data:`` URL above all — would be script run in the reader's
session (found in review, 28 Sep 2026).

**``check_manual_outcome`` is the one place the rule lives.**

Minimum evidence for a manual ``PASSED`` (decided 28 Sep 2026)
--------------------------------------------------------------
A non-blank note **or** at least one reference — the qualification contract's rule.
``FAILED`` and ``REVIEW`` need no evidence.

A manual ``PENDING``
--------------------
A manual entry is synchronous: the operator's input *is* the outcome, and nothing will
ever poll it. A manual ``PENDING`` is therefore a row nothing can resolve — the
"pending-forever" placeholder the contract's §8 retires — so it is refused. Whether any pending
check counts toward ``CLEAR`` is the Clear policy's question; if it ever needs a pending manual entry,
that exception goes here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.modules.onboarding.domain.entities.orchestration_enums import VerificationResultStatus
from app.modules.onboarding.domain.web_links import URL_SCHEMES, is_web_link
from app.shared.exceptions import ValidationError

EvidenceRefType = Literal["document", "url"]
EVIDENCE_REF_TYPES: frozenset[str] = frozenset({"document", "url"})


@dataclass(frozen=True)
class EvidenceRef:
    type: EvidenceRefType
    ref: str

    def as_json(self) -> dict[str, str]:
        return {"type": self.type, "ref": self.ref}


@dataclass(frozen=True)
class VerificationEvidence:
    note: str | None = None
    refs: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    @property
    def cleaned_note(self) -> str | None:
        note = (self.note or "").strip()
        return note or None

    @property
    def is_empty(self) -> bool:
        return self.cleaned_note is None and not self.refs

    def document_ids(self) -> tuple[uuid.UUID, ...]:
        """The ``document`` references as ids. Raises ``ValidationError`` for one that
        is not a uuid."""
        ids: list[uuid.UUID] = []
        for ref in self.refs:
            if ref.type != "document":
                continue
            try:
                ids.append(uuid.UUID(ref.ref))
            except ValueError as exc:
                raise ValidationError(
                    f"evidence reference {ref.ref!r} is not a document id"
                ) from exc
        return tuple(ids)


def _is_web_link(value: str) -> bool:
    """An absolute http(s) link with a host — the shared rule in ``web_links``, which
    the company website uses too."""
    return is_web_link(value)


def check_evidence_shape(evidence: VerificationEvidence | None) -> None:
    """Every reference names a known type and a non-blank ref; a ``url`` is an
    http(s) link."""
    if evidence is None:
        return
    for ref in evidence.refs:
        if ref.type not in EVIDENCE_REF_TYPES or not ref.ref.strip():
            raise ValidationError(
                "evidence references need a type "
                f"({', '.join(sorted(EVIDENCE_REF_TYPES))}) and a non-blank ref"
            )
        if ref.type == "url" and not _is_web_link(ref.ref):
            raise ValidationError(
                "a url evidence reference must be an http:// or https:// link"
            )
    evidence.document_ids()


def check_manual_outcome(
    status: VerificationResultStatus, evidence: VerificationEvidence | None
) -> None:
    """The rule a manually recorded outcome must meet. See the module docstring.

    Raises:
        ValidationError: a ``PENDING`` manual entry, or a ``PASSED`` one with no
            evidence.
    """
    check_evidence_shape(evidence)
    if status is VerificationResultStatus.PENDING:
        # Nothing would ever resolve it (verification-and-screening.md §8).
        raise ValidationError(
            "a manual verification result is recorded with its real outcome "
            "(PASSED, FAILED or REVIEW); a manual PENDING result could never resolve"
        )
    if status is VerificationResultStatus.PASSED and (evidence is None or evidence.is_empty):
        # A note or at least one reference.
        raise ValidationError(
            "a manual PASSED result needs evidence: a note or at least one reference"
        )


__all__ = [
    "EVIDENCE_REF_TYPES",
    "URL_SCHEMES",
    "EvidenceRef",
    "EvidenceRefType",
    "VerificationEvidence",
    "check_evidence_shape",
    "check_manual_outcome",
]
