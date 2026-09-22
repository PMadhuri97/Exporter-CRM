"""Direct-SQL constraint suite for the case management schema (ANER-4.3-S1T1).

Raw SQL on purpose, following customers/tests/integration/
test_s1t1_review_lifecycle_schema.py's precedent: inserting through the ORM
would prove only that SQLAlchemy declares a constraint, not that Postgres
enforces one. Every constraint and trigger cases_0001_case_management creates
is violated here and asserted rejected, and the boundary of each is exercised
alongside it.

The test database is shared across a run and never reset, so every test mints
its own identifiers and none may assume an empty table.
"""
import uuid

import pytest

from app.modules.cases.tests.fixtures.case_sql import (
    CHECK_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    INSERT_CASE,
    INVALID_TEXT_REPRESENTATION,
    RAISED_EXCEPTION,
    UNIQUE_VIOLATION,
    case_params,
    case_reference,
    execute,
    fetchone,
    insert_case,
    insert_evidence_item,
    insert_timeline_event,
    rejects,
)

# ── compliance_case: all four tables exist with all fields ────────────────────


def test_a_minimal_case_is_accepted():
    case = insert_case()
    row = fetchone(
        "SELECT case_reference, case_type, case_status, severity, priority, "
        "title, description, originating_epic, originating_event_type, "
        "sla_deadline, sla_breached, evidence_package, created_at, "
        "last_updated_at FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row is not None
    assert row[0] == case["case_reference"]


def test_every_case_type_is_accepted():
    for case_type in (
        "SCREENING_REVIEW", "TRANSACTION_FLAG", "RECONCILIATION_BREAK",
        "RECONCILIATION_TIMEOUT", "ONBOARDING_REVIEW", "TRAVEL_RULE_REVIEW",
        "ON_CHAIN_ESCALATION", "WEBHOOK_DELIVERY_FAILURE", "MANUAL",
    ):
        insert_case(case_type=case_type)


def test_onboarding_intake_case_type_is_accepted_with_no_sla_deadline():
    """ONBOARDING_INTAKE (ANER-4.3-S2) is deliberately not in the loop above:
    unlike every other case_type, it is required to carry a NULL
    sla_deadline (ck_compliance_case_intake_has_no_sla_deadline), so it needs
    its own fixture override rather than the shared default."""
    insert_case(case_type="ONBOARDING_INTAKE", sla_deadline=None)


def test_every_case_status_is_accepted():
    for case_status in (
        "OPEN", "ASSIGNED", "UNDER_INVESTIGATION", "PENDING_EXTERNAL",
        "PENDING_APPROVAL", "RESOLVED", "ESCALATED", "CLOSED_WITHOUT_ACTION",
    ):
        insert_case(case_status=case_status)


def test_every_severity_is_accepted():
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        insert_case(severity=severity)


def test_a_case_can_carry_a_customer_settlement_and_onboarding_subject():
    """No FK on the subject columns (documented gap), but all three are settable."""
    case = insert_case(
        customer_id=str(uuid.uuid4()),
        settlement_id=str(uuid.uuid4()),
        onboarding_id=str(uuid.uuid4()),
    )
    row = fetchone(
        "SELECT customer_id, settlement_id, onboarding_id FROM cases.compliance_case "
        "WHERE id = %s",
        (case["id"],),
    )
    assert str(row[0]) == case["customer_id"]
    assert str(row[1]) == case["settlement_id"]
    assert str(row[2]) == case["onboarding_id"]


def test_a_resolved_case_carries_its_resolution():
    case = insert_case(
        resolution_action="NO_ACTION_REQUIRED",
        resolution_note="Reviewed; no discrepancy found.",
        resolved_at="2026-09-17T10:00:00+00:00",
        resolved_by="compliance.officer",
    )
    row = fetchone(
        "SELECT resolution_action, resolution_note, resolved_by "
        "FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row == ("NO_ACTION_REQUIRED", "Reviewed; no discrepancy found.", "compliance.officer")


# ── case_reference: identity and generation ────────────────────────────────────


def test_duplicate_case_reference_is_rejected():
    """AC: case_reference uniqueness verified (duplicate insert via raw SQL rejected)."""
    case = insert_case()
    rejects(
        UNIQUE_VIOLATION,
        INSERT_CASE,
        case_params(case_reference=case["case_reference"]),
    )


def test_malformed_case_reference_is_rejected():
    rejects(CHECK_VIOLATION, INSERT_CASE, case_params(case_reference="CASE-1"))


def test_case_reference_is_generated_when_absent():
    """The database trigger fills case_reference matching CASE-{YYYY}-{seq} when
    the caller leaves it NULL."""
    params = case_params(id=str(uuid.uuid4()))
    params["case_reference"] = None
    execute(INSERT_CASE, params)

    row = fetchone(
        "SELECT case_reference FROM cases.compliance_case WHERE id = %s",
        (params["id"],),
    )
    assert row[0] is not None
    assert row[0].startswith("CASE-")


def test_two_generated_references_in_the_same_year_are_distinct_and_sequential():
    params_a = case_params(id=str(uuid.uuid4()))
    params_a["case_reference"] = None
    execute(INSERT_CASE, params_a)

    params_b = case_params(id=str(uuid.uuid4()))
    params_b["case_reference"] = None
    execute(INSERT_CASE, params_b)

    row_a = fetchone(
        "SELECT case_reference FROM cases.compliance_case WHERE id = %s", (params_a["id"],)
    )
    row_b = fetchone(
        "SELECT case_reference FROM cases.compliance_case WHERE id = %s", (params_b["id"],)
    )
    assert row_a[0] != row_b[0]

    seq_a = int(row_a[0].rsplit("-", 1)[1])
    seq_b = int(row_b[0].rsplit("-", 1)[1])
    assert seq_b == seq_a + 1


def test_an_explicit_case_reference_is_not_overwritten():
    explicit = case_reference()
    case = insert_case(case_reference=explicit)
    row = fetchone(
        "SELECT case_reference FROM cases.compliance_case WHERE id = %s", (case["id"],)
    )
    assert row[0] == explicit


# ── originating_event_id: idempotency guard ────────────────────────────────────


def test_duplicate_originating_event_id_is_rejected():
    """AC: originating_event_id uniqueness verified."""
    event_id = str(uuid.uuid4())
    insert_case(originating_event_id=event_id)
    rejects(
        UNIQUE_VIOLATION,
        INSERT_CASE,
        case_params(originating_event_id=event_id),
    )


def test_two_cases_with_no_originating_event_id_are_both_accepted():
    """The idempotency guard is a partial unique index: NULL is not "duplicated"."""
    insert_case(originating_event_id=None)
    insert_case(originating_event_id=None)


# ── priority range ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("priority", [0, 6, -1])
def test_priority_outside_one_to_five_is_rejected(priority):
    rejects(CHECK_VIOLATION, INSERT_CASE, case_params(priority=priority))


@pytest.mark.parametrize("priority", [1, 2, 3, 4, 5])
def test_priority_within_one_to_five_is_accepted(priority):
    insert_case(priority=priority)


# ── resolution_note: required whenever resolution_action is set ───────────────


def test_resolution_action_with_null_note_is_rejected():
    """AC: resolution_action with null resolution_note is rejected at DB level."""
    rejects(
        CHECK_VIOLATION,
        INSERT_CASE,
        case_params(resolution_action="NO_ACTION_REQUIRED", resolution_note=None),
    )


def test_resolution_action_with_empty_note_is_rejected():
    """AC: resolution_action with empty resolution_note is rejected at DB level."""
    rejects(
        CHECK_VIOLATION,
        INSERT_CASE,
        case_params(resolution_action="NO_ACTION_REQUIRED", resolution_note=""),
    )


def test_resolution_action_with_whitespace_only_note_is_rejected():
    rejects(
        CHECK_VIOLATION,
        INSERT_CASE,
        case_params(resolution_action="NO_ACTION_REQUIRED", resolution_note="   "),
    )


def test_resolution_action_with_a_real_note_is_accepted():
    insert_case(resolution_action="NO_ACTION_REQUIRED", resolution_note="Closed, no issue.")


def test_no_resolution_action_needs_no_note():
    insert_case(resolution_action=None, resolution_note=None)


def test_a_note_with_no_resolution_action_is_permitted():
    """The constraint binds the note to the action, not the other way round."""
    insert_case(resolution_action=None, resolution_note="A note left before resolving.")


# ── ck_compliance_case_intake_has_no_sla_deadline (ANER-4.3-S2) ────────────────


def test_onboarding_intake_case_with_a_sla_deadline_is_rejected():
    """AC: an ONBOARDING_INTAKE case has no SLA yet — the database rejects one
    inserted with a non-null sla_deadline."""
    rejects(CHECK_VIOLATION, INSERT_CASE, case_params(case_type="ONBOARDING_INTAKE"))


def test_onboarding_intake_case_with_no_sla_deadline_is_accepted():
    case = insert_case(case_type="ONBOARDING_INTAKE", sla_deadline=None)
    row = fetchone(
        "SELECT case_type, sla_deadline FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )
    assert row == ("ONBOARDING_INTAKE", None)


def test_onboarding_intake_case_cannot_be_updated_to_carry_a_sla_deadline():
    """The constraint is checked on UPDATE too, not just INSERT."""
    case = insert_case(case_type="ONBOARDING_INTAKE", sla_deadline=None)
    rejects(
        CHECK_VIOLATION,
        "UPDATE cases.compliance_case SET sla_deadline = now() WHERE id = %s",
        (case["id"],),
    )


def test_non_intake_case_type_may_still_have_a_null_sla_deadline_at_the_db_level():
    """The constraint is one-directional: it forbids ONBOARDING_INTAKE from
    having a deadline, it does not require every other case_type to have one.
    NOT NULL was dropped from the column for every case_type when it was
    dropped for this one — requiring a deadline for non-intake cases remains
    an application-layer responsibility, not a schema one (see
    cases_0003_intake_sla_null's module docstring)."""
    insert_case(case_type="TRANSACTION_FLAG", sla_deadline=None)


# ── enum validation ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "column, value",
    [
        ("case_type", "NOT_A_TYPE"),
        ("case_status", "IN_LIMBO"),
        ("severity", "URGENT"),
        ("resolution_action", "DO_SOMETHING"),
    ],
)
def test_invalid_enum_value_is_rejected(column, value):
    rejects(INVALID_TEXT_REPRESENTATION, INSERT_CASE, case_params(**{column: value}))


# ── compliance_case: column immutability trigger ───────────────────────────────


def test_id_cannot_be_rewritten():
    case = insert_case()
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.compliance_case SET id = %s WHERE id = %s",
        (str(uuid.uuid4()), case["id"]),
    )


def test_case_reference_cannot_be_rewritten():
    case = insert_case()
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.compliance_case SET case_reference = %s WHERE id = %s",
        (case_reference(), case["id"]),
    )


