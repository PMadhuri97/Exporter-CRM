"""The review lifecycle schema as the database actually holds it.

The constraint suites prove that Postgres rejects bad rows. This one proves the
objects those rejections depend on are present at all, and that what the models
declare is what the migrations built — a model column that never reached a
migration is invisible to every test that only inserts rows.

It asserts the resulting schema rather than driving Alembic.  Migrating inside a
test reverts the reference registries on a shared database and leaves screening
silently disabled for everything that runs afterwards, so the settlement module
stopped doing it and this follows that precedent. The upgrade/downgrade path is
exercised by running the migration, not by a test that mutates the database
every other test is using.
"""
import pytest

from app.modules.customers.domain.entities import (
    CustomerBaselineSnapshot,
    CustomerEntitlement,
    CustomerReview,
    CustomerStatusHistory,
    DetectedChange,
    ReAttestationRequest,
    ReviewSchedule,
    ReviewTriggerDefinition,
)
from app.modules.customers.domain.entities.lifecycle_enums import (
    AttestationStatus,
    ChangeType,
    CustomerStatus,
    EntitlementSource,
    EntitlementType,
    LimitPeriod,
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
from app.modules.customers.tests.fixtures.lifecycle_sql import connect

SCHEMA = "customers"

LIFECYCLE_MODELS = [
    ReviewSchedule,
    ReviewTriggerDefinition,
    CustomerReview,
    CustomerBaselineSnapshot,
    DetectedChange,
    CustomerStatusHistory,
    CustomerEntitlement,
    ReAttestationRequest,
]

APPEND_ONLY_TABLES = [
    "customer_baseline_snapshot",
    "detected_change",
    "customer_status_history",
]


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _scalars(sql: str, params: tuple = ()) -> set:
    return {row[0] for row in _query(sql, params)}


# ── Tables ────────────────────────────────────────────────────────────────────


def test_all_eight_lifecycle_tables_exist():
    present = _scalars(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (SCHEMA,)
    )
    assert {m.__tablename__ for m in LIFECYCLE_MODELS} <= present


@pytest.mark.parametrize("model", LIFECYCLE_MODELS, ids=lambda m: m.__tablename__)
def test_model_columns_match_the_built_table(model):
    """Every declared column reached a migration, and no column arrived without one.

    A drift in either direction is invisible to a suite that only inserts rows:
    a column the model has and the table lacks fails only when something writes
    it, and a column the table has and the model lacks is never written at all.
    """
    built = _scalars(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (SCHEMA, model.__tablename__),
    )
    assert {c.name for c in model.__table__.columns} == built


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_append_only_table_has_no_updated_at_column(table):
    """Immutability is enforced by the trigger and declared by the table's shape.

    An `updated_at` column here would be an invitation to write one, on a table
    whose trigger rejects every UPDATE.
    """
    columns = _scalars(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (SCHEMA, table),
    )
    assert "updated_at" not in columns
    assert "created_at" in columns


# ── Indexes ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "index_name",
    [
        "ix_review_schedule_due_sweep",
        "ix_customer_review_customer_time",
        "ix_detected_change_review_materiality",
        "ix_customer_entitlement_lookup",
        "ix_customer_baseline_snapshot_customer_time",
        "ix_customer_status_history_customer_time",
        "ix_re_attestation_request_due",
    ],
)
def test_index_was_built(index_name):
    """A downgrade that drops an index and an upgrade that never rebuilds it
    leaves the sweep doing sequential scans, and nothing else notices."""
    assert index_name in _scalars(
        "SELECT indexname FROM pg_indexes WHERE schemaname = %s", (SCHEMA,)
    )


def test_no_index_is_left_invalid():
    """A failed concurrent build leaves an INVALID index behind that still
    satisfies a name check but is never used by the planner."""
    invalid = _scalars(
        """
        SELECT c.relname
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND NOT i.indisvalid
        """,
        (SCHEMA,),
    )
    assert not invalid


