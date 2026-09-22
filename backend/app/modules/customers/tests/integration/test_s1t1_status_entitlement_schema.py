"""Direct-SQL constraint suite for the status, entitlement and attestation tables.

Raw SQL on purpose: inserting through the ORM would prove only that SQLAlchemy
declares a constraint, not that Postgres enforces one. Every constraint and
trigger the migration creates is violated here and asserted rejected, and the
boundary of each is exercised alongside it.

The test database is shared across a run and never reset, so every test mints
its own identifiers and none may assume an empty table.
"""
import uuid

import pytest

from app.modules.customers.tests.fixtures.lifecycle_sql import (
    CHECK_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    INVALID_TEXT_REPRESENTATION,
    NOT_NULL_VIOLATION,
    RAISED_EXCEPTION,
    UNIQUE_VIOLATION,
    execute,
    insert_customer,
    insert_review,
    insert_snapshot,
    ref,
    rejects,
)

REASON_DETAIL = "Beneficial ownership changed without notice."
APPROVAL = str(uuid.uuid4())


@pytest.fixture
def customer_id() -> str:
    return insert_customer()


@pytest.fixture
def review_ref(customer_id: str) -> str:
    review = insert_review(
        customer_id=customer_id, baseline_snapshot_ref=insert_snapshot(customer_id)
    )
    return review["review_ref"]


# ── customer_status_history ───────────────────────────────────────────────────

_INSERT_STATUS = """
    INSERT INTO customers.customer_status_history (
        id, customer_id, from_status, to_status, restriction_level,
        reason_code, reason_detail, effective_from, effective_until,
        initiated_by, approval_request_id, source_review_ref,
        customer_notified_at, notification_ref
    ) VALUES (
        %(id)s, %(customer_id)s, %(from_status)s, %(to_status)s,
        %(restriction_level)s, 'REVIEW_OUTCOME', %(reason_detail)s,
        %(effective_from)s, %(effective_until)s, 'compliance.officer',
        %(approval_request_id)s, %(source_review_ref)s, NULL, NULL
    )
"""


def _status_params(customer: str, **overrides) -> dict:
    params = {
        "id": str(uuid.uuid4()),
        "customer_id": customer,
        "from_status": "ACTIVE",
        "to_status": "UNDER_REVIEW",
        "restriction_level": None,
        "reason_detail": REASON_DETAIL,
        "effective_from": "2026-09-08T09:00:00+00:00",
        "effective_until": None,
        "approval_request_id": None,
        "source_review_ref": None,
    }
    params.update(overrides)
    return params


def test_a_benign_status_change_needs_no_approval(customer_id):
    execute(_INSERT_STATUS, _status_params(customer_id))


def test_short_reason_detail_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, reason_detail="closed"),
    )


def test_whitespace_reason_detail_is_rejected(customer_id):
    """Padding a mandatory field with spaces does not make it a record."""
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, reason_detail=" " * 40),
    )


def test_reason_detail_at_the_minimum_is_accepted(customer_id):
    execute(_INSERT_STATUS, _status_params(customer_id, reason_detail="A" * 20))


def test_missing_reason_detail_is_rejected(customer_id):
    rejects(
        NOT_NULL_VIOLATION, _INSERT_STATUS, _status_params(customer_id, reason_detail=None)
    )


# ── Consequential changes carry dual authorisation ────────────────────────────


def test_suspension_without_approval_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, to_status="SUSPENDED"),
    )


def test_restriction_without_approval_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(
            customer_id, to_status="RESTRICTED", restriction_level="OUTBOUND_BLOCKED"
        ),
    )


@pytest.mark.parametrize("prior", ["SUSPENDED", "RESTRICTED"])
def test_reinstatement_without_approval_is_rejected(customer_id, prior):
    """Returning a customer to ACTIVE is as consequential as removing them from it."""
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, from_status=prior, to_status="ACTIVE"),
    )


def test_suspension_with_approval_is_accepted(customer_id):
    execute(
        _INSERT_STATUS,
        _status_params(customer_id, to_status="SUSPENDED", approval_request_id=APPROVAL),
    )


