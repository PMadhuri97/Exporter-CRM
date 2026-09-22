"""Model-level guarantees for the status, entitlement and attestation tables.

Database-free, and the counterpart to the direct-SQL suite next door: a model
can declare a constraint the database never received, and the two suites answer
different questions.
"""
import pytest
from sqlalchemy import BigInteger

from app.modules.customers.domain.entities.customer_entitlement import CustomerEntitlement
from app.modules.customers.domain.entities.customer_status_history import (
    MIN_REASON_DETAIL_LENGTH,
    CustomerStatusHistory,
)
from app.modules.customers.domain.entities.lifecycle_enums import (
    AttestationStatus,
    CustomerStatus,
    EntitlementSource,
    EntitlementType,
    LimitPeriod,
    RestrictionLevel,
)
from app.modules.customers.domain.entities.re_attestation_request import (
    ReAttestationRequest,
)

MODELS = [CustomerStatusHistory, CustomerEntitlement, ReAttestationRequest]

#: The registry holds asset codes such as USDC alongside ISO-4217 currencies.
MIN_CURRENCY_WIDTH = 8


# ── Placement and shape ───────────────────────────────────────────────────────


@pytest.mark.parametrize("model", MODELS)
def test_table_lives_in_the_customers_schema(model):
    assert model.__table__.schema == "customers"


def test_table_names_match_the_epic_data_model():
    assert {m.__tablename__ for m in MODELS} == {
        "customer_status_history",
        "customer_entitlement",
        "re_attestation_request",
    }


def test_status_history_is_append_only():
    """Current status is the latest row, not a column somebody can overwrite."""
    assert "updated_at" not in CustomerStatusHistory.__table__.columns


@pytest.mark.parametrize("model", [CustomerEntitlement, ReAttestationRequest])
def test_mutable_model_carries_updated_at(model):
    assert "updated_at" in model.__table__.columns


# ── Enum membership ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "enum_cls, expected",
    [
        (
            CustomerStatus,
            {
                "ACTIVE",
                "UNDER_REVIEW",
                "RESTRICTED",
                "SUSPENDED",
                "PENDING_OFFBOARDING",
                "OFFBOARDED",
            },
        ),
        (
            EntitlementType,
            {
                "CORRIDOR_ACCESS",
                "TRANSACTION_LIMIT",
                "AGGREGATE_LIMIT",
                "PRODUCT_ACCESS",
                "ASSET_ACCESS",
            },
        ),
        (LimitPeriod, {"PER_TRANSACTION", "DAILY", "MONTHLY"}),
        (
            EntitlementSource,
            {"ONBOARDING", "REVIEW_OUTCOME", "MANUAL_GRANT", "RESTRICTION_APPLIED"},
        ),
        (
            AttestationStatus,
            {"PENDING", "PARTIALLY_RESPONDED", "COMPLETED", "OVERDUE", "ESCALATED"},
        ),
    ],
)
def test_enum_members_match_the_epic(enum_cls, expected):
    assert {m.name for m in enum_cls} == expected


def test_status_history_reuses_the_restriction_ladder():
    """The ladder a trigger auto-applies is the ladder a status change records."""
    column = CustomerStatusHistory.__table__.columns["restriction_level"]
    assert column.type.enum_class is RestrictionLevel
    assert column.type.name == "customer_restriction_level_enum"


# ── Declared constraints and indexes ──────────────────────────────────────────


@pytest.mark.parametrize(
    "model, name",
    [
        (CustomerStatusHistory, "ck_customer_status_history_reason_detail_substantive"),
        (CustomerStatusHistory, "ck_customer_status_history_restriction_level_paired"),
        (
            CustomerStatusHistory,
            "ck_customer_status_history_consequential_change_approved",
        ),
        (CustomerStatusHistory, "ck_customer_status_history_period_ordered"),
        (CustomerEntitlement, "ck_customer_entitlement_limit_paired"),
        (CustomerEntitlement, "ck_customer_entitlement_limit_period_paired"),
        (CustomerEntitlement, "ck_customer_entitlement_limit_non_negative"),
        (CustomerEntitlement, "ck_customer_entitlement_period_ordered"),
        (ReAttestationRequest, "uq_re_attestation_request_ref"),
        (ReAttestationRequest, "ck_re_attestation_request_completion_authorised"),
    ],
)
def test_named_constraint_is_declared(model, name):
    assert name in {c.name for c in model.__table__.constraints}


def test_entitlement_lookup_index_covers_the_enforcement_path():
    index = next(
        i
        for i in CustomerEntitlement.__table__.indexes
        if i.name == "ix_customer_entitlement_lookup"
    )
    assert [c.name for c in index.columns] == [
        "customer_id",
        "entitlement_type",
        "active",
    ]


# ── Money columns ─────────────────────────────────────────────────────────────


def test_limit_is_an_integer_in_minor_units():
    """Money is never a float or a Decimal at rest."""
    column = CustomerEntitlement.__table__.columns["limit_value_minor"]
    assert isinstance(column.type, BigInteger)


def test_limit_currency_is_wide_enough_for_registry_asset_codes():
    column = CustomerEntitlement.__table__.columns["limit_currency"]
    assert column.type.length >= MIN_CURRENCY_WIDTH


def test_every_entitlement_records_an_approval():
    """No entitlement exists without a recorded approval behind it."""
    assert (
        CustomerEntitlement.__table__.columns["approval_request_id"].nullable is False
    )


# ── References ────────────────────────────────────────────────────────────────


def test_reason_detail_minimum_is_declared():
    assert MIN_REASON_DETAIL_LENGTH == 20


def test_from_status_is_nullable_for_a_customers_first_transition():
    """The first row of a history has no prior status.

    This nullability is why the approval check carries an explicit
    `from_status IS NOT NULL` guard rather than relying on `IN`.
    """
    assert CustomerStatusHistory.__table__.columns["from_status"].nullable is True
    assert CustomerStatusHistory.__table__.columns["to_status"].nullable is False


@pytest.mark.parametrize(
    "model, column, target",
    [
        (
            CustomerStatusHistory,
            "source_review_ref",
            "customers.customer_review.review_ref",
        ),
        (
            ReAttestationRequest,
            "review_ref",
            "customers.customer_review.review_ref",
        ),
        (
            CustomerEntitlement,
            "customer_id",
            "customers.customers.customer_id",
        ),
    ],
)
def test_foreign_key_targets_and_restricts(model, column, target):
    fk = next(iter(model.__table__.columns[column].foreign_keys))
    assert fk.target_fullname == target
    assert fk.ondelete == "RESTRICT"
