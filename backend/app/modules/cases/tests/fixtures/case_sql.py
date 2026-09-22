"""Direct-SQL helpers shared by the case management constraint suites.

Raw SQL on purpose, following `customers/tests/fixtures/lifecycle_sql.py`'s
precedent exactly: inserting through the ORM would prove only that SQLAlchemy
declares a constraint, not that Postgres enforces one.

The test database is shared across a run and never reset, so every helper
mints its own identifiers and no test may assume an empty table.
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
#: plpgsql RAISE EXCEPTION — how every immutability/append-only trigger here
#: reports a rejection (both the shared public.prevent_mutation() and this
#: schema's own prevent_field_mutation_when_set()).
RAISED_EXCEPTION = "P0001"

Params = tuple | dict


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


def fetchone(query: str, params: Params = ()) -> tuple:
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def fetchall(query: str, params: Params = ()) -> list[tuple]:
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchall()
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


def case_reference() -> str:
    """A reference matching the CASE-{YYYY}-{sequential} format the schema enforces.

    Distinct per call, but not drawn from the real per-year counter — tests
    that need the trigger-generated value instead leave case_reference NULL on
    insert and read it back (see `test_case_reference_is_generated_when_absent`).
    """
    return f"CASE-2026-{uuid.uuid4().int % 10**9:09d}"


# ── Row builders ──────────────────────────────────────────────────────────────

INSERT_CASE = """
    INSERT INTO cases.compliance_case (
        id, case_reference, case_type, case_status, severity, priority,
        title, description, customer_id, settlement_id, onboarding_id,
        originating_epic, originating_event_type, originating_event_id,
        assigned_to, assigned_at, sla_deadline, sla_breached,
        resolution_action, resolution_note, resolution_approval_request_id,
        resolved_at, resolved_by
    ) VALUES (
        %(id)s, %(case_reference)s, %(case_type)s, %(case_status)s, %(severity)s,
        %(priority)s, %(title)s, %(description)s, %(customer_id)s,
        %(settlement_id)s, %(onboarding_id)s, %(originating_epic)s,
        %(originating_event_type)s, %(originating_event_id)s, %(assigned_to)s,
        %(assigned_at)s, %(sla_deadline)s, %(sla_breached)s,
        %(resolution_action)s, %(resolution_note)s,
        %(resolution_approval_request_id)s, %(resolved_at)s, %(resolved_by)s
    )
"""


def case_params(**overrides) -> dict:
    """A valid, minimal compliance_case row, with any column overridable by keyword."""
    params = {
        "id": str(uuid.uuid4()),
        "case_reference": case_reference(),
        "case_type": "TRANSACTION_FLAG",
        "case_status": "OPEN",
        "severity": "HIGH",
        "priority": 2,
        "title": "Fixture case",
        "description": "Created by the constraint test suite.",
        "customer_id": None,
        "settlement_id": None,
        "onboarding_id": None,
        "originating_epic": "Epic 2.4",
        "originating_event_type": "transaction.flagged",
        "originating_event_id": None,
        "assigned_to": None,
        "assigned_at": None,
        "sla_deadline": "2026-12-31T00:00:00+00:00",
        "sla_breached": False,
        "resolution_action": None,
        "resolution_note": None,
        "resolution_approval_request_id": None,
        "resolved_at": None,
        "resolved_by": None,
    }
    params.update(overrides)
    return params


INSERT_CASE_WITH_CREATED_AT = """
    INSERT INTO cases.compliance_case (
        id, case_reference, case_type, case_status, severity, priority,
        title, description, customer_id, settlement_id, onboarding_id,
        originating_epic, originating_event_type, originating_event_id,
        assigned_to, assigned_at, sla_deadline, sla_breached,
        resolution_action, resolution_note, resolution_approval_request_id,
        resolved_at, resolved_by, created_at
    ) VALUES (
        %(id)s, %(case_reference)s, %(case_type)s, %(case_status)s, %(severity)s,
        %(priority)s, %(title)s, %(description)s, %(customer_id)s,
        %(settlement_id)s, %(onboarding_id)s, %(originating_epic)s,
        %(originating_event_type)s, %(originating_event_id)s, %(assigned_to)s,
        %(assigned_at)s, %(sla_deadline)s, %(sla_breached)s,
        %(resolution_action)s, %(resolution_note)s,
        %(resolution_approval_request_id)s, %(resolved_at)s, %(resolved_by)s,
        %(created_at)s
    )