def test_created_at_cannot_be_rewritten():
    case = insert_case()
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.compliance_case SET created_at = now() WHERE id = %s",
        (case["id"],),
    )


def test_resolved_at_and_resolved_by_can_be_written_once():
    case = insert_case()
    execute(
        "UPDATE cases.compliance_case SET resolution_action = 'NO_ACTION_REQUIRED', "
        "resolution_note = 'Closed.', resolved_at = now(), "
        "resolved_by = 'compliance.officer' WHERE id = %s",
        (case["id"],),
    )
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.compliance_case SET resolved_by = 'someone.else' WHERE id = %s",
        (case["id"],),
    )
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.compliance_case SET resolved_at = now() WHERE id = %s",
        (case["id"],),
    )


def test_case_status_remains_writable():
    """The trigger guards identity and resolution, not the lifecycle itself."""
    case = insert_case()
    execute(
        "UPDATE cases.compliance_case SET case_status = 'UNDER_INVESTIGATION' WHERE id = %s",
        (case["id"],),
    )
    row = fetchone(
        "SELECT case_status FROM cases.compliance_case WHERE id = %s", (case["id"],)
    )
    assert row[0] == "UNDER_INVESTIGATION"


def test_last_updated_at_remains_writable():
    case = insert_case()
    execute(
        "UPDATE cases.compliance_case SET last_updated_at = now() WHERE id = %s",
        (case["id"],),
    )


