"""ANER-4.3-S2T2: the five RXIL-specific evidence_type values and their
PII-bearing classification.

`EvidenceType` and `PII_BEARING_EVIDENCE_TYPES` are pure Python — no database
needed to exercise the enum membership and classification logic, unlike
whether Postgres itself accepts the new values (covered at the database level
in test_s1t1_case_management_schema.test_every_evidence_type_is_accepted).
"""
from __future__ import annotations

from app.modules.cases.domain.entities.enums import PII_BEARING_EVIDENCE_TYPES, EvidenceType

_NEW_RXIL_VALUES = {
    "DUPLICATION_CHECK",
    "VESSEL_TRACKING",
    "BILL_OF_LADING",
    "BUYER_RATING",
    "INSURANCE_CERTIFICATE",
}


def test_five_new_rxil_evidence_types_exist_with_upper_snake_case_values():
    """Matches the existing evidence_type_enum casing convention exactly —
    the member name and its `.value` are identical upper-snake-case strings,
    same as every pre-existing EvidenceType member."""
    for name in _NEW_RXIL_VALUES:
        member = EvidenceType[name]
        assert member.value == name


def test_rxil_kyc_and_screening_outputs_are_not_given_new_values():
    """RXIL's KYC output maps to the existing KYB_RESULT value and its AML/CFT
    screening output maps to the existing SCREENING_RESULT value — neither
    got a new member, by design."""
    assert {"KYC_RESULT", "AML_RESULT", "AML_CFT_RESULT"}.isdisjoint(
        {member.name for member in EvidenceType}
    )
    assert EvidenceType.KYB_RESULT.value == "KYB_RESULT"
    assert EvidenceType.SCREENING_RESULT.value == "SCREENING_RESULT"


def test_buyer_rating_and_insurance_certificate_are_pii_bearing():
    """AC: of the five new types, the two that plausibly name individuals
    (a buyer rating report's directors/signatories, an insurance
    certificate's named insured/beneficiary) are flagged PII-bearing,
    following the same documented-gap convention as the pre-existing five."""
    assert EvidenceType.BUYER_RATING in PII_BEARING_EVIDENCE_TYPES
    assert EvidenceType.INSURANCE_CERTIFICATE in PII_BEARING_EVIDENCE_TYPES


def test_duplication_check_vessel_tracking_and_bill_of_lading_are_not_pii_bearing():
    """These three are commercial/logistics artifacts with no natural person
    as their subject and are deliberately left off the PII list."""
    assert EvidenceType.DUPLICATION_CHECK not in PII_BEARING_EVIDENCE_TYPES
    assert EvidenceType.VESSEL_TRACKING not in PII_BEARING_EVIDENCE_TYPES
    assert EvidenceType.BILL_OF_LADING not in PII_BEARING_EVIDENCE_TYPES


def test_pre_existing_pii_bearing_evidence_types_are_unchanged():
    """The five original PII-bearing types are still exactly as documented —
    this migration only ever adds to the set, never removes from it."""
    assert {
        EvidenceType.SCREENING_RESULT,
        EvidenceType.KYB_RESULT,
        EvidenceType.ONBOARDING_EVIDENCE,
        EvidenceType.TRAVEL_RULE_DATA,
        EvidenceType.REACTOR_INVESTIGATION,
    }.issubset(PII_BEARING_EVIDENCE_TYPES)


def test_pii_bearing_evidence_types_has_exactly_seven_members():
    assert len(PII_BEARING_EVIDENCE_TYPES) == 7
