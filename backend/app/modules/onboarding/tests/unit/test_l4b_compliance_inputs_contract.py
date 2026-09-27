"""The 4A ↔ 4B compliance-inputs contract's shape — 4B-0.

``docs/dev4/4b-task.md`` §6.1 fixes the output shape, and §6.2 invariant 7 freezes
it once the seam lands: a field added, removed, renamed, reordered or retyped is a
contract change that needs both developers' written agreement first (§6.4). These
tests are the tripwire. If one fails, the fix is the agreement, not the test.
"""

from __future__ import annotations

import dataclasses
import inspect
import uuid

import pytest

from app.modules.onboarding.application.compliance_inputs import ComplianceInputsService
from app.modules.onboarding.application.screening_review_service import (
    SCREENING_CATALOGUE,
    VALID_ITEM_KEYS,
)
from app.modules.onboarding.domain import compliance_inputs
from app.modules.onboarding.domain.compliance_inputs import (
    CompanyComplianceInputs,
    ComplianceInputsReader,
    ScreeningItemInput,
    VerificationInput,
)

#: §6.1, verbatim: (field, annotation) in declaration order.
FROZEN_SHAPE = {
    VerificationInput: [
        ("verification_result_id", "uuid.UUID"),
        ("verification_type", "str"),
        ("entity_type", "str"),
        ("provider", "str"),
        ("status", "str"),
        ("risk_level", "str | None"),
        ("performed_at", "datetime"),
        ("is_placeholder", "bool"),
        ("latest_review_id", "uuid.UUID | None"),
        ("latest_review_status", "str | None"),
        ("latest_reviewed_at", "datetime | None"),
        ("evidence_document_ids", "tuple[uuid.UUID, ...]"),
    ],
    ScreeningItemInput: [
        ("item_key", "str"),
        ("screening_review_item_id", "uuid.UUID | None"),
        ("status", "str | None"),
        ("reviewed_by", "str | None"),
        ("reviewed_at", "datetime | None"),
    ],
    CompanyComplianceInputs: [
        ("company_id", "uuid.UUID"),
        ("screening_catalogue", "tuple[str, ...]"),
        ("screening_items", "tuple[ScreeningItemInput, ...]"),
        ("verifications", "tuple[VerificationInput, ...]"),
    ],
}


@pytest.mark.parametrize("cls", list(FROZEN_SHAPE), ids=lambda cls: cls.__name__)
def test_each_type_has_exactly_the_frozen_fields_in_order(cls):
    actual = [(field.name, field.type) for field in dataclasses.fields(cls)]
    assert actual == FROZEN_SHAPE[cls]


@pytest.mark.parametrize("cls", list(FROZEN_SHAPE), ids=lambda cls: cls.__name__)
def test_each_type_is_a_frozen_dataclass(cls):
    instance = cls(**{name: None for name, _ in FROZEN_SHAPE[cls]})
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, FROZEN_SHAPE[cls][0][0], "changed")


def test_no_type_carries_a_judgement():
    """§6.2 invariant 1: facts, not judgements. Dev4A's rules are not exposed here."""
    judgement_words = ("ready", "pending", "answered", "clear", "complete", "ok")
    for cls, fields in FROZEN_SHAPE.items():
        for name, _ in fields:
            assert not any(word in name for word in judgement_words), (cls.__name__, name)


def test_the_module_exports_exactly_the_contract():
    assert sorted(compliance_inputs.__all__) == [
        "CompanyComplianceInputs",
        "ComplianceInputsReader",
        "ScreeningItemInput",
        "VerificationInput",
    ]


def test_the_reader_protocol_has_exactly_the_two_reads():
    methods = {
        name
        for name, member in vars(ComplianceInputsReader).items()
        if inspect.isfunction(member) and not name.startswith("_")
    }
    assert methods == {"company_inputs", "buyer_checks"}


@pytest.mark.parametrize(
    ("method", "parameter"),
    [("company_inputs", "company_id"), ("buyer_checks", "deal_buyer_id")],
)
def test_the_service_implements_each_read_with_the_protocols_signature(method, parameter):
    protocol_method = getattr(ComplianceInputsReader, method)
    service_method = getattr(ComplianceInputsService, method)
    assert inspect.iscoroutinefunction(service_method)
    assert list(inspect.signature(service_method).parameters) == ["self", parameter]
    assert list(inspect.signature(protocol_method).parameters) == ["self", parameter]
    assert (
        inspect.signature(service_method).return_annotation
        == inspect.signature(protocol_method).return_annotation
    )


def test_the_catalogue_is_the_eight_keys_in_display_order():
    """§6.1: "the eight keys, in display order" — the order `VerificationSection.tsx` renders."""
    assert SCREENING_CATALOGUE == (
        "website-reviewed",
        "address-physical",
        "business-consistency",
        "payment-purpose",
        "bank-statements-reviewed",
        "suspicious-bank-indicators",
        "exception-approval",
        "exception-evidence",
    )
    assert frozenset(SCREENING_CATALOGUE) == VALID_ITEM_KEYS
    assert len(set(SCREENING_CATALOGUE)) == 8


def test_a_value_can_be_built_as_the_contract_describes():
    company_id = uuid.uuid4()
    empty = CompanyComplianceInputs(
        company_id=company_id,
        screening_catalogue=SCREENING_CATALOGUE,
        screening_items=tuple(
            ScreeningItemInput(
                item_key=key,
                screening_review_item_id=None,
                status=None,
                reviewed_by=None,
                reviewed_at=None,
            )
            for key in SCREENING_CATALOGUE
        ),
        verifications=(),
    )
    assert [item.item_key for item in empty.screening_items] == list(SCREENING_CATALOGUE)
