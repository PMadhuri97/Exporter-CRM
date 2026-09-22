"""Direct-SQL constraint violation suite for the S1T1 orchestration schema.

Raw SQL on purpose (BUILD.md #12): inserting through the ORM would prove only
that SQLAlchemy declares a constraint, not that Postgres enforces one.  Every
constraint the migration creates is violated here and asserted rejected, and the
boundary of each is exercised alongside it — a constraint that rejects everything
is as broken as one that rejects nothing.

The test database is shared across a whole run and is never reset, so every test
mints its own ids and none may assume an empty table.

Encrypted-at-rest fields
------------------------
The columns ``tax_identification_number`` (onboarding_request),
``date_of_birth`` and ``identification_number`` (ubo_record) are sized at
String(512) for ciphertext capacity, and annotated in the model with
``# Encrypted at rest``.  There is no write path or KMS integration in this
PR, so the encryption-at-rest acceptance criterion cannot be directly exercised
by a test.  The column design is in place; encryption will be testable once a
KMS provider and field-level encryption layer are implemented.
"""

import uuid

import psycopg2
import psycopg2.errors
import pytest

from app.platform.configuration.config import get_settings

# ── SQLSTATE codes ────────────────────────────────────────────────────────────

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
INVALID_TEXT_REPRESENTATION = "22P02"


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


def _insert_customer():
    """Create a throwaway onboarding_customers row and return its id."""
    customer_id = str(uuid.uuid4())
    _execute(
        """
        INSERT INTO onboarding.onboarding_customers (
            id, email, full_name, external_user_id, level_name, status
        ) VALUES (
            %s, %s, 'Fixture Corp', %s, 'basic', 'PENDING'
        )
        """,
        (customer_id, f"{uuid.uuid4().hex}@example.com", uuid.uuid4().hex),
    )
    return customer_id


# Base INSERT SQL for onboarding_request.  Column order is fixed; callers
# override individual columns via string formatting before the VALUES tuple.
_BASE_INSERT_REQUEST = """
    INSERT INTO onboarding.onboarding_request (
        id, tenant_id, customer_id, idempotency_key, status, entity_type,
        legal_name, registration_number, incorporation_country,
        registered_address, initial_user_id
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        'Test Corp', '123456', 'US',
        '{"country": "US"}', 'user_1'
    )
"""


@pytest.fixture
def onboarding_request_id():
    """Insert a valid onboarding_request and return its id."""
    req_id = str(uuid.uuid4())
    customer_id = _insert_customer()
    tenant_id = str(uuid.uuid4())

    _execute(
        _BASE_INSERT_REQUEST,
        (req_id, tenant_id, customer_id, f"key-{uuid.uuid4().hex[:8]}", "DRAFT", "CORPORATION"),
    )
    return req_id


@pytest.fixture
def request_with_tenant():
    """Insert a valid onboarding_request, return (req_id, tenant_id, customer_id)."""
    req_id = str(uuid.uuid4())
    customer_id = _insert_customer()
    tenant_id = str(uuid.uuid4())
    idem_key = f"key-{uuid.uuid4().hex[:8]}"

    _execute(
        _BASE_INSERT_REQUEST,
        (req_id, tenant_id, customer_id, idem_key, "DRAFT", "CORPORATION"),
    )
    return req_id, tenant_id, customer_id


# ── Review Item 1: tenant/idempotency unique constraint ──────────────────────


def test_tenant_idempotency_key_unique_constraint(request_with_tenant):
    """uq_onboarding_request_tenant_idem_key rejects duplicate (tenant, idem_key)."""
    _, tenant_id, _ = request_with_tenant

    # Read the idempotency_key of the first insert
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT idempotency_key FROM onboarding.onboarding_request WHERE tenant_id = %s",
        (tenant_id,),
    )
    idem_key = cur.fetchone()[0]
    cur.close()
    conn.close()

    # Second insert: same tenant_id + idempotency_key, different everything else
    second_customer = _insert_customer()
    with pytest.raises(psycopg2.errors.UniqueViolation) as exc:
        _execute(
            _BASE_INSERT_REQUEST,
            (
                str(uuid.uuid4()),
                tenant_id,
                second_customer,
                idem_key,
                "DRAFT",
                "CORPORATION",
            ),
        )
    assert "uq_onboarding_request_tenant_idem_key" in str(exc.value)


# ── Existing constraint: partial unique on active customer ────────────────────


