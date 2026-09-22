"""Direct-SQL test for ``onboarding_0007_reg_optional``: the database itself
must accept a NULL ``registration_number``/``registered_address``, not just
"the service didn't crash" — following ``test_exp1_exporter_crm_schema.py``'s
established convention (BUILD.md #12) of proving a constraint (or, here, the
deliberate absence of one) directly against Postgres rather than through the
ORM.
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


_INSERT_BARE_LEAD = """
    INSERT INTO onboarding.onboarding_request (
        id, tenant_id, idempotency_key, customer_id, status, entity_type,
        legal_name, registration_number, incorporation_country,
        registered_address, initial_user_id
    ) VALUES (%s, %s, %s, %s, 'DRAFT', 'CORPORATION', %s, NULL, %s, NULL, %s)
"""


def test_onboarding_request_accepts_null_registration_number_and_address():
    """The exact acceptance criterion: Postgres genuinely accepts a NULL
    registration_number/registered_address for a bare Lead row — this is a
    raw-SQL insert, not a round trip through the ORM/service layer."""
    request_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())

    # Should not raise.
    _execute(
        _INSERT_BARE_LEAD,
        (
            request_id,
            tenant_id,
            str(uuid.uuid4()),
            customer_id,
            f"Bare Lead Co {uuid.uuid4().hex[:8]}",
            "US",
            "lead-intake@example.com",
        ),
    )

    conn = _pg_connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT registration_number, registered_address FROM onboarding.onboarding_request "
            "WHERE id = %s",
            (request_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    assert row == (None, None)


def test_onboarding_request_still_rejects_null_incorporation_country():
    """The boundary: `incorporation_country` deliberately stayed NOT NULL —
    only `registration_number`/`registered_address` were loosened."""
    with pytest.raises(psycopg2.errors.NotNullViolation):
        _execute(
            """
            INSERT INTO onboarding.onboarding_request (
                id, tenant_id, idempotency_key, customer_id, status, entity_type,
                legal_name, registration_number, incorporation_country,
                registered_address, initial_user_id
            ) VALUES (%s, %s, %s, %s, 'DRAFT', 'CORPORATION', %s, NULL, NULL, NULL, %s)
            """,
            (
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                f"No Country Co {uuid.uuid4().hex[:8]}",
                "lead-intake@example.com",
            ),
        )
