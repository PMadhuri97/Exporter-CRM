"""Direct-SQL constraint suite for the review lifecycle schema.

Raw SQL on purpose: inserting through the ORM would prove only that SQLAlchemy
declares a constraint, not that Postgres enforces one. Every constraint and
trigger the migration creates is violated here and asserted rejected, and the
boundary of each is exercised alongside it — a constraint that rejects
everything is as broken as one that rejects nothing.

The test database is shared across a run and never reset, so every test mints
its own identifiers and none may assume an empty table.
"""
import uuid

import pytest

from app.modules.customers.tests.fixtures.lifecycle_sql import (
    CHECK_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    INSERT_REVIEW,
    INVALID_TEXT_REPRESENTATION,
    NOT_NULL_VIOLATION,
    RAISED_EXCEPTION,
    RATIONALE_50,
    UNIQUE_VIOLATION,
    execute,
    insert_customer,
    insert_review,
    insert_snapshot,
    insert_trigger_definition,
    ref,
    rejects,
    review_params,
    review_ref,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def customer_id() -> str:
    return insert_customer()


@pytest.fixture
def snapshot_ref(customer_id: str) -> str:
    return insert_snapshot(customer_id)


# ── review_schedule ───────────────────────────────────────────────────────────

_INSERT_SCHEDULE = """
    INSERT INTO customers.review_schedule (
        id, customer_id, current_risk_rating, review_frequency_months,
        next_review_due, grace_period_days, overdue, schedule_status,
        accelerated_from, acceleration_reason
    ) VALUES (%s, %s, 'MEDIUM', %s, %s, %s, false, 'SCHEDULED', %s, %s)
"""


def _schedule_args(customer: str, **kw) -> tuple:
    return (
        str(uuid.uuid4()),
        customer,
        kw.get("frequency", 12),
        kw.get("next_review_due", "2027-01-01"),
        kw.get("grace_period_days", 30),
        kw.get("accelerated_from"),
        kw.get("acceleration_reason"),
    )


def test_one_live_schedule_per_customer(customer_id):
    execute(_INSERT_SCHEDULE, _schedule_args(customer_id))
    rejects(UNIQUE_VIOLATION, _INSERT_SCHEDULE, _schedule_args(customer_id))


def test_a_second_customer_gets_its_own_schedule(customer_id):
    execute(_INSERT_SCHEDULE, _schedule_args(customer_id))
    execute(_INSERT_SCHEDULE, _schedule_args(insert_customer()))


def test_schedule_without_a_due_date_is_rejected(customer_id):
    rejects(
        NOT_NULL_VIOLATION,
        _INSERT_SCHEDULE,
        _schedule_args(customer_id, next_review_due=None),
    )


def test_acceleration_without_a_reason_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_SCHEDULE,
        _schedule_args(customer_id, accelerated_from="2026-06-01"),
    )


def test_acceleration_with_a_reason_is_accepted(customer_id):
    execute(
        _INSERT_SCHEDULE,
        _schedule_args(
            customer_id,
            accelerated_from="2026-06-01",
            acceleration_reason="sanctions hit on ongoing monitoring",
        ),
    )


def test_zero_review_frequency_is_rejected(customer_id):
    rejects(CHECK_VIOLATION, _INSERT_SCHEDULE, _schedule_args(customer_id, frequency=0))


def test_negative_grace_period_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION, _INSERT_SCHEDULE, _schedule_args(customer_id, grace_period_days=-1)
    )


def test_schedule_for_an_unknown_customer_is_rejected():
    rejects(FOREIGN_KEY_VIOLATION, _INSERT_SCHEDULE, _schedule_args(str(uuid.uuid4())))


def test_invalid_schedule_status_is_rejected(customer_id):
    rejects(
        INVALID_TEXT_REPRESENTATION,
        """
        INSERT INTO customers.review_schedule (
            id, customer_id, current_risk_rating, review_frequency_months,
            next_review_due, grace_period_days, overdue, schedule_status
        ) VALUES (%s, %s, 'MEDIUM', 12, DATE '2027-01-01', 30, false, 'PAUSED')
        """,
        (str(uuid.uuid4()), customer_id),
    )


# ── review_trigger_definition ─────────────────────────────────────────────────


def test_duplicate_trigger_code_is_rejected():
    code = insert_trigger_definition()
    rejects(
        UNIQUE_VIOLATION,
        """
        INSERT INTO customers.review_trigger_definition (
            id, trigger_code, description, source_epic, event_type, severity,
            review_action, auto_restrict, active, effective_from
        ) VALUES (%s, %s, 'duplicate', 'Epic 3.2', 'x', 'LOW',
                  'NO_ACTION', false, true, DATE '2026-01-01')
        """,
        (str(uuid.uuid4()), code),
    )