def test_reinstatement_with_approval_is_accepted(customer_id):
    execute(
        _INSERT_STATUS,
        _status_params(
            customer_id,
            from_status="SUSPENDED",
            to_status="ACTIVE",
            approval_request_id=str(uuid.uuid4()),
        ),
    )


def test_a_first_transition_into_active_needs_no_approval(customer_id):
    """The first row of a history has no prior status, and is not a reinstatement."""
    execute(
        _INSERT_STATUS, _status_params(customer_id, from_status=None, to_status="ACTIVE")
    )


def test_a_first_transition_into_suspension_still_needs_approval(customer_id):
    """The NULL from_status must not become a way around the approval rule."""
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, from_status=None, to_status="SUSPENDED"),
    )


# ── Restriction level is paired with the restricted status ────────────────────


def test_restricted_without_a_level_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(
            customer_id,
            to_status="RESTRICTED",
            restriction_level=None,
            approval_request_id=APPROVAL,
        ),
    )


def test_a_level_on_a_non_restricted_status_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(
            customer_id,
            to_status="SUSPENDED",
            restriction_level="FULL_BLOCK",
            approval_request_id=APPROVAL,
        ),
    )


def test_restricted_with_a_level_and_approval_is_accepted(customer_id):
    execute(
        _INSERT_STATUS,
        _status_params(
            customer_id,
            to_status="RESTRICTED",
            restriction_level="LIMIT_REDUCED",
            approval_request_id=APPROVAL,
        ),
    )


def test_effective_until_before_effective_from_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, effective_until="2026-09-07T09:00:00+00:00"),
    )


def test_invalid_customer_status_is_rejected(customer_id):
    rejects(
        INVALID_TEXT_REPRESENTATION,
        _INSERT_STATUS,
        _status_params(customer_id, to_status="DORMANT"),
    )


def test_status_change_citing_an_unknown_review_is_rejected(customer_id):
    rejects(
        FOREIGN_KEY_VIOLATION,
        _INSERT_STATUS,
        _status_params(customer_id, source_review_ref="REV-2026-000000001"),
    )


def test_status_change_citing_a_real_review_is_accepted(customer_id, review_ref):
    execute(_INSERT_STATUS, _status_params(customer_id, source_review_ref=review_ref))


# ── customer_status_history is append-only ────────────────────────────────────


@pytest.fixture
def status_row(customer_id) -> str:
    params = _status_params(customer_id)
    execute(_INSERT_STATUS, params)
    return params["id"]


def test_status_history_rejects_update(status_row):
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.customer_status_history SET reason_code = 'EDITED' WHERE id = %s",
        (status_row,),
    )


def test_status_history_rejects_delete(status_row):
    """A suspension edited out of the record is not one anyone can defend."""
    rejects(
        RAISED_EXCEPTION,
        "DELETE FROM customers.customer_status_history WHERE id = %s",
        (status_row,),
    )


# ── customer_entitlement ──────────────────────────────────────────────────────

_INSERT_ENTITLEMENT = """
    INSERT INTO customers.customer_entitlement (
        id, customer_id, entitlement_type, entitlement_key, permitted,
        limit_value_minor, limit_currency, limit_period, granted_at, granted_by,
        approval_request_id, effective_from, effective_until, source, active
    ) VALUES (
        %(id)s, %(customer_id)s, %(entitlement_type)s, %(entitlement_key)s, true,
        %(limit_value_minor)s, %(limit_currency)s, %(limit_period)s, now(),
        'compliance.officer', %(approval_request_id)s, %(effective_from)s,
        %(effective_until)s, 'REVIEW_OUTCOME', true
    )
"""


def _entitlement_params(customer: str, **overrides) -> dict:
    params = {
        "id": str(uuid.uuid4()),
        "customer_id": customer,
        "entitlement_type": "CORRIDOR_ACCESS",
        "entitlement_key": "GB-IN",
        "limit_value_minor": None,
        "limit_currency": None,
        "limit_period": None,
        "approval_request_id": str(uuid.uuid4()),
        "effective_from": "2026-09-08T00:00:00+00:00",
        "effective_until": None,
    }
    params.update(overrides)
    return params


def test_a_non_limit_entitlement_carries_no_amount(customer_id):
    execute(_INSERT_ENTITLEMENT, _entitlement_params(customer_id))