# ── case_timeline_event: append-only ───────────────────────────────────────────


def test_timeline_event_rejects_update():
    case = insert_case()
    event = insert_timeline_event(case["id"])
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.case_timeline_event SET note = 'edited' WHERE id = %s",
        (event["id"],),
    )


def test_timeline_event_rejects_delete():
    case = insert_case()
    event = insert_timeline_event(case["id"])
    rejects(
        RAISED_EXCEPTION,
        "DELETE FROM cases.case_timeline_event WHERE id = %s",
        (event["id"],),
    )


def test_timeline_event_for_an_unknown_case_is_rejected():
    rejects(
        FOREIGN_KEY_VIOLATION,
        "INSERT INTO cases.case_timeline_event ("
        " id, case_id, event_type, to_status, actor_id, actor_type"
        ") VALUES (%s, %s, 'CASE_CREATED', 'OPEN', 'system', 'SYSTEM')",
        (str(uuid.uuid4()), str(uuid.uuid4())),
    )


def test_every_timeline_event_type_is_accepted():
    case = insert_case()
    for event_type in (
        "CASE_CREATED", "ASSIGNED", "STATUS_CHANGED", "NOTE_ADDED",
        "EVIDENCE_UPDATED", "ESCALATED", "APPROVAL_REQUESTED",
        "APPROVAL_RECEIVED", "APPROVAL_REJECTED", "RESOLVED", "CLOSED",
    ):
        insert_timeline_event(case["id"], event_type=event_type)


