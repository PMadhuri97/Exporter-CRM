"""Model-level guarantees for the review lifecycle schema.

Database-free. These assert what the mapping declares — schema placement, enum
membership, append-only shape, and the presence of every named constraint and
index. The direct-SQL suite next door asserts that Postgres enforces them; a
model can declare a constraint the database never received, and the two suites
answer different questions.
"""
import pytest

from app.modules.customers.domain.entities.customer_baseline_snapshot import (
    CustomerBaselineSnapshot,
)
from app.modules.customers.domain.entities.customer_review import (
    MIN_OUTCOME_RATIONALE_LENGTH,
    CustomerReview,
)
from app.modules.customers.domain.entities.customers import RiskRating
from app.modules.customers.domain.entities.detected_change import DetectedChange
from app.modules.customers.domain.entities.lifecycle_enums import (
    ChangeType,
    Materiality,
    RestrictionLevel,
    ReviewAction,
    ReviewOutcome,
    ReviewRiskRating,
    ReviewStatus,
    ReviewType,
    ScheduleStatus,
    SnapshotReason,
    TriggerSeverity,
)
from app.modules.customers.domain.entities.review_schedule import ReviewSchedule
from app.modules.customers.domain.entities.review_trigger_definition import (
    ReviewTriggerDefinition,
)

LIFECYCLE_MODELS = [
    ReviewSchedule,
    ReviewTriggerDefinition,
    CustomerReview,
    CustomerBaselineSnapshot,
    DetectedChange,
]

APPEND_ONLY_MODELS = [CustomerBaselineSnapshot, DetectedChange]
MUTABLE_MODELS = [ReviewSchedule, ReviewTriggerDefinition, CustomerReview]


# ── Placement ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", LIFECYCLE_MODELS)
def test_every_lifecycle_table_lives_in_the_customers_schema(model):
    assert model.__table__.schema == "customers"


def test_table_names_match_the_epic_data_model():
    assert {m.__tablename__ for m in LIFECYCLE_MODELS} == {
        "review_schedule",
        "review_trigger_definition",
        "customer_review",
        "customer_baseline_snapshot",
        "detected_change",
    }


@pytest.mark.parametrize("model", LIFECYCLE_MODELS)
def test_primary_key_is_a_single_uuid_column(model):
    pk = list(model.__table__.primary_key.columns)
    assert [c.name for c in pk] == ["id"]
    assert pk[0].type.python_type.__name__ == "UUID"


# ── Append-only shape ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("model", APPEND_ONLY_MODELS)
def test_append_only_model_has_no_updated_at(model):
    """Immutability is declared in the model, not only in the trigger.

    An `updated_at` column on an append-only table is an invitation to write one,
    and the ORM would set it on a flush the trigger then rejects.
    """
    assert "updated_at" not in model.__table__.columns


@pytest.mark.parametrize("model", MUTABLE_MODELS)
def test_mutable_model_carries_updated_at(model):
    assert "updated_at" in model.__table__.columns


# ── Enum membership ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "enum_cls, expected",
    [
        (ReviewRiskRating, {"LOW", "MEDIUM", "HIGH", "PROHIBITED"}),
        (
            ScheduleStatus,
            {"SCHEDULED", "IN_PROGRESS", "OVERDUE", "SUSPENDED_PENDING_OFFBOARDING"},
        ),
        (TriggerSeverity, {"CRITICAL", "HIGH", "MEDIUM", "LOW"}),
        (
            ReviewAction,
            {
                "IMMEDIATE_REVIEW",
                "ACCELERATE_SCHEDULE",
                "FLAG_AT_NEXT_REVIEW",
                "NO_ACTION",
            },
        ),
        (
            ReviewType,
            {"PERIODIC", "EVENT_TRIGGERED", "AD_HOC", "REMEDIATION_FOLLOWUP"},
        ),
        (
            ReviewStatus,
            {
                "INITIATED",
                "VERIFICATION_RUNNING",
                "AWAITING_CUSTOMER",
                "UNDER_ASSESSMENT",
                "PENDING_APPROVAL",
                "COMPLETED",
                "CANCELLED",
            },
        ),
        (
            ReviewOutcome,
            {
                "NO_CHANGE",
                "RATING_CHANGED",
                "RESTRICTED",
                "SUSPENDED",
                "REFERRED_TO_OFFBOARDING",
                "REMEDIATION_REQUIRED",
            },
        ),
        (
            SnapshotReason,
            {
                "ONBOARDING_COMPLETED",
                "REVIEW_COMPLETED",
                "REMEDIATION_COMPLETED",
                "MANUAL_CAPTURE",
            },
        ),
        (
            ChangeType,
            {"ADDED", "REMOVED", "MODIFIED", "UNCHANGED_BUT_REVERIFIED"},
        ),
        (Materiality, {"MATERIAL", "NOTABLE", "IMMATERIAL"}),
    ],
)
def test_enum_members_match_the_epic(enum_cls, expected):
    assert {m.name for m in enum_cls} == expected