def test_an_amount_without_a_currency_is_rejected(customer_id):
    """An amount with no currency is not an amount."""
    rejects(
        CHECK_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="TRANSACTION_LIMIT",
            limit_value_minor=50_000_00,
            limit_currency=None,
            limit_period="PER_TRANSACTION",
        ),
    )


def test_a_currency_without_an_amount_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="TRANSACTION_LIMIT",
            limit_value_minor=None,
            limit_currency="USD",
            # Left null so the period pairing holds and this row can only trip
            # the currency pairing. A row that violates two constraints proves
            # neither of them is present.
            limit_period=None,
        ),
    )


def test_an_amount_without_a_period_is_rejected(customer_id):
    """500000 of what, per what?"""
    rejects(
        CHECK_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="TRANSACTION_LIMIT",
            limit_value_minor=50_000_00,
            limit_currency="USD",
            limit_period=None,
        ),
    )


def test_a_complete_limit_is_accepted(customer_id):
    execute(
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="TRANSACTION_LIMIT",
            limit_value_minor=50_000_00,
            limit_currency="USD",
            limit_period="PER_TRANSACTION",
        ),
    )


def test_a_registry_asset_code_fits_the_currency_column(customer_id):
    """The column holds registry codes such as USDC, not only ISO-4217."""
    execute(
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="ASSET_ACCESS",
            entitlement_key="USDC",
            limit_value_minor=1_000_000,
            limit_currency="USDC",
            limit_period="DAILY",
        ),
    )


def test_a_negative_limit_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="AGGREGATE_LIMIT",
            entitlement_key=None,
            limit_value_minor=-1,
            limit_currency="USD",
            limit_period="MONTHLY",
        ),
    )


def test_a_zero_limit_is_accepted(customer_id):
    """Zero is a meaningful cap — permitted, but for nothing."""
    execute(
        _INSERT_ENTITLEMENT,
        _entitlement_params(
            customer_id,
            entitlement_type="AGGREGATE_LIMIT",
            entitlement_key=None,
            limit_value_minor=0,
            limit_currency="USD",
            limit_period="MONTHLY",
        ),
    )


def test_an_entitlement_without_an_approval_is_rejected(customer_id):
    rejects(
        NOT_NULL_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(customer_id, approval_request_id=None),
    )


def test_entitlement_ending_before_it_starts_is_rejected(customer_id):
    rejects(
        CHECK_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(customer_id, effective_until="2026-09-07T00:00:00+00:00"),
    )


def test_entitlement_for_an_unknown_customer_is_rejected():
    rejects(
        FOREIGN_KEY_VIOLATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(str(uuid.uuid4())),
    )


@pytest.mark.parametrize(
    "column, value",
    [
        ("entitlement_type", "CORRIDOR"),
        ("limit_period", "WEEKLY"),
    ],
)
def test_invalid_entitlement_enum_is_rejected(customer_id, column, value):
    overrides = {column: value}
    if column == "limit_period":
        overrides |= {"limit_value_minor": 100, "limit_currency": "USD"}
    rejects(
        INVALID_TEXT_REPRESENTATION,
        _INSERT_ENTITLEMENT,
        _entitlement_params(customer_id, **overrides),
    )


# ── re_attestation_request ────────────────────────────────────────────────────

_INSERT_ATTESTATION = """
    INSERT INTO customers.re_attestation_request (
        id, attestation_ref, customer_id, review_ref, requested_items,
        requested_at, due_by, reminder_schedule, status, responded_at,
        responded_by, signatory_authority_verified, response_detail, escalated_at
    ) VALUES (
        %(id)s, %(attestation_ref)s, %(customer_id)s, %(review_ref)s,
        '{"items": ["beneficial_owners"]}', now(), DATE '2026-10-01',
        NULL, %(status)s, %(responded_at)s, %(responded_by)s,
        %(signatory_authority_verified)s, NULL, NULL
    )
"""