def test_one_active_onboarding_per_customer(onboarding_request_id):
    """uq_onboarding_request_active_customer allows only one ACTIVE per customer."""
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT customer_id, tenant_id FROM onboarding.onboarding_request WHERE id = %s",
        (onboarding_request_id,),
    )
    customer_id, tenant_id = cur.fetchone()
    cur.close()
    conn.close()

    _execute(
        "UPDATE onboarding.onboarding_request SET status = 'ACTIVE' WHERE id = %s",
        (onboarding_request_id,),
    )

    with pytest.raises(psycopg2.errors.UniqueViolation) as exc:
        _execute(
            _BASE_INSERT_REQUEST,
            (
                str(uuid.uuid4()),
                tenant_id,
                customer_id,
                f"key-{uuid.uuid4().hex[:8]}",
                "ACTIVE",
                "CORPORATION",
            ),
        )
    assert "uq_onboarding_request_active_customer" in str(exc.value)


# ── Review Item 2: enum constraint tests ──────────────────────────────────────
#
# One test per distinct Postgres enum type introduced by this migration.
# Each test attempts a direct-SQL INSERT with an invalid literal and asserts
# PostgreSQL rejects it with SQLSTATE 22P02 (invalid_text_representation).


def test_invalid_status_enum_rejected():
    """onboarding_request_status_enum rejects values outside the defined set."""
    customer_id = _insert_customer()
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _BASE_INSERT_REQUEST,
            (
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                customer_id,
                f"key-{uuid.uuid4().hex[:8]}",
                "BOGUS_STATUS",
                "CORPORATION",
            ),
        )


def test_invalid_entity_type_enum_rejected():
    """onboarding_entity_type_enum rejects values outside the defined set."""
    customer_id = _insert_customer()
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _BASE_INSERT_REQUEST,
            (
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                customer_id,
                f"key-{uuid.uuid4().hex[:8]}",
                "DRAFT",
                "BOGUS_ENTITY",
            ),
        )


def test_invalid_screening_result_enum_rejected(onboarding_request_id):
    """onboarding_screening_result_enum on screening_result rejects invalid values."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET screening_result = 'BOGUS_SCREENING' WHERE id = %s",
            (onboarding_request_id,),
        )


def test_invalid_risk_rating_enum_rejected(onboarding_request_id):
    """onboarding_risk_rating_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET risk_rating = 'BOGUS_RATING' WHERE id = %s",
            (onboarding_request_id,),
        )


def test_invalid_compliance_decision_enum_rejected(onboarding_request_id):
    """onboarding_compliance_decision_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET compliance_decision = 'BOGUS_DECISION' WHERE id = %s",
            (onboarding_request_id,),
        )


def test_invalid_rejection_category_enum_rejected(onboarding_request_id):
    """onboarding_rejection_category_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET rejection_category = 'BOGUS_CATEGORY' WHERE id = %s",
            (onboarding_request_id,),
        )


def test_invalid_control_type_enum_rejected(onboarding_request_id):
    """ubo_control_type_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.ubo_record (
                id, onboarding_request_id, first_name, last_name,
                control_type, kyc_result
            ) VALUES (%s, %s, 'Jane', 'Doe', 'BOGUS_CONTROL', 'VERIFIED')
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


def test_invalid_identification_type_enum_rejected(onboarding_request_id):
    """ubo_identification_type_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.ubo_record (
                id, onboarding_request_id, first_name, last_name,
                control_type, kyc_result, identification_type
            ) VALUES (
                %s, %s, 'Jane', 'Doe', 'DIRECT_OWNERSHIP', 'VERIFIED',
                'BOGUS_ID_TYPE'
            )
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


def test_invalid_kyc_result_enum_rejected(onboarding_request_id):
    """ubo_kyc_result_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.ubo_record (
                id, onboarding_request_id, first_name, last_name,
                control_type, kyc_result
            ) VALUES (%s, %s, 'Jane', 'Doe', 'DIRECT_OWNERSHIP', 'BOGUS_KYC')
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


def test_invalid_pep_status_enum_rejected(onboarding_request_id):
    """ubo_pep_status_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.ubo_record (
                id, onboarding_request_id, first_name, last_name,
                control_type, kyc_result, pep_status
            ) VALUES (
                %s, %s, 'Jane', 'Doe', 'DIRECT_OWNERSHIP', 'VERIFIED',
                'BOGUS_PEP'
            )
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