def test_auto_restrict_without_a_restriction_level_is_rejected():
    """A trigger that restricts a live customer must say to what level."""
    rejects(
        CHECK_VIOLATION,
        """
        INSERT INTO customers.review_trigger_definition (
            id, trigger_code, description, source_epic, event_type, severity,
            review_action, auto_restrict, restriction_level, active, effective_from
        ) VALUES (%s, %s, 'restricts with no level', 'Epic 3.2', 'x', 'CRITICAL',
                  'IMMEDIATE_REVIEW', true, NULL, true, DATE '2026-01-01')
        """,
        (str(uuid.uuid4()), ref("TRG")),
    )


def test_restriction_level_without_auto_restrict_is_rejected():
    rejects(
        CHECK_VIOLATION,
        """
        INSERT INTO customers.review_trigger_definition (
            id, trigger_code, description, source_epic, event_type, severity,
            review_action, auto_restrict, restriction_level, active, effective_from
        ) VALUES (%s, %s, 'level with no restrict', 'Epic 3.2', 'x', 'LOW',
                  'NO_ACTION', false, 'FULL_BLOCK', true, DATE '2026-01-01')
        """,
        (str(uuid.uuid4()), ref("TRG")),
    )


def test_auto_restrict_with_a_level_is_accepted():
    insert_trigger_definition(auto_restrict=True)


# ── customer_review: the baseline invariant ───────────────────────────────────


def test_review_without_a_baseline_is_rejected(customer_id):
    """The key test. A review with no baseline is not a review."""
    rejects(
        NOT_NULL_VIOLATION,
        INSERT_REVIEW,
        review_params(customer_id=customer_id, baseline_snapshot_ref=None),
    )


def test_review_against_a_nonexistent_baseline_is_rejected(customer_id):
    """NOT NULL alone would accept a ref that points at no snapshot."""
    rejects(
        FOREIGN_KEY_VIOLATION,
        INSERT_REVIEW,
        review_params(customer_id=customer_id, baseline_snapshot_ref=ref("SNAP")),
    )


def test_review_against_a_real_baseline_is_accepted(customer_id, snapshot_ref):
    insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)


# ── customer_review: identity and references ──────────────────────────────────


def test_duplicate_review_ref_is_rejected(customer_id, snapshot_ref):
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    rejects(
        UNIQUE_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            review_ref=review["review_ref"],
        ),
    )


def test_malformed_review_ref_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            review_ref="REVIEW-1",
        ),
    )


def test_review_for_an_unknown_customer_is_rejected(customer_id, snapshot_ref):
    rejects(
        FOREIGN_KEY_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=str(uuid.uuid4()), baseline_snapshot_ref=snapshot_ref
        ),
    )


def test_review_naming_an_unknown_trigger_is_rejected(customer_id, snapshot_ref):
    rejects(
        FOREIGN_KEY_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            review_type="EVENT_TRIGGERED",
            trigger_code=ref("TRG"),
        ),
    )


def test_event_triggered_review_without_a_trigger_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            review_type="EVENT_TRIGGERED",
            trigger_code=None,
        ),
    )


def test_periodic_review_carrying_a_trigger_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            review_type="PERIODIC",
            trigger_code=insert_trigger_definition(),
        ),
    )


def test_event_triggered_review_with_its_trigger_is_accepted(customer_id, snapshot_ref):
    insert_review(
        customer_id=customer_id,
        baseline_snapshot_ref=snapshot_ref,
        review_type="EVENT_TRIGGERED",
        trigger_code=insert_trigger_definition(),
    )


# ── customer_review: completion is a compliance record ────────────────────────


def _completed(**kw) -> dict:
    base = {
        "status": "COMPLETED",
        "outcome": "NO_CHANGE",
        "outcome_rationale": RATIONALE_50,
        "completed_at": "2026-09-07T10:00:00+00:00",
        "completed_by": "compliance.officer",
    }
    base.update(kw)
    return base


def test_completed_review_with_a_short_rationale_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            **_completed(outcome_rationale="A" * 49),
        ),
    )


def test_completed_review_at_exactly_fifty_characters_is_accepted(customer_id, snapshot_ref):
    assert len(RATIONALE_50) >= 50
    insert_review(
        customer_id=customer_id,
        baseline_snapshot_ref=snapshot_ref,
        **_completed(outcome_rationale="A" * 50),
    )


def test_whitespace_does_not_satisfy_the_rationale_minimum(customer_id, snapshot_ref):
    """Fifty spaces is fifty characters and no kind of compliance record."""
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            **_completed(outcome_rationale=" " * 60),
        ),
    )