def test_every_actor_type_is_accepted():
    case = insert_case()
    for actor_type in (
        "COMPLIANCE_OFFICER", "OPERATIONS_OFFICER", "SYSTEM", "EXTERNAL_APPROVER",
    ):
        insert_timeline_event(case["id"], actor_type=actor_type)


def test_a_case_referenced_by_a_timeline_event_cannot_be_deleted():
    case = insert_case()
    insert_timeline_event(case["id"])
    rejects(
        FOREIGN_KEY_VIOLATION,
        "DELETE FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )


# ── case_evidence_item ──────────────────────────────────────────────────────────


def test_every_evidence_type_is_accepted():
    case = insert_case()
    for evidence_type in (
        "SCREENING_RESULT", "KYB_RESULT", "ONBOARDING_EVIDENCE",
        "DECISIONING_RESULT", "LIMITS_CHECK", "FX_RATE_DATA",
        "RECONCILIATION_DATA", "TRAVEL_RULE_DATA", "ON_CHAIN_ASSESSMENT",
        "REACTOR_INVESTIGATION", "SETTLEMENT_RECORD", "MANUAL_ATTACHMENT",
        # RXIL-specific additions (ANER-4.3-S2T2, cases_0004_rxil_evidence).
        "DUPLICATION_CHECK", "VESSEL_TRACKING", "BILL_OF_LADING",
        "BUYER_RATING", "INSURANCE_CERTIFICATE",
    ):
        insert_evidence_item(case["id"], evidence_type=evidence_type)


def test_evidence_item_for_an_unknown_case_is_rejected():
    rejects(
        FOREIGN_KEY_VIOLATION,
        "INSERT INTO cases.case_evidence_item ("
        " id, case_id, evidence_type, source_epic, source_reference_id,"
        " evidence_data, added_by"
        ") VALUES (%s, %s, 'SCREENING_RESULT', 'Epic 2.4', %s, '{}'::jsonb, 'x')",
        (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())),
    )


def test_added_at_cannot_be_rewritten():
    case = insert_case()
    item = insert_evidence_item(case["id"])
    rejects(
        RAISED_EXCEPTION,
        "UPDATE cases.case_evidence_item SET added_at = now() WHERE id = %s",
        (item["id"],),
    )


def test_is_key_evidence_remains_writable():
    """Only added_at is guarded — an analyst may still triage the flag afterwards."""
    case = insert_case()
    item = insert_evidence_item(case["id"], is_key_evidence=False)
    execute(
        "UPDATE cases.case_evidence_item SET is_key_evidence = true WHERE id = %s",
        (item["id"],),
    )
    row = fetchone(
        "SELECT is_key_evidence FROM cases.case_evidence_item WHERE id = %s", (item["id"],)
    )
    assert row[0] is True


def test_a_case_referenced_by_evidence_cannot_be_deleted():
    case = insert_case()
    insert_evidence_item(case["id"])
    rejects(
        FOREIGN_KEY_VIOLATION,
        "DELETE FROM cases.compliance_case WHERE id = %s",
        (case["id"],),
    )


# ── case_sla_config: fields and uniqueness ──────────────────────────────────────


#: A real case_type recognised by ck_case_sla_config_case_type, used wherever a
#: test wants to isolate a *different* constraint (severity / sla_hours /
#: auto_escalate_at_pct) rather than incidentally tripping this one too — Postgres
#: reports every violated CHECK as the same 23514 SQLSTATE, so a test using an
#: invalid case_type would "pass" for the wrong reason.
#:
#: MANUAL specifically, not any of the other eight: sla_config_loader.
#: load_sla_config_table wipes and re-seeds case_sla_config with the full
#: production sla-config.yaml — which covers every (case_type, severity) pair
#: *except* MANUAL (see that file's trailing comment). A test that inserts a
#: fresh row under, say, RECONCILIATION_BREAK/HIGH would collide with
#: uq_case_sla_config_type_severity the moment it runs after
#: test_s1t2_sla_seed_loading has seeded the table — order-dependent in a
#: single run and near-certain on a shared, never-reset database across runs.
#: MANUAL is the one pair the production loader guarantees never to touch.
_VALID_CASE_TYPE = "MANUAL"