def _attestation_params(customer: str, review: str, **overrides) -> dict:
    params = {
        "id": str(uuid.uuid4()),
        "attestation_ref": ref("ATT"),
        "customer_id": customer,
        "review_ref": review,
        "status": "PENDING",
        "responded_at": None,
        "responded_by": None,
        "signatory_authority_verified": False,
    }
    params.update(overrides)
    return params


def _completed_attestation(**kw) -> dict:
    base = {
        "status": "COMPLETED",
        "responded_at": "2026-09-20T12:00:00+00:00",
        "responded_by": "director.one",
        "signatory_authority_verified": True,
    }
    base.update(kw)
    return base


def test_a_pending_attestation_needs_no_signatory(customer_id, review_ref):
    execute(_INSERT_ATTESTATION, _attestation_params(customer_id, review_ref))


def test_completed_attestation_without_verified_authority_is_rejected(
    customer_id, review_ref
):
    """An unverified answer binds nobody, and leaves the file looking satisfied."""
    rejects(
        CHECK_VIOLATION,
        _INSERT_ATTESTATION,
        _attestation_params(
            customer_id,
            review_ref,
            **_completed_attestation(signatory_authority_verified=False),
        ),
    )


def test_completed_attestation_without_a_responder_is_rejected(customer_id, review_ref):
    rejects(
        CHECK_VIOLATION,
        _INSERT_ATTESTATION,
        _attestation_params(
            customer_id, review_ref, **_completed_attestation(responded_by=None)
        ),
    )


def test_completed_attestation_without_a_response_time_is_rejected(customer_id, review_ref):
    rejects(
        CHECK_VIOLATION,
        _INSERT_ATTESTATION,
        _attestation_params(
            customer_id, review_ref, **_completed_attestation(responded_at=None)
        ),
    )


def test_a_fully_authorised_completion_is_accepted(customer_id, review_ref):
    execute(
        _INSERT_ATTESTATION,
        _attestation_params(customer_id, review_ref, **_completed_attestation()),
    )


def test_duplicate_attestation_ref_is_rejected(customer_id, review_ref):
    params = _attestation_params(customer_id, review_ref)
    execute(_INSERT_ATTESTATION, params)
    rejects(
        UNIQUE_VIOLATION,
        _INSERT_ATTESTATION,
        _attestation_params(
            customer_id, review_ref, attestation_ref=params["attestation_ref"]
        ),
    )


def test_attestation_against_an_unknown_review_is_rejected(customer_id):
    rejects(
        FOREIGN_KEY_VIOLATION,
        _INSERT_ATTESTATION,
        _attestation_params(customer_id, "REV-2026-000000002"),
    )


def test_invalid_attestation_status_is_rejected(customer_id, review_ref):
    rejects(
        INVALID_TEXT_REPRESENTATION,
        _INSERT_ATTESTATION,
        _attestation_params(customer_id, review_ref, status="IGNORED"),
    )


# ── re_attestation_request immutability ───────────────────────────────────────


@pytest.fixture
def attestation(customer_id, review_ref) -> dict:
    params = _attestation_params(customer_id, review_ref)
    execute(_INSERT_ATTESTATION, params)
    return params


def test_attestation_ref_cannot_be_rewritten(attestation):
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.re_attestation_request SET attestation_ref = %s WHERE id = %s",
        (ref("ATT"), attestation["id"]),
    )


def test_requested_at_cannot_be_rewritten(attestation):
    rejects(
        RAISED_EXCEPTION,
        "UPDATE customers.re_attestation_request SET requested_at = now() WHERE id = %s",
        (attestation["id"],),
    )


def test_attestation_status_remains_writable(attestation):
    """The trigger guards identity and the request time, not the response."""
    execute(
        """
        UPDATE customers.re_attestation_request
        SET status = 'COMPLETED', responded_at = now(), responded_by = 'director.one',
            signatory_authority_verified = true
        WHERE id = %s
        """,
        (attestation["id"],),
    )


def test_completion_by_update_still_requires_verified_authority(attestation):
    """The check binds an UPDATE into COMPLETED, not only an INSERT."""
    rejects(
        CHECK_VIOLATION,
        """
        UPDATE customers.re_attestation_request
        SET status = 'COMPLETED', responded_at = now(), responded_by = 'director.one'
        WHERE id = %s
        """,
        (attestation["id"],),
    )
