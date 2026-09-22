"""Direct-SQL helpers shared by the review lifecycle constraint suites.

These issue raw statements on their own psycopg2 connections rather than going
through the ORM. A constraint suite that inserted through SQLAlchemy would prove
only that the model declares a constraint, not that Postgres enforces one.

Each helper commits on its own connection, so a rejected statement leaves no
aborted transaction behind for the next assertion.
"""
import uuid

import psycopg2
import pytest

from app.platform.configuration.config import get_settings

# ── SQLSTATE codes ────────────────────────────────────────────────────────────

NOT_NULL_VIOLATION = "23502"
FOREIGN_KEY_VIOLATION = "23503"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
INVALID_TEXT_REPRESENTATION = "22P02"
#: plpgsql RAISE EXCEPTION — how both immutability triggers report a rejection.
RAISED_EXCEPTION = "P0001"

# psycopg2 binds either positional or named parameters; both are used here.
Params = tuple | dict

#: Exactly at the rationale floor, and a real sentence rather than padding.
RATIONALE_50 = "The registry confirmed every director and owner unchanged."


def connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def execute(query: str, params: Params = ()) -> None:
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def rejects(sqlstate: str, query: str, params: Params = ()) -> None:
    """Assert the statement is rejected by the database with this SQLSTATE."""
    with pytest.raises(psycopg2.Error) as exc:
        execute(query, params)
    assert exc.value.pgcode == sqlstate, (
        f"expected SQLSTATE {sqlstate}, got {exc.value.pgcode}: {exc.value}"
    )


def ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def review_ref() -> str:
    """A reference matching the REV-{YYYY}-{sequential} format the schema enforces."""
    return f"REV-2026-{uuid.uuid4().int % 10**9:09d}"


# ── Row builders ──────────────────────────────────────────────────────────────


def insert_customer() -> str:
    customer_id = str(uuid.uuid4())
    execute(
        """
        INSERT INTO customers.customers (
            customer_id, entity_name, entity_type, kyb_status, risk_rating
        ) VALUES (%s, 'Fixture Trading Ltd', 'BUYER', 'VERIFIED', 'LOW')
        """,
        (customer_id,),
    )
    return customer_id


def insert_snapshot(customer_id: str) -> str:
    snapshot_ref = ref("SNAP")
    execute(
        """
        INSERT INTO customers.customer_baseline_snapshot (
            id, snapshot_ref, customer_id, snapshot_reason, legal_name, risk_rating
        ) VALUES (%s, %s, %s, 'ONBOARDING_COMPLETED', 'Fixture Trading Ltd', 'LOW')
        """,
        (str(uuid.uuid4()), snapshot_ref, customer_id),
    )
    return snapshot_ref


def insert_trigger_definition(auto_restrict: bool = False) -> str:
    trigger_code = ref("TRG")
    execute(
        """
        INSERT INTO customers.review_trigger_definition (
            id, trigger_code, description, source_epic, event_type,
            severity, review_action, auto_restrict, restriction_level,
            active, effective_from
        ) VALUES (%s, %s, 'Sanctions match on ongoing monitoring', 'Epic 3.2',
                  'screening.hit.confirmed', 'CRITICAL', 'IMMEDIATE_REVIEW',
                  %s, %s, true, DATE '2026-01-01')
        """,
        (
            str(uuid.uuid4()),
            trigger_code,
            auto_restrict,
            "FULL_BLOCK" if auto_restrict else None,
        ),
    )
    return trigger_code


INSERT_REVIEW = """
    INSERT INTO customers.customer_review (
        id, review_ref, customer_id, review_type, trigger_code,
        initiated_at, initiated_by, due_by, status, baseline_snapshot_ref,
        material_change_count, risk_rating_before, risk_rating_after,
        rating_changed, outcome, outcome_rationale, approval_request_id,
        completed_at, completed_by
    ) VALUES (
        %(id)s, %(review_ref)s, %(customer_id)s, %(review_type)s, %(trigger_code)s,
        now(), 'scheduler', now() + interval '30 days', %(status)s,
        %(baseline_snapshot_ref)s, %(material_change_count)s, 'LOW',
        %(risk_rating_after)s, %(rating_changed)s, %(outcome)s,
        %(outcome_rationale)s, %(approval_request_id)s, %(completed_at)s,
        %(completed_by)s
    )
"""


def review_params(**overrides) -> dict:
    """A valid, minimal review, with any column overridable by keyword."""
    params = {
        "id": str(uuid.uuid4()),
        "review_ref": review_ref(),
        "customer_id": None,
        "review_type": "PERIODIC",
        "trigger_code": None,
        "status": "INITIATED",
        "baseline_snapshot_ref": None,
        "material_change_count": 0,
        "risk_rating_after": None,
        "rating_changed": False,
        "outcome": None,
        "outcome_rationale": None,
        "approval_request_id": None,
        "completed_at": None,
        "completed_by": None,
    }
    params.update(overrides)
    return params


def insert_review(**overrides) -> dict:
    params = review_params(**overrides)
    execute(INSERT_REVIEW, params)
    return params
