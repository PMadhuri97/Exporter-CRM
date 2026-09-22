"""Comprehensive unit test suite for idempotency key validation and generation library."""

import uuid

import pytest

from app.platform.idempotency import (
    ValidationReason,
    derive_internal_key,
    generate_rail_reference,
    validate_customer_key,
    validate_internal_derived_key,
    validate_rail_reference,
)

VALID_UUID_V4 = "c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0c"


# =============================================================================
# 1. validate_customer_key — 20 Test Cases
# =============================================================================

@pytest.mark.parametrize(
    "key, expected_valid, expected_reason",
    [
        # Case 1: Valid lower-case UUID v4
        ("c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0c", True, None),
        # Case 2: Valid upper-case UUID v4
        ("C8F3B2A1-4E2D-4F1A-8C3B-5D6E7F8A9B0C", True, None),
        # Case 3: Valid mixed-case UUID v4
        ("c8f3b2a1-4E2D-4f1a-8C3B-5d6e7f8a9b0c", True, None),
        # Case 4: Generated random UUID v4
        (str(uuid.uuid4()), True, None),
        # Case 5: Empty string
        ("", False, ValidationReason.EMPTY_KEY),
        # Case 6: Whitespace string
        ("   ", False, ValidationReason.EMPTY_KEY),
        # Case 7: Exceeds 64 characters (65 chars)
        ("a" * 65, False, ValidationReason.EXCEEDS_MAX_LENGTH),
        # Case 8: Exceeds 64 characters with uuid prefix
        ("c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0c-extra-characters-making-it-too-long", False, ValidationReason.EXCEEDS_MAX_LENGTH),
        # Case 9: UUID v1 instead of v4 (version digit is 1)
        ("c8f3b2a1-4e2d-1f1a-8c3b-5d6e7f8a9b0c", False, ValidationReason.INVALID_UUID_V4),
        # Case 10: UUID v3 instead of v4 (version digit is 3)
        ("c8f3b2a1-4e2d-3f1a-8c3b-5d6e7f8a9b0c", False, ValidationReason.INVALID_UUID_V4),
        # Case 11: UUID v5 instead of v4 (version digit is 5)
        ("c8f3b2a1-4e2d-5f1a-8c3b-5d6e7f8a9b0c", False, ValidationReason.INVALID_UUID_V4),
        # Case 12: Missing hyphens
        ("c8f3b2a14e2d4f1a8c3b5d6e7f8a9b0c", False, ValidationReason.INVALID_UUID_V4),
        # Case 13: Non-hex characters
        ("g8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0z", False, ValidationReason.INVALID_UUID_V4),
        # Case 14: Incorrect hyphen positioning
        ("c8f3b2a14-e2d-4f1a-8c3b-5d6e7f8a9b0c", False, ValidationReason.INVALID_UUID_V4),
        # Case 15: Truncated UUID
        ("c8f3b2a1-4e2d-4f1a-8c3b", False, ValidationReason.INVALID_UUID_V4),
        # Case 16: Invalid variant digit (must be 8, 9, a, or b)
        ("c8f3b2a1-4e2d-4f1a-0c3b-5d6e7f8a9b0c", False, ValidationReason.INVALID_UUID_V4),
        # Case 17: Special characters in UUID
        ("c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0!", False, ValidationReason.INVALID_UUID_V4),
        # Case 18: Arbitrary non-UUID string
        ("my-custom-idempotency-key-12345", False, ValidationReason.INVALID_UUID_V4),
        # Case 19: Numeric string
        ("123456789012345678901234567890123456", False, ValidationReason.INVALID_UUID_V4),
        # Case 20: Null-like string "null"
        ("null", False, ValidationReason.INVALID_UUID_V4),
    ],
)
def test_validate_customer_key_20_cases(key, expected_valid, expected_reason):
    res = validate_customer_key(key)
    assert res.is_valid == expected_valid
    assert res.reason == expected_reason