"""


def insert_case(**overrides) -> dict:
    """Insert one `compliance_case` row.

    `created_at` is a keyword-only extra, not part of `case_params`'s dict:
    omitted, the column is left out of the INSERT and the table's own
    `server_default=func.now()` fills it, exactly as every existing caller
    expects. Passed explicitly (e.g. by
    `test_s5t2_sla_monitoring_detection.py`'s auto-escalation-threshold tests,
    which need a case created far enough in the past that "75% of the SLA
    window" has already elapsed), `INSERT_CASE_WITH_CREATED_AT` is used
    instead — not a later `UPDATE`, since `compliance_case.created_at` is
    immutable once set (the field-mutation-prevention trigger this module's
    own docstring documents) and a raw `UPDATE` after insert would simply be
    rejected.
    """
    created_at = overrides.pop("created_at", None)
    params = case_params(**overrides)

    if created_at is not None:
        params["created_at"] = created_at
        execute(INSERT_CASE_WITH_CREATED_AT, params)
    else:
        execute(INSERT_CASE, params)
    return params


def insert_timeline_event(case_id: str, **overrides) -> dict:
    """Insert one `case_timeline_event` row.

    `occurred_at` is a keyword-only extra, not part of the base params dict:
    omitted, the column is left out of the INSERT entirely so the table's own
    `server_default=func.now()` fills it — the original behaviour every
    existing caller relies on. Passed explicitly (e.g. by
    `test_s6t1_case_reports.py`'s resolution-audit ordering tests, which need
    several events in a deterministic, non-`now()` order), it is added to the
    column list instead, so a caller can build a timeline with events several
    minutes apart without sleeping between inserts.
    """
    occurred_at = overrides.pop("occurred_at", None)
    params = {
        "id": str(uuid.uuid4()),
        "case_id": case_id,
        "event_type": "CASE_CREATED",
        "from_status": None,
        "to_status": "OPEN",
        "actor_id": "system",
        "actor_type": "SYSTEM",
        "note": None,
    }
    params.update(overrides)

    occurred_at_column = ""
    occurred_at_value = ""
    if occurred_at is not None:
        params["occurred_at"] = occurred_at
        occurred_at_column = ", occurred_at"
        occurred_at_value = ", %(occurred_at)s"

    execute(
        f"""
        INSERT INTO cases.case_timeline_event (
            id, case_id, event_type, from_status, to_status, actor_id,
            actor_type, note{occurred_at_column}
        ) VALUES (
            %(id)s, %(case_id)s, %(event_type)s, %(from_status)s, %(to_status)s,
            %(actor_id)s, %(actor_type)s, %(note)s{occurred_at_value}
        )
        """,
        params,
    )
    return params


def insert_evidence_item(case_id: str, **overrides) -> dict:
    params = {
        "id": str(uuid.uuid4()),
        "case_id": case_id,
        "evidence_type": "SCREENING_RESULT",
        "source_epic": "Epic 2.4",
        "source_reference_id": str(uuid.uuid4()),
        "evidence_data": "{}",
        "added_by": "compliance.officer",
        "is_key_evidence": False,
    }
    params.update(overrides)
    execute(
        """
        INSERT INTO cases.case_evidence_item (
            id, case_id, evidence_type, source_epic, source_reference_id,
            evidence_data, added_by, is_key_evidence
        ) VALUES (
            %(id)s, %(case_id)s, %(evidence_type)s, %(source_epic)s,
            %(source_reference_id)s, %(evidence_data)s::jsonb, %(added_by)s,
            %(is_key_evidence)s
        )
        """,
        params,
    )
    return params