def test_invalid_document_type_enum_rejected(onboarding_request_id):
    """onboarding_document_type_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.onboarding_document (
                id, onboarding_request_id, document_type, storage_path,
                file_name, mime_type, size_bytes, validation_status
            ) VALUES (
                %s, %s, 'BOGUS_DOC_TYPE', '/path', 'doc.pdf',
                'application/pdf', 1024, 'PENDING'
            )
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


def test_invalid_validation_status_enum_rejected(onboarding_request_id):
    """onboarding_validation_status_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.onboarding_document (
                id, onboarding_request_id, document_type, storage_path,
                file_name, mime_type, size_bytes, validation_status
            ) VALUES (
                %s, %s, 'CERTIFICATE_OF_INCORPORATION', '/path', 'doc.pdf',
                'application/pdf', 1024, 'BOGUS_VALIDATION'
            )
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


def test_invalid_normalised_result_enum_rejected(onboarding_request_id):
    """kyb_normalised_result_enum rejects values outside the defined set."""
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            """
            INSERT INTO onboarding.kyb_vendor_result (
                id, onboarding_request_id, vendor_name, normalised_result
            ) VALUES (%s, %s, 'TestVendor', 'BOGUS_RESULT')
            """,
            (str(uuid.uuid4()), onboarding_request_id),
        )


# ── BUILD.md #12 audit: FK constraint tests ──────────────────────────────────


def test_ubo_record_fk_rejects_orphan():
    """FK on ubo_record.onboarding_request_id rejects non-existent parent."""
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _execute(
            """
            INSERT INTO onboarding.ubo_record (
                id, onboarding_request_id, first_name, last_name,
                control_type, kyc_result
            ) VALUES (%s, %s, 'Jane', 'Doe', 'DIRECT_OWNERSHIP', 'VERIFIED')
            """,
            (str(uuid.uuid4()), str(uuid.uuid4())),
        )


def test_onboarding_document_fk_rejects_orphan():
    """FK on onboarding_document.onboarding_request_id rejects non-existent parent."""
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _execute(
            """
            INSERT INTO onboarding.onboarding_document (
                id, onboarding_request_id, document_type, storage_path,
                file_name, mime_type, size_bytes, validation_status
            ) VALUES (
                %s, %s, 'CERTIFICATE_OF_INCORPORATION', '/path', 'doc.pdf',
                'application/pdf', 1024, 'PENDING'
            )
            """,
            (str(uuid.uuid4()), str(uuid.uuid4())),
        )


def test_onboarding_event_fk_rejects_orphan():
    """FK on onboarding_event.onboarding_request_id rejects non-existent parent."""
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _execute(
            """
            INSERT INTO onboarding.onboarding_event (
                id, onboarding_request_id, event_type
            ) VALUES (%s, %s, 'STATE_CHANGED')
            """,
            (str(uuid.uuid4()), str(uuid.uuid4())),
        )


def test_kyb_vendor_result_fk_rejects_orphan():
    """FK on kyb_vendor_result.onboarding_request_id rejects non-existent parent."""
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _execute(
            """
            INSERT INTO onboarding.kyb_vendor_result (
                id, onboarding_request_id, vendor_name, normalised_result
            ) VALUES (%s, %s, 'TestVendor', 'VERIFIED')
            """,
            (str(uuid.uuid4()), str(uuid.uuid4())),
        )


def test_onboarding_event_fk_restrict_prevents_parent_delete(onboarding_request_id):
    """FK RESTRICT on onboarding_event prevents deleting a request with events."""
    _execute(
        """
        INSERT INTO onboarding.onboarding_event (
            id, onboarding_request_id, event_type
        ) VALUES (%s, %s, 'STATE_CHANGED')
        """,
        (str(uuid.uuid4()), onboarding_request_id),
    )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _execute(
            "DELETE FROM onboarding.onboarding_request WHERE id = %s",
            (onboarding_request_id,),
        )


# ── Existing: immutability trigger tests ──────────────────────────────────────