def test_review_rating_ladder_is_not_the_onboarding_ladder():
    """The two ratings are different types with a different top band.

    Sharing one enum would let a review store ENHANCED, which the review
    programme has no cadence for, or an onboarding decision store PROHIBITED.
    """
    assert ReviewRiskRating.PROHIBITED.name not in {m.name for m in RiskRating}
    assert RiskRating.ENHANCED.name not in {m.name for m in ReviewRiskRating}


def test_restriction_ladder_is_graduated():
    """Full access or full suspension is too blunt for a live relationship."""
    assert len(RestrictionLevel) > 2
    assert RestrictionLevel.FULL_BLOCK in RestrictionLevel


# ── Declared constraints and indexes ──────────────────────────────────────────


@pytest.mark.parametrize(
    "model, name",
    [
        (ReviewSchedule, "uq_review_schedule_customer_id"),
        (ReviewSchedule, "ck_review_schedule_frequency_positive"),
        (ReviewSchedule, "ck_review_schedule_grace_period_non_negative"),
        (ReviewSchedule, "ck_review_schedule_acceleration_reason_present"),
        (ReviewTriggerDefinition, "uq_review_trigger_definition_code"),
        (ReviewTriggerDefinition, "ck_review_trigger_definition_restriction_paired"),
        (CustomerReview, "uq_customer_review_ref"),
        (CustomerReview, "ck_customer_review_ref_format"),
        (CustomerReview, "ck_customer_review_completion_recorded"),
        (CustomerReview, "ck_customer_review_consequential_outcome_approved"),
        (CustomerReview, "ck_customer_review_trigger_code_consistent"),
        (CustomerReview, "ck_customer_review_rating_changed_derived"),
        (CustomerReview, "ck_customer_review_material_change_count_non_negative"),
        (CustomerBaselineSnapshot, "uq_customer_baseline_snapshot_ref"),
        (DetectedChange, "uq_detected_change_ref"),
    ],
)
def test_named_constraint_is_declared(model, name):
    assert name in {c.name for c in model.__table__.constraints}


@pytest.mark.parametrize(
    "model, name, columns",
    [
        (
            ReviewSchedule,
            "ix_review_schedule_due_sweep",
            ["next_review_due", "schedule_status"],
        ),
        (
            CustomerReview,
            "ix_customer_review_customer_time",
            ["customer_id", "initiated_at"],
        ),
        (
            DetectedChange,
            "ix_detected_change_review_materiality",
            ["review_ref", "materiality"],
        ),
        (
            CustomerBaselineSnapshot,
            "ix_customer_baseline_snapshot_customer_time",
            ["customer_id", "captured_at"],
        ),
    ],
)
def test_index_is_declared_over_the_expected_columns(model, name, columns):
    index = next(i for i in model.__table__.indexes if i.name == name)
    assert [c.name for c in index.columns] == columns


# ── The invariant the whole Epic rests on ─────────────────────────────────────


def test_baseline_snapshot_ref_is_required_and_references_a_snapshot():
    """A review with no baseline is not a review.

    NOT NULL alone would accept a ref pointing at no snapshot, which is worth no
    more than a null one — hence the foreign key.
    """
    column = CustomerReview.__table__.columns["baseline_snapshot_ref"]
    assert column.nullable is False
    targets = {fk.target_fullname for fk in column.foreign_keys}
    assert targets == {"customers.customer_baseline_snapshot.snapshot_ref"}


def test_outcome_rationale_minimum_is_fifty_characters():
    assert MIN_OUTCOME_RATIONALE_LENGTH == 50


@pytest.mark.parametrize(
    "model, column",
    [
        (ReviewSchedule, "customer_id"),
        (CustomerReview, "customer_id"),
        (CustomerBaselineSnapshot, "customer_id"),
        (DetectedChange, "customer_id"),
    ],
)
def test_customer_id_restricts_deletion_of_the_customer(model, column):
    """A customer with review history cannot be deleted out from under it."""
    fk = next(iter(model.__table__.columns[column].foreign_keys))
    assert fk.target_fullname == "customers.customers.customer_id"
    assert fk.ondelete == "RESTRICT"