# =============================================================================
# 2. validate_internal_derived_key — 20 Test Cases
# =============================================================================

@pytest.mark.parametrize(
    "key, expected_valid, expected_reason",
    [
        # Case 1: Standard valid derived key
        (f"{VALID_UUID_V4}:customer_debit", True, None),
        # Case 2: Valid key with multiple underscore step identifier
        (f"{VALID_UUID_V4}:post_ledger_entry_step_one", True, None),
        # Case 3: Valid key with single letter step identifier
        (f"{VALID_UUID_V4}:a", True, None),
        # Case 4: Valid key with uppercase parent UUID v4
        (f"{VALID_UUID_V4.upper()}:step_two", True, None),
        # Case 5: Empty string
        ("", False, ValidationReason.EMPTY_KEY),
        # Case 6: Whitespace string
        ("   ", False, ValidationReason.EMPTY_KEY),
        # Case 7: Exceeds 256 characters limit
        (f"{VALID_UUID_V4}:" + ("a" * 250), False, ValidationReason.EXCEEDS_MAX_LENGTH),
        # Case 8: Missing colon separator
        (f"{VALID_UUID_V4}customer_debit", False, ValidationReason.INVALID_FORMAT),
        # Case 9: Multiple colon separators
        (f"{VALID_UUID_V4}:step:substep", False, ValidationReason.INVALID_FORMAT),
        # Case 10: Invalid parent UUID (v1)
        ("c8f3b2a1-4e2d-1f1a-8c3b-5d6e7f8a9b0c:step_one", False, ValidationReason.INVALID_UUID_V4),
        # Case 11: Invalid parent UUID (non-hex)
        ("invalid-uuid-format:step_one", False, ValidationReason.INVALID_UUID_V4),
        # Case 12: Uppercase in step identifier
        (f"{VALID_UUID_V4}:CustomerDebit", False, ValidationReason.INVALID_STEP_IDENTIFIER),
        # Case 13: Digits in step identifier
        (f"{VALID_UUID_V4}:step1", False, ValidationReason.INVALID_STEP_IDENTIFIER),
        # Case 14: Hyphens in step identifier
        (f"{VALID_UUID_V4}:step-one", False, ValidationReason.INVALID_STEP_IDENTIFIER),
        # Case 15: Special characters in step identifier
        (f"{VALID_UUID_V4}:step_one!", False, ValidationReason.INVALID_STEP_IDENTIFIER),
        # Case 16: Spaces in step identifier
        (f"{VALID_UUID_V4}:step one", False, ValidationReason.INVALID_STEP_IDENTIFIER),
        # Case 17: Empty step identifier
        (f"{VALID_UUID_V4}:", False, ValidationReason.INVALID_STEP_IDENTIFIER),
        # Case 18: Empty parent UUID
        (":step_one", False, ValidationReason.INVALID_FORMAT),
        # Case 19: Only colon
        (":", False, ValidationReason.INVALID_FORMAT),
        # Case 20: Step identifier starting with a leading underscore (valid)
        (f"{VALID_UUID_V4}:_step_start", True, None),  # Underscores allowed
    ],
)
def test_validate_internal_derived_key_20_cases(key, expected_valid, expected_reason):
    res = validate_internal_derived_key(key)
    assert res.is_valid == expected_valid
    assert res.reason == expected_reason


# =============================================================================
# 3. validate_rail_reference — 20 Test Cases
# =============================================================================