# ── Triggers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "trigger_name, table",
    [
        ("trg_customer_baseline_snapshot_append_only", "customer_baseline_snapshot"),
        ("trg_detected_change_append_only", "detected_change"),
        ("trg_customer_status_history_append_only", "customer_status_history"),
        ("trg_customer_review_field_immutability", "customer_review"),
        ("trg_re_attestation_request_field_immutability", "re_attestation_request"),
    ],
)
def test_trigger_is_attached_to_its_table(trigger_name, table):
    attached = _scalars(
        """
        SELECT t.tgname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND NOT t.tgisinternal
        """,
        (SCHEMA, table),
    )
    assert trigger_name in attached


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_append_only_trigger_covers_both_update_and_delete(table):
    """A trigger registered for UPDATE alone leaves DELETE open, and the table
    reads as append-only in every review while rows quietly disappear."""
    rows = _query(
        """
        SELECT t.tgtype
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND NOT t.tgisinternal
        """,
        (SCHEMA, table),
    )
    assert rows, f"no trigger on {table}"
    # pg_trigger.tgtype bit 3 is DELETE, bit 4 is UPDATE.
    tgtype = rows[0][0]
    assert tgtype & (1 << 3), f"{table} trigger does not fire on DELETE"
    assert tgtype & (1 << 4), f"{table} trigger does not fire on UPDATE"


def test_the_column_immutability_function_belongs_to_this_schema():
    """`public` holds only alembic_version and the shared prevent_mutation()."""
    assert "prevent_field_mutation_when_set" in _scalars(
        """
        SELECT p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %s
        """,
        (SCHEMA,),
    )


# ── Enum types ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "type_name, enum_cls",
    [
        ("review_risk_rating_enum", ReviewRiskRating),
        ("review_schedule_status_enum", ScheduleStatus),
        ("review_trigger_severity_enum", TriggerSeverity),
        ("review_trigger_action_enum", ReviewAction),
        ("customer_restriction_level_enum", RestrictionLevel),
        ("customer_review_type_enum", ReviewType),
        ("customer_review_status_enum", ReviewStatus),
        ("customer_review_outcome_enum", ReviewOutcome),
        ("baseline_snapshot_reason_enum", SnapshotReason),
        ("detected_change_type_enum", ChangeType),
        ("detected_change_materiality_enum", Materiality),
        ("customer_status_enum", CustomerStatus),
        ("entitlement_type_enum", EntitlementType),
        ("entitlement_limit_period_enum", LimitPeriod),
        ("entitlement_source_enum", EntitlementSource),
        ("attestation_status_enum", AttestationStatus),
    ],
)
def test_enum_labels_match_the_python_members(type_name, enum_cls):
    """The migration spells its enum values out by hand.

    A member added to the Python enum without a matching ALTER TYPE fails only
    when a row carrying it is written, which in a compliance table may be the
    first time it genuinely matters.
    """
    labels = _scalars(
        """
        SELECT e.enumlabel
        FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = %s AND t.typname = %s
        """,
        (SCHEMA, type_name),
    )
    assert labels == {m.name for m in enum_cls}


def test_the_review_ladder_is_a_separate_type_from_the_onboarding_ladder():
    """Both live in this schema; conflating them would let a review store a band
    it has no cadence for."""
    review = _scalars(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = %s AND t.typname = 'review_risk_rating_enum'",
        (SCHEMA,),
    )
    onboarding = _scalars(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = %s AND t.typname = 'risk_rating_enum'",
        (SCHEMA,),
    )
    assert "PROHIBITED" in review and "PROHIBITED" not in onboarding
    assert "ENHANCED" in onboarding and "ENHANCED" not in review


# ── Referential integrity ─────────────────────────────────────────────────────


def test_every_customer_reference_restricts_deletion():
    """RESTRICT, not CASCADE: a customer's review history is a financial and
    regulatory record, and deleting the customer must not take it with them."""
    actions = _query(
        """
        SELECT c.conname, c.confdeltype
        FROM pg_constraint c
        JOIN pg_class child ON child.oid = c.conrelid
        JOIN pg_class parent ON parent.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = child.relnamespace
        WHERE n.nspname = %s AND c.contype = 'f' AND parent.relname = 'customers'
        """,
        (SCHEMA,),
    )
    lifecycle = [row for row in actions if row[0].startswith(("fk_review", "fk_customer", "fk_detected", "fk_re_"))]
    assert lifecycle, "no lifecycle foreign keys onto customers.customers"
    # 'r' is RESTRICT in pg_constraint.confdeltype.
    assert all(row[1] == "r" for row in lifecycle), lifecycle