def test_completed_review_without_an_outcome_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            **_completed(outcome=None),
        ),
    )


def test_an_incomplete_review_needs_no_rationale(customer_id, snapshot_ref):
    """The rule binds completion, not every row on the way to it."""
    insert_review(
        customer_id=customer_id,
        baseline_snapshot_ref=snapshot_ref,
        status="UNDER_ASSESSMENT",
    )


# ── customer_review: consequential outcomes carry dual authorisation ──────────


@pytest.mark.parametrize("outcome", ["SUSPENDED", "RESTRICTED", "REFERRED_TO_OFFBOARDING"])
def test_consequential_outcome_without_approval_is_rejected(
    customer_id, snapshot_ref, outcome
):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            **_completed(outcome=outcome),
        ),
    )


@pytest.mark.parametrize("outcome", ["SUSPENDED", "RESTRICTED", "REFERRED_TO_OFFBOARDING"])
def test_consequential_outcome_with_approval_is_accepted(customer_id, snapshot_ref, outcome):
    insert_review(
        customer_id=customer_id,
        baseline_snapshot_ref=snapshot_ref,
        **_completed(outcome=outcome, approval_request_id=str(uuid.uuid4())),
    )


def test_benign_outcome_needs_no_approval(customer_id, snapshot_ref):
    insert_review(
        customer_id=customer_id, baseline_snapshot_ref=snapshot_ref, **_completed()
    )


# ── customer_review: derived columns cannot lie ───────────────────────────────


def test_rating_changed_false_while_the_rating_moved_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            risk_rating_after="HIGH",
            rating_changed=False,
        ),
    )


def test_rating_changed_true_while_the_rating_held_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            risk_rating_after="LOW",
            rating_changed=True,
        ),
    )


def test_rating_changed_true_before_assessment_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            risk_rating_after=None,
            rating_changed=True,
        ),
    )


def test_a_genuine_rating_change_is_accepted(customer_id, snapshot_ref):
    insert_review(
        customer_id=customer_id,
        baseline_snapshot_ref=snapshot_ref,
        risk_rating_after="HIGH",
        rating_changed=True,
    )


def test_negative_material_change_count_is_rejected(customer_id, snapshot_ref):
    rejects(
        CHECK_VIOLATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id,
            baseline_snapshot_ref=snapshot_ref,
            material_change_count=-1,
        ),
    )


@pytest.mark.parametrize(
    "column, value",
    [
        ("review_type", "ANNUAL"),
        ("status", "PAUSED"),
        ("outcome", "CLOSED"),
        ("risk_rating_after", "ENHANCED"),
    ],
)
def test_invalid_review_enum_value_is_rejected(customer_id, snapshot_ref, column, value):
    """`ENHANCED` belongs to the onboarding ladder, not the review ladder."""
    rejects(
        INVALID_TEXT_REPRESENTATION,
        INSERT_REVIEW,
        review_params(
            customer_id=customer_id, baseline_snapshot_ref=snapshot_ref, **{column: value}
        ),
    )


# ── customer_review: column immutability trigger ──────────────────────────────


def test_review_ref_cannot_be_rewritten(customer_id, snapshot_ref):
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.customer_review SET review_ref = %s WHERE id = %s",
        (review_ref(), review["id"]),
    )


def test_initiated_at_cannot_be_rewritten(customer_id, snapshot_ref):
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.customer_review SET initiated_at = now() WHERE id = %s",
        (review["id"],),
    )


def test_completion_can_be_written_once(customer_id, snapshot_ref):
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    execute(
        """
        UPDATE customers.customer_review
        SET status = 'COMPLETED', outcome = 'NO_CHANGE', outcome_rationale = %s,
            completed_at = now(), completed_by = 'compliance.officer'
        WHERE id = %s
        """,
        (RATIONALE_50, review["id"]),
    )
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.customer_review SET completed_by = 'someone.else' WHERE id = %s",
        (review["id"],),
    )


def test_status_remains_writable(customer_id, snapshot_ref):
    """The trigger guards identity and completion, not the lifecycle itself."""
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    execute(
        "UPDATE customers.customer_review SET status = 'VERIFICATION_RUNNING' WHERE id = %s",
        (review["id"],),
    )


# ── customer_baseline_snapshot: append-only ───────────────────────────────────


def test_snapshot_rejects_update(customer_id, snapshot_ref):
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.customer_baseline_snapshot SET legal_name = 'Renamed' "
        "WHERE snapshot_ref = %s",
        (snapshot_ref,),
    )