def test_onboarding_request_field_immutability(onboarding_request_id):
    """Fields guarded by trg_onboarding_request_field_immutability are immutable once set."""

    # ── screening_result ──────────────────────────────────────────────────
    _execute(
        "UPDATE onboarding.onboarding_request "
        "SET screening_result = 'CLEAR' WHERE id = %s",
        (onboarding_request_id,),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET screening_result = 'REVIEW_REQUIRED' WHERE id = %s",
            (onboarding_request_id,),
        )
    assert "screening_result is immutable once set" in str(exc.value)

    # ── ubo_mapping ───────────────────────────────────────────────────────
    _execute(
        "UPDATE onboarding.onboarding_request "
        "SET ubo_mapping = '[{\"owner\": \"a\"}]' WHERE id = %s",
        (onboarding_request_id,),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET ubo_mapping = '[{\"owner\": \"b\"}]' WHERE id = %s",
            (onboarding_request_id,),
        )
    assert "ubo_mapping is immutable once set" in str(exc.value)

    # ── risk_rating_factors ───────────────────────────────────────────────
    _execute(
        "UPDATE onboarding.onboarding_request "
        "SET risk_rating_factors = '{\"score\": 42}' WHERE id = %s",
        (onboarding_request_id,),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.onboarding_request "
            "SET risk_rating_factors = '{\"score\": 99}' WHERE id = %s",
            (onboarding_request_id,),
        )
    assert "risk_rating_factors is immutable once set" in str(exc.value)


def test_ubo_record_created_at_immutability(onboarding_request_id):
    """UboRecord.created_at is immutable."""
    ubo_id = str(uuid.uuid4())
    _execute(
        """
        INSERT INTO onboarding.ubo_record (
            id, onboarding_request_id, first_name, last_name, control_type, kyc_result
        ) VALUES (
            %s, %s, 'Jane', 'Doe', 'DIRECT_OWNERSHIP', 'VERIFIED'
        )
        """,
        (ubo_id, onboarding_request_id),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.ubo_record SET created_at = now() WHERE id = %s",
            (ubo_id,),
        )
    assert "created_at is immutable once set" in str(exc.value)


def test_onboarding_document_submitted_at_immutability(onboarding_request_id):
    """OnboardingDocument.submitted_at is immutable once set."""
    doc_id = str(uuid.uuid4())
    _execute(
        """
        INSERT INTO onboarding.onboarding_document (
            id, onboarding_request_id, document_type, storage_path,
            file_name, mime_type, size_bytes, validation_status, submitted_at
        ) VALUES (
            %s, %s, 'CERTIFICATE_OF_INCORPORATION', '/path', 'doc.pdf',
            'application/pdf', 1024, 'PENDING', now()
        )
        """,
        (doc_id, onboarding_request_id),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.onboarding_document "
            "SET submitted_at = now() WHERE id = %s",
            (doc_id,),
        )
    assert "submitted_at is immutable once set" in str(exc.value)


def test_kyb_vendor_result_retrieved_at_immutability(onboarding_request_id):
    """KybVendorResult.retrieved_at is immutable once set."""
    result_id = str(uuid.uuid4())
    _execute(
        """
        INSERT INTO onboarding.kyb_vendor_result (
            id, onboarding_request_id, vendor_name, normalised_result, retrieved_at
        ) VALUES (
            %s, %s, 'Sumsub', 'VERIFIED', now()
        )
        """,
        (result_id, onboarding_request_id),
    )

    # Allowed mutation (non-guarded field)
    _execute(
        "UPDATE onboarding.kyb_vendor_result "
        "SET vendor_reference_id = 'new_ref' WHERE id = %s",
        (result_id,),
    )

    # Disallowed mutation
    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.kyb_vendor_result "
            "SET retrieved_at = now() WHERE id = %s",
            (result_id,),
        )
    assert "retrieved_at is immutable once set" in str(exc.value)


# ── Existing: append-only trigger ─────────────────────────────────────────────


def test_onboarding_event_append_only(onboarding_request_id):
    """OnboardingEvent is fully append-only — UPDATE and DELETE are rejected."""
    event_id = str(uuid.uuid4())
    _execute(
        """
        INSERT INTO onboarding.onboarding_event (
            id, onboarding_request_id, event_type
        ) VALUES (
            %s, %s, 'STATE_CHANGED'
        )
        """,
        (event_id, onboarding_request_id),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.onboarding_event "
            "SET event_type = 'MUTATED' WHERE id = %s",
            (event_id,),
        )

    err_str = str(exc.value).lower()
    assert "mutation" in err_str or "append-only" in err_str or "forbidden" in err_str

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "DELETE FROM onboarding.onboarding_event WHERE id = %s",
            (event_id,),
        )

    err_str = str(exc.value).lower()
    assert "mutation" in err_str or "append-only" in err_str or "forbidden" in err_str
