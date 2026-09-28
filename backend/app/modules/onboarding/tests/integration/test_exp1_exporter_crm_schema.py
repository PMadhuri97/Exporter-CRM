"""Direct-SQL constraint violation suite for EXP-1's schema
(``onboarding_0005_exporter_crm``).

Raw SQL on purpose, following ``test_s1t1_orchestration_schema.py``'s
established convention in this codebase (BUILD.md #12): inserting through the
ORM would prove only that SQLAlchemy declares a constraint, not that Postgres
enforces one. Every constraint the migration creates is violated here and
asserted rejected, and the boundary of each is exercised alongside it — a
constraint that rejects everything is as broken as one that rejects nothing.

The test database is shared across a whole run and is never reset, so every
test mints its own ids and none may assume an empty table.
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


_INSERT_PROFILE = """
    INSERT INTO onboarding.exporter_profile (
        id, customer_id, source, journey
    ) VALUES (%s, %s, %s, %s)
"""


@pytest.fixture
def exporter_profile():
    """Insert a valid exporter_profile and return (profile_id, customer_id)."""
    profile_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())
    _execute(_INSERT_PROFILE, (profile_id, customer_id, "SALES", "LEAD"))
    return profile_id, customer_id


# ── exporter_profile: uq_exporter_profile_customer_id ─────────────────────────


def test_exporter_profile_customer_id_unique_constraint(exporter_profile):
    _, customer_id = exporter_profile

    with pytest.raises(psycopg2.errors.UniqueViolation) as exc:
        _execute(
            _INSERT_PROFILE,
            (str(uuid.uuid4()), customer_id, "MANUAL", "LEAD"),
        )
    assert "uq_exporter_profile_customer_id" in str(exc.value)


# ── exporter_profile: source immutability ─────────────────────────────────────


def test_exporter_profile_source_immutability(exporter_profile):
    """trg_exporter_profile_source_immutability rejects changing `source`
    once set, but allows a no-op re-write of the same value (proving the
    trigger fires on an actual change, not on every UPDATE statement)."""
    profile_id, _ = exporter_profile

    # Allowed: re-writing the same value is not a change.
    _execute(
        "UPDATE onboarding.exporter_profile SET source = 'SALES' WHERE id = %s",
        (profile_id,),
    )

    # Rejected: an actual change.
    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.exporter_profile SET source = 'MANUAL' WHERE id = %s",
            (profile_id,),
        )
    assert "source is immutable once set" in str(exc.value)


def test_exporter_profile_invalid_source_enum_rejected():
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _INSERT_PROFILE,
            (str(uuid.uuid4()), str(uuid.uuid4()), "BOGUS_SOURCE", "LEAD"),
        )


def test_exporter_profile_invalid_journey_enum_rejected():
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _INSERT_PROFILE,
            (str(uuid.uuid4()), str(uuid.uuid4()), "SALES", "BOGUS_STATUS"),
        )


# ── exporter_contact: at most one primary per customer_id ─────────────────────


_INSERT_CONTACT = """
    INSERT INTO onboarding.exporter_contact (
        id, customer_id, name, is_primary_contact
    ) VALUES (%s, %s, %s, %s)
"""


def test_exporter_contact_primary_partial_unique_index(exporter_profile):
    _, customer_id = exporter_profile
    _execute(_INSERT_CONTACT, (str(uuid.uuid4()), customer_id, "Jane Doe", True))

    with pytest.raises(psycopg2.errors.UniqueViolation) as exc:
        _execute(_INSERT_CONTACT, (str(uuid.uuid4()), customer_id, "John Smith", True))
    assert "uq_exporter_contact_primary_per_customer" in str(exc.value)


def test_exporter_contact_multiple_non_primary_allowed(exporter_profile):
    """The partial index's boundary: it must not reject a second *non*-primary
    contact for the same customer_id — only a second primary."""
    _, customer_id = exporter_profile
    _execute(_INSERT_CONTACT, (str(uuid.uuid4()), customer_id, "Jane Doe", False))
    # Should not raise.
    _execute(_INSERT_CONTACT, (str(uuid.uuid4()), customer_id, "John Smith", False))


# ── exporter_activity: append-only ────────────────────────────────────────────


_INSERT_ACTIVITY = """
    INSERT INTO onboarding.exporter_activity (
        id, customer_id, activity_type, subject, actor_id, occurred_at
    ) VALUES (%s, %s, %s, %s, %s, now())
"""


def test_exporter_activity_append_only(exporter_profile):
    activity_id = str(uuid.uuid4())
    _, customer_id = exporter_profile
    _execute(
        _INSERT_ACTIVITY,
        (activity_id, customer_id, "CALL", "Intro call", "agent_1"),
    )

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "UPDATE onboarding.exporter_activity SET subject = 'Mutated' WHERE id = %s",
            (activity_id,),
        )
    err_str = str(exc.value).lower()
    assert "immutable" in err_str or "mutation" in err_str or "forbidden" in err_str

    with pytest.raises(psycopg2.errors.RaiseException) as exc:
        _execute(
            "DELETE FROM onboarding.exporter_activity WHERE id = %s",
            (activity_id,),
        )
    err_str = str(exc.value).lower()
    assert "immutable" in err_str or "mutation" in err_str or "forbidden" in err_str


def test_exporter_activity_invalid_activity_type_enum_rejected():
    with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
        _execute(
            _INSERT_ACTIVITY,
            (str(uuid.uuid4()), str(uuid.uuid4()), "BOGUS_TYPE", "x", "agent_1"),
        )
