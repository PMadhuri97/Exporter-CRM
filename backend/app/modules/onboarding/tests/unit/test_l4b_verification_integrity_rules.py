"""Dev4B's pure rules — no database (``docs/dev4/4b-task.md`` §5).

* the manual-outcome evidence rule lives in one function (D16, decided by the lead);
* evidence references are shaped like the qualification contract's;
* a review chain is ordered by its supersedes pointers;
* provenance and placeholder labels are honest;
* the screening catalogue is one ordered list, served with labels and sections.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    SCREENING_CATALOGUE_ITEMS,
    VALID_ITEM_KEYS,
)
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationResultStatus
from app.modules.onboarding.domain.entities.screening_review import SCREENING_STATUSES
from app.modules.onboarding.domain.entities.verification_result import (
    is_placeholder_result,
    provenance_of,
)
from app.modules.onboarding.domain.verification_evidence import (
    EvidenceRef,
    VerificationEvidence,
    check_evidence_shape,
    check_manual_outcome,
)
from app.modules.onboarding.infrastructure.adapters.manual_entry_adapter import (
    PROVIDER_NAME as MANUAL_PROVIDER,
)
from app.modules.onboarding.infrastructure.adapters.stub_rxil_adapter import (
    PROVIDER_NAME as STUB_PROVIDER,
)
from app.modules.onboarding.infrastructure.repositories.verification_review_repository import (
    order_chain,
)
from app.shared.exceptions import ValidationError

# ── The manual outcome rule (D16) ────────────────────────────────────────────


def test_a_manual_passed_needs_evidence():
    with pytest.raises(ValidationError, match="evidence"):
        check_manual_outcome(VerificationResultStatus.PASSED, None)
    with pytest.raises(ValidationError, match="evidence"):
        check_manual_outcome(VerificationResultStatus.PASSED, VerificationEvidence(note=" "))


@pytest.mark.parametrize(
    "evidence",
    [
        VerificationEvidence(note="Bank letter seen"),
        VerificationEvidence(refs=(EvidenceRef(type="url", ref="https://example.org"),)),
        VerificationEvidence(refs=(EvidenceRef(type="document", ref=str(uuid.uuid4())),)),
    ],
    ids=["note", "url", "document"],
)
def test_a_note_or_one_reference_is_enough_for_passed(evidence):
    check_manual_outcome(VerificationResultStatus.PASSED, evidence)


@pytest.mark.parametrize("status", [VerificationResultStatus.FAILED, VerificationResultStatus.REVIEW])
def test_failed_and_review_need_no_evidence(status):
    check_manual_outcome(status, None)


def test_a_manual_pending_is_refused():
    with pytest.raises(ValidationError, match="PENDING"):
        check_manual_outcome(VerificationResultStatus.PENDING, VerificationEvidence(note="x"))


@pytest.mark.parametrize(
    "ref",
    [
        EvidenceRef(type="document", ref="not-a-uuid"),
        EvidenceRef(type="url", ref="   "),
        EvidenceRef(type="verification_result", ref=str(uuid.uuid4())),  # type: ignore[arg-type]
    ],
    ids=["document-not-uuid", "blank-ref", "unknown-type"],
)
def test_malformed_references_are_refused(ref):
    with pytest.raises(ValidationError):
        check_evidence_shape(VerificationEvidence(refs=(ref,)))


# A url reference is shown to other staff as a link, so only a web link may be
# stored: anything else would be script run in the reader's session.
@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "//evil.example/path",
        "www.example.com",
        "https://",
        "http://[::1",
    ],
)
def test_a_url_reference_must_be_an_http_link(url):
    with pytest.raises(ValidationError, match="http"):
        check_evidence_shape(VerificationEvidence(refs=(EvidenceRef(type="url", ref=url),)))


@pytest.mark.parametrize(
    "url",
    ["https://registry.example/entity/1", "http://news.example/a?b=c#d", "HTTPS://EXAMPLE.ORG"],
)
def test_an_http_or_https_link_is_accepted(url):
    check_evidence_shape(VerificationEvidence(refs=(EvidenceRef(type="url", ref=url),)))


def test_document_ids_are_the_document_references_only_in_order():
    first, second = uuid.uuid4(), uuid.uuid4()
    evidence = VerificationEvidence(
        refs=(
            EvidenceRef(type="document", ref=str(first)),
            EvidenceRef(type="url", ref="https://example.org"),
            EvidenceRef(type="document", ref=str(second)),
        )
    )
    assert evidence.document_ids() == (first, second)


# ── Review chains ────────────────────────────────────────────────────────────


def _review(review_id, supersedes):
    return SimpleNamespace(id=review_id, supersedes_review_id=supersedes)


def test_a_chain_is_ordered_by_supersedes_pointers_not_by_input_order():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    chain = order_chain([_review(c, b), _review(a, None), _review(b, a)])
    assert [r.id for r in chain] == [a, b, c]


def test_no_reviews_is_an_empty_chain():
    assert order_chain([]) == ()


# ── Provenance and placeholders (§5.4, §5.9) ────────────────────────────────


def test_the_stub_provider_is_lower_case_and_labelled_stub():
    assert STUB_PROVIDER == STUB_PROVIDER.lower()
    assert provenance_of(STUB_PROVIDER) == "STUB"


def test_rows_the_stub_wrote_before_4b6_are_still_labelled_stub():
    assert provenance_of("RXIL") == "STUB"


def test_manual_is_a_person_and_anything_else_is_a_provider():
    assert provenance_of(MANUAL_PROVIDER) == "MANUAL"
    assert provenance_of("rxil") == "PROVIDER"


@pytest.mark.parametrize(
    ("normalized_result", "provider_reference", "expected"),
    [
        ({"stub": True}, None, True),
        ({"stub": True}, "", True),
        ({"stub": True}, "ref-1", False),
        ({"stub": "true"}, None, False),
        ({}, None, False),
        (None, None, False),
    ],
)
def test_placeholder_rule(normalized_result, provider_reference, expected):
    assert is_placeholder_result(normalized_result, provider_reference) is expected


# ── Screening catalogue (§5.5) ───────────────────────────────────────────────


def test_the_catalogue_is_one_ordered_list_every_other_copy_derives_from():
    assert SCREENING_CATALOGUE == tuple(item.key for item in SCREENING_CATALOGUE_ITEMS)
    assert frozenset(SCREENING_CATALOGUE) == VALID_ITEM_KEYS
    assert len(SCREENING_CATALOGUE) == len(VALID_ITEM_KEYS) == 8


def test_every_catalogue_item_has_a_label_and_a_known_section():
    sections = ("Company checks", "Volume and activity", "EDD", "Exception")
    for item in SCREENING_CATALOGUE_ITEMS:
        assert item.label.strip()
        assert item.section in sections
    # Sections appear in display order, each as one contiguous run.
    seen = [item.section for item in SCREENING_CATALOGUE_ITEMS]
    runs = [s for i, s in enumerate(seen) if i == 0 or seen[i - 1] != s]
    assert runs == list(sections)


def test_the_four_screening_statuses():
    assert SCREENING_STATUSES == ("NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT")