def test_snapshot_rejects_delete(customer_id, snapshot_ref):
    rejects(
        RAISED_EXCEPTION,
        "DELETE FROM customers.customer_baseline_snapshot WHERE snapshot_ref = %s",
        (snapshot_ref,),
    )


def test_duplicate_snapshot_ref_is_rejected(customer_id, snapshot_ref):
    rejects(
        UNIQUE_VIOLATION,
        """
        INSERT INTO customers.customer_baseline_snapshot (
            id, snapshot_ref, customer_id, snapshot_reason, legal_name, risk_rating
        ) VALUES (%s, %s, %s, 'REVIEW_COMPLETED', 'Fixture Trading Ltd', 'LOW')
        """,
        (str(uuid.uuid4()), snapshot_ref, customer_id),
    )


def test_snapshot_for_an_unknown_customer_is_rejected():
    rejects(
        FOREIGN_KEY_VIOLATION,
        """
        INSERT INTO customers.customer_baseline_snapshot (
            id, snapshot_ref, customer_id, snapshot_reason, legal_name, risk_rating
        ) VALUES (%s, %s, %s, 'ONBOARDING_COMPLETED', 'Ghost Ltd', 'LOW')
        """,
        (str(uuid.uuid4()), ref("SNAP"), str(uuid.uuid4())),
    )


# ── detected_change: append-only ──────────────────────────────────────────────

_INSERT_CHANGE = """
    INSERT INTO customers.detected_change (
        id, change_ref, review_ref, customer_id, attribute, change_type,
        baseline_value, current_value, materiality, verification_source,
        requires_customer_confirmation
    ) VALUES (%s, %s, %s, %s, 'beneficial_owners', %s,
              '{"count": 2}', '{"count": 3}', %s, 'companies_house', true)
"""


@pytest.fixture
def change(customer_id, snapshot_ref) -> dict:
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    change_ref = ref("CHG")
    execute(
        _INSERT_CHANGE,
        (
            str(uuid.uuid4()),
            change_ref,
            review["review_ref"],
            customer_id,
            "ADDED",
            "MATERIAL",
        ),
    )
    return {"change_ref": change_ref, "review_ref": review["review_ref"]}


def test_detected_change_rejects_update(change):
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.detected_change SET accepted = true WHERE change_ref = %s",
        (change["change_ref"],),
    )


def test_detected_change_rejects_delete(change):
    rejects(
        RAISED_EXCEPTION,
        "DELETE FROM customers.detected_change WHERE change_ref = %s",
        (change["change_ref"],),
    )


def test_duplicate_change_ref_is_rejected(change, customer_id):
    rejects(
        UNIQUE_VIOLATION,
        _INSERT_CHANGE,
        (
            str(uuid.uuid4()),
            change["change_ref"],
            change["review_ref"],
            customer_id,
            "MODIFIED",
            "NOTABLE",
        ),
    )


def test_change_against_an_unknown_review_is_rejected(customer_id):
    rejects(
        FOREIGN_KEY_VIOLATION,
        _INSERT_CHANGE,
        (
            str(uuid.uuid4()),
            ref("CHG"),
            review_ref(),
            customer_id,
            "ADDED",
            "MATERIAL",
        ),
    )


def test_a_confirmed_no_change_is_recordable(customer_id, snapshot_ref):
    """A review that confirms nothing changed is a positive finding.

    Without this member a record cannot distinguish "we checked and all was
    well" from "we did not check".
    """
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    execute(
        _INSERT_CHANGE,
        (
            str(uuid.uuid4()),
            ref("CHG"),
            review["review_ref"],
            customer_id,
            "UNCHANGED_BUT_REVERIFIED",
            "IMMATERIAL",
        ),
    )


def test_invalid_materiality_is_rejected(customer_id, snapshot_ref):
    review = insert_review(customer_id=customer_id, baseline_snapshot_ref=snapshot_ref)
    rejects(
        INVALID_TEXT_REPRESENTATION,
        _INSERT_CHANGE,
        (
            str(uuid.uuid4()),
            ref("CHG"),
            review["review_ref"],
            customer_id,
            "ADDED",
            "SEVERE",
        ),
    )


# ── Referential integrity across the lifecycle ────────────────────────────────


def test_a_customer_with_review_history_cannot_be_deleted(customer_id, snapshot_ref):
    rejects(
        FOREIGN_KEY_VIOLATION,
        "DELETE FROM customers.customers WHERE customer_id = %s",
        (customer_id,),
    )


def test_a_review_referenced_by_a_change_cannot_be_deleted(change):
    rejects(
        FOREIGN_KEY_VIOLATION,
        "DELETE FROM customers.customer_review WHERE review_ref = %s",
        (change["review_ref"],),
    )