@pytest.mark.parametrize(
    "key, expected_valid, expected_reason",
    [
        # Case 1: Valid ACH reference
        ("ANER-a1b2c3d4-1-ACH", True, None),
        # Case 2: Valid WIRE reference
        ("ANER-12345678-leg_1-WIRE", True, None),
        # Case 3: Valid RTP reference
        ("ANER-abcdef12-100-RTP", True, None),
        # Case 4: Valid FEDNOW reference
        ("ANER-98765432-seq_99-FEDNOW", True, None),
        # Case 5: Valid SWIFT reference
        ("ANER-fedcba98-swift_leg-SWIFT", True, None),
        # Case 6: Valid CARD reference
        ("ANER-a1b2c3d4-auth_leg-CARD", True, None),
        # Case 7: Valid BOOK reference
        ("ANER-a1b2c3d4-internal-BOOK", True, None),
        # Case 8: Valid lower-case rail code (normalized case check)
        ("ANER-a1b2c3d4-1-ach", True, None),
        # Case 9: Empty string
        ("", False, ValidationReason.EMPTY_KEY),
        # Case 10: Whitespace string
        ("   ", False, ValidationReason.EMPTY_KEY),
        # Case 11: Exceeds 64 characters limit
        ("ANER-a1b2c3d4-" + ("a" * 50) + "-ACH", False, ValidationReason.EXCEEDS_MAX_LENGTH),
        # Case 12: Wrong prefix (e.g. TEST instead of ANER)
        ("TEST-a1b2c3d4-1-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 13: Missing prefix
        ("a1b2c3d4-1-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 14: Unknown rail code
        ("ANER-a1b2c3d4-1-UNKNOWN_RAIL", False, ValidationReason.UNKNOWN_RAIL_CODE),
        # Case 15: Missing leg sequence field
        ("ANER-a1b2c3d4-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 16: Extra hyphenated fields
        ("ANER-a1b2c3d4-1-extra-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 17: Special characters in settlement_id
        ("ANER-a1b2c3!4-1-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 18: Special characters in leg sequence
        ("ANER-a1b2c3d4-1#-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 19: Empty settlement_id
        ("ANER--1-ACH", False, ValidationReason.INVALID_FORMAT),
        # Case 20: Arbitrary string format
        ("ANER_ACH_REFERENCE_KEY_123", False, ValidationReason.INVALID_FORMAT),
    ],
)
def test_validate_rail_reference_20_cases(key, expected_valid, expected_reason):
    res = validate_rail_reference(key)
    assert res.is_valid == expected_valid
    assert res.reason == expected_reason


# =============================================================================
# 4. Determinism Verification — 1,000 Iteration Tests
# =============================================================================

def test_derive_internal_key_determinism_1000_runs():
    parent_key = "c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0c"
    step_identifier = "customer_debit"

    first_output = derive_internal_key(parent_key, step_identifier)
    assert first_output == f"{parent_key}:{step_identifier}"

    for _ in range(1000):
        output = derive_internal_key(parent_key, step_identifier)
        assert output == first_output


def test_generate_rail_reference_determinism_1000_runs():
    settlement_id = "c8f3b2a1-4e2d-4f1a-8c3b-5d6e7f8a9b0c"
    leg_sequence = 1
    rail_code = "ACH"

    first_output = generate_rail_reference(settlement_id, leg_sequence, rail_code)
    assert first_output == "ANER-c8f3b2a1-1-ACH"

    for _ in range(1000):
        output = generate_rail_reference(settlement_id, leg_sequence, rail_code)
        assert output == first_output


# =============================================================================
# 5. Generator Edge & Error Cases
# =============================================================================

def test_derive_internal_key_invalid_parent_raises_value_error():
    with pytest.raises(ValueError, match="Cannot derive internal key"):
        derive_internal_key("invalid-parent-uuid", "step_one")


def test_derive_internal_key_invalid_step_raises_value_error():
    with pytest.raises(ValueError, match="Cannot derive internal key"):
        derive_internal_key(VALID_UUID_V4, "StepOneWithUppercase")


def test_generate_rail_reference_empty_settlement_id_raises_value_error():
    with pytest.raises(ValueError, match="Settlement ID cannot be empty"):
        generate_rail_reference("", 1, "ACH")


def test_generate_rail_reference_invalid_rail_code_raises_value_error():
    with pytest.raises(ValueError, match="Cannot generate rail reference"):
        generate_rail_reference("a1b2c3d4-1234", 1, "INVALID_RAIL")
