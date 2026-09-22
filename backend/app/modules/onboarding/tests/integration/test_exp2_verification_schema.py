"""Direct-SQL constraint violation suite for EXP-2's `verification_result` table.

Raw SQL on purpose (this codebase's established convention — see
`test_s1t1_orchestration_schema.py`'s module docstring): inserting through the
ORM would prove only that SQLAlchemy declares a constraint, not that Postgres
enforces one.

The test database is shared across a whole run and is never reset, so every
test mints its own ids and none may assume an empty table.

Encrypted-at-rest fields
------------------------
`raw_result` is sized/typed and documented (`VerificationResult`'s class
docstring, `# PII / encrypted-at-rest documentation gap` comment) as needing
encryption-at-rest for PII-bearing verification_types (AML/SANCTIONS/
ADVERSE_MEDIA). There is no write path or KMS integration in this ticket, so
that acceptance criterion cannot be directly exercised by a test — same
already-accepted gap as `onboarding_request.tax_identification_number` /
`kyb_vendor_result.raw_vendor_response`, not a new one.
"""

import uuid

import psycopg2
import psycopg2.errors
import pytest

from app.platform.configuration.config import get_settings


def _pg_connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _execute(query: str, params: tuple = ()):
    conn = _pg_connect()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _fetch_one(query: str, params: tuple = ()):
    conn = _pg_connect()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


_BASE_INSERT = """
    INSERT INTO onboarding.verification_result (
        id, verification_type, entity_type, entity_reference,
        provider, status, performed_at, raw_result, normalized_result
    ) VALUES (
        %s, %s, %s, %s,
        'manual', 'PENDING', now(), '{}'::jsonb, '{}'::jsonb
    )
"""


@pytest.fixture
def verification_result_id():
    """Insert a valid verification_result row and return its id."""
    result_id = str(uuid.uuid4())
    _execute(
        _BASE_INSERT,
        (result_id, "KYC", "DIRECTOR", str(uuid.uuid4())),
    )
    return result_id


# ── Enum constraint tests ──────────────────────────────────────────────────────
# One test per distinct Postgres enum type this migration introduces.


def test_invalid_verification_type_enum_rejected():
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _BASE_INSERT,
            (str(uuid.uuid4()), "BOGUS_TYPE", "DIRECTOR", str(uuid.uuid4())),
        )


def test_invalid_entity_type_enum_rejected():
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _BASE_INSERT,
            (str(uuid.uuid4()), "KYC", "BOGUS_ENTITY", str(uuid.uuid4())),
        )


def test_invalid_status_enum_rejected(verification_result_id):
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.verification_result SET status = 'BOGUS_STATUS' WHERE id = %s",
            (verification_result_id,),
        )


def test_invalid_risk_level_enum_rejected(verification_result_id):
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.verification_result SET risk_level = 'BOGUS_RISK' WHERE id = %s",
            (verification_result_id,),
        )


def test_invalid_review_status_enum_rejected(verification_result_id):
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.verification_result SET review_status = 'BOGUS_REVIEW' WHERE id = %s",
            (verification_result_id,),
        )


# ── Valid enum values round-trip (boundary check: the constraint isn't
# accidentally rejecting everything, only what's outside the defined set) ─────


def test_every_verification_type_value_is_accepted():
    values = [
        "KYC", "KYB", "AML", "CFT", "SANCTIONS", "PEP", "ADVERSE_MEDIA",
        "COMPANY_REGISTRY", "UBO", "GST", "IEC", "BANK_ACCOUNT", "BUYER",
        "INVOICE", "INVOICE_DUPLICATION", "SHIPMENT", "VESSEL", "INSURANCE",
    ]
    for value in values:
        _execute(_BASE_INSERT, (str(uuid.uuid4()), value, "EXPORTER", str(uuid.uuid4())))


def test_every_entity_type_value_is_accepted():
    for value in ("EXPORTER", "BUYER", "DIRECTOR", "INVOICE", "VESSEL", "SHIPMENT"):
        _execute(_BASE_INSERT, (str(uuid.uuid4()), "KYC", value, str(uuid.uuid4())))


# ── Immutability trigger: reviewed_by / review_status ────────────────────────


def test_reviewed_by_and_review_status_are_immutable_once_set(verification_result_id):
    """trg_verification_result_field_immutability (reusing onboarding.
    prevent_field_mutation_when_set) rejects a second write to either column
    once it holds a non-null value — the DB-level half of the EXP-2 decision
    to make these write-once, mirroring resolved_by elsewhere in this
    codebase. The service-level half (VerificationResultAlreadyReviewedError)
    is covered by test_exp2_verification_service.py."""
    _execute(
        "UPDATE onboarding.verification_result "
        "SET reviewed_by = 'officer_1', review_status = 'ACCEPTED' WHERE id = %s",
        (verification_result_id,),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.verification_result "
            "SET reviewed_by = 'officer_2' WHERE id = %s",
            (verification_result_id,),
        )
    assert "reviewed_by is immutable once set" in str(exc.value)

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.verification_result "
            "SET review_status = 'REJECTED' WHERE id = %s",
            (verification_result_id,),
        )
    assert "review_status is immutable once set" in str(exc.value)


def test_other_columns_remain_mutable_after_review_is_set(verification_result_id):
    """The trigger only guards reviewed_by/review_status — status, risk_level,
    normalized_result etc. stay updatable (e.g. by VerificationService.
    get_verification_status's polling path) even after a review is recorded."""
    _execute(
        "UPDATE onboarding.verification_result "
        "SET reviewed_by = 'officer_1', review_status = 'ACCEPTED' WHERE id = %s",
        (verification_result_id,),
    )

    # Should not raise.
    _execute(
        "UPDATE onboarding.verification_result "
        "SET status = 'PASSED', normalized_result = '{\"x\": 1}'::jsonb WHERE id = %s",
        (verification_result_id,),
    )

    row = _fetch_one(
        "SELECT status, normalized_result FROM onboarding.verification_result WHERE id = %s",
        (verification_result_id,),
    )
    assert row[0] == "PASSED"


def test_reviewed_by_alone_can_be_set_without_review_status_yet():
    """The columns are independently nullable — setting one doesn't force the
    other, only the immutability guard applies once each individually holds
    a value."""
    result_id = str(uuid.uuid4())
    _execute(_BASE_INSERT, (result_id, "KYC", "DIRECTOR", str(uuid.uuid4())))

    # Not yet reviewed: both mutable.
    _execute(
        "UPDATE onboarding.verification_result SET reviewed_by = 'officer_1' WHERE id = %s",
        (result_id,),
    )
    # review_status is still NULL, so this is still the *first* write to it.
    _execute(
        "UPDATE onboarding.verification_result SET review_status = 'ESCALATED' WHERE id = %s",
        (result_id,),
    )

    with pytest.raises(psycopg2.errors.RaiseException):
        _execute(
            "UPDATE onboarding.verification_result SET reviewed_by = 'officer_2' WHERE id = %s",
            (result_id,),
        )