def _clear_manual_config(severity: str) -> None:
    """Delete any existing (MANUAL, severity) row before a test inserts one.

    Even MANUAL is not immune to a re-run: unlike review_trigger_definition's
    free-form trigger_code, case_sla_config's natural key is a closed
    (case_type, severity) vocabulary, so a test cannot mint a fresh one the way
    `ref()` does elsewhere in this suite. Without this, re-running this test
    file against the same never-reset database a second time would collide
    with the row the first run committed.
    """
    execute(
        "DELETE FROM cases.case_sla_config WHERE case_type = %s AND severity = %s",
        (_VALID_CASE_TYPE, severity),
    )


def test_case_sla_config_accepts_a_row():
    _clear_manual_config("CRITICAL")
    config_id = str(uuid.uuid4())
    execute(
        "INSERT INTO cases.case_sla_config ("
        " id, case_type, severity, sla_hours, auto_escalate_at_pct"
        ") VALUES (%s, %s, %s, %s, %s)",
        (config_id, _VALID_CASE_TYPE, "CRITICAL", 1, 75),
    )
    row = fetchone(
        "SELECT case_type, severity, sla_hours, auto_escalate_at_pct "
        "FROM cases.case_sla_config WHERE id = %s",
        (config_id,),
    )
    assert row == (_VALID_CASE_TYPE, "CRITICAL", 1, 75)


def test_duplicate_case_type_severity_pair_is_rejected():
    _clear_manual_config("HIGH")
    pair = (_VALID_CASE_TYPE, "HIGH")
    execute(
        "INSERT INTO cases.case_sla_config (id, case_type, severity, sla_hours, "
        "auto_escalate_at_pct) VALUES (%s, %s, %s, 4, 75)",
        (str(uuid.uuid4()), *pair),
    )
    rejects(
        UNIQUE_VIOLATION,
        "INSERT INTO cases.case_sla_config (id, case_type, severity, sla_hours, "
        "auto_escalate_at_pct) VALUES (%s, %s, %s, 8, 75)",
        (str(uuid.uuid4()), *pair),
    )


def test_case_sla_config_rejects_an_unrecognised_case_type():
    rejects(
        CHECK_VIOLATION,
        "INSERT INTO cases.case_sla_config (id, case_type, severity, sla_hours, "
        "auto_escalate_at_pct) VALUES (%s, 'NOT_A_TYPE', 'HIGH', 4, 75)",
        (str(uuid.uuid4()),),
    )


def test_case_sla_config_rejects_an_unrecognised_severity():
    rejects(
        CHECK_VIOLATION,
        "INSERT INTO cases.case_sla_config (id, case_type, severity, sla_hours, "
        "auto_escalate_at_pct) VALUES (%s, %s, 'URGENT', 4, 75)",
        (str(uuid.uuid4()), _VALID_CASE_TYPE),
    )


def test_case_sla_config_rejects_non_positive_sla_hours():
    rejects(
        CHECK_VIOLATION,
        "INSERT INTO cases.case_sla_config (id, case_type, severity, sla_hours, "
        "auto_escalate_at_pct) VALUES (%s, %s, 'HIGH', 0, 75)",
        (str(uuid.uuid4()), _VALID_CASE_TYPE),
    )


def test_case_sla_config_rejects_pct_outside_1_to_100():
    rejects(
        CHECK_VIOLATION,
        "INSERT INTO cases.case_sla_config (id, case_type, severity, sla_hours, "
        "auto_escalate_at_pct) VALUES (%s, %s, 'HIGH', 4, 101)",
        (str(uuid.uuid4()), _VALID_CASE_TYPE),
    )


# ── migration history is queryable ──────────────────────────────────────────────


def test_migration_history_is_queryable():
    """AC: migration history queryable. The revision this suite depends on is
    recorded and reachable from `alembic_version` (which always holds the
    current head, not the full history — history itself is queryable through
    the migration scripts, `alembic history`)."""
    row = fetchone("SELECT version_num FROM public.alembic_version")
    assert row is not None
    assert row[0] is not None
