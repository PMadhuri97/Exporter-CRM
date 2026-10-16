"""Direct-SQL proof that the database refuses a link to the wrong record.

Migration ``onboarding_0054_integrity_fks`` added foreign keys and checks that the
services already honoured. Each test writes as a caller that bypasses the services
would, and expects the database itself to refuse — and shows that the correct link is
still accepted.
"""

from __future__ import annotations

import random
import string
import uuid

import psycopg2.errors
import pytest

from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.modules.onboarding.tests.integration._verification_support import (
    insert_result,
    insert_review,
    pg,
)

pytestmark = pytest.mark.asyncio


def _pan() -> str:
    letters = "".join(random.choices(string.ascii_uppercase, k=5))
    digits = "".join(random.choices(string.digits, k=4))
    return f"{letters}{digits}{random.choice(string.ascii_uppercase)}"


def _cycle(cur, company_id: uuid.UUID) -> uuid.UUID:
    cycle_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.check_cycle (id, company_id, number, kind, started_at, "
        " created_by, source) VALUES (%s, %s, 1, 'INITIAL', now(), 'sql', 'test')",
        (str(cycle_id), str(company_id)),
    )
    return cycle_id


def _decision(cur, company_id: uuid.UUID) -> uuid.UUID:
    """The company's first background-check decision: NOT_STARTED -> IN_REVIEW."""
    decision_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
        " to_value, decided_by, decided_by_kind, source) "
        "VALUES (%s, %s, 'NOT_STARTED', 'IN_REVIEW', 'sql', 'MANUAL', 'MANUAL')",
        (str(decision_id), str(company_id)),
    )
    return decision_id


def _activity(cur, company_id: uuid.UUID) -> uuid.UUID:
    activity_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.exporter_activity (id, customer_id, activity_type, subject, "
        " actor_id, occurred_at, due_at) "
        "VALUES (%s, %s, 'FOLLOW_UP', 'Call back', 'sql', now(), now())",
        (str(activity_id), str(company_id)),
    )
    return activity_id


def _sanctions_run(cur, company_id: uuid.UUID, cycle_id: uuid.UUID | None = None) -> uuid.UUID:
    run_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.sanctions_run (id, company_id, subject_type, subject_name, "
        " cycle_id, performed_by, performed_at) "
        "VALUES (%s, %s, 'COMPANY', 'Acme Exports', %s, 'sql', now())",
        (str(run_id), str(company_id), str(cycle_id) if cycle_id else None),
    )
    return run_id


# ── Evidence, history ────────────────────────────────────────────────────────


async def test_evidence_cannot_cite_a_review_that_does_not_exist():
    with pg() as cur:
        company_id = insert_company(cur)
        decision_id = _decision(cur, company_id)
        result_id = insert_result(cur, entity_type="EXPORTER", entity_reference=company_id)
        insert = (
            "INSERT INTO onboarding.background_check_evidence (id, decision_id, kind, "
            " verification_result_id, verification_review_id) "
            "VALUES (%s, %s, 'VERIFICATION_RESULT', %s, %s)"
        )
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                insert, (str(uuid.uuid4()), str(decision_id), str(result_id), str(uuid.uuid4()))
            )

        review_id = insert_review(cur, result_id)
        cur.execute(insert, (str(uuid.uuid4()), str(decision_id), str(result_id), str(review_id)))


async def test_a_history_row_cannot_name_a_deal_that_does_not_exist():
    with pg() as cur:
        company_id = insert_company(cur)
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO onboarding.exporter_lifecycle_history (id, customer_id, dimension, "
                " event_type, to_status, deal_id) VALUES (%s, %s, 'deal', 'deal_opened', 'OPEN', %s)",
                (str(uuid.uuid4()), str(company_id), str(uuid.uuid4())),
            )


# ── Check cycles belong to the company they scope ────────────────────────────


async def test_a_sanctions_run_cannot_use_another_companys_cycle():
    with pg() as cur:
        company_id, other_company_id = insert_company(cur), insert_company(cur)
        other_cycle = _cycle(cur, other_company_id)
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            _sanctions_run(cur, company_id, other_cycle)

        _sanctions_run(cur, company_id, _cycle(cur, company_id))


async def test_a_verification_result_cannot_use_another_companys_cycle():
    with pg() as cur:
        company_id, other_company_id = insert_company(cur), insert_company(cur)
        other_cycle = _cycle(cur, other_company_id)
        insert = (
            "INSERT INTO onboarding.verification_result (id, verification_type, entity_type, "
            " entity_reference, provider, status, performed_at, raw_result, normalized_result, "
            " subject_company_id, cycle_id) "
            "VALUES (%s, 'KYB', 'EXPORTER', %s, 'manual', 'PASSED', now(), '{}', '{}', %s, %s)"
        )
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                insert, (str(uuid.uuid4()), str(company_id), str(company_id), str(other_cycle))
            )

        own_cycle = _cycle(cur, company_id)
        cur.execute(insert, (str(uuid.uuid4()), str(company_id), str(company_id), str(own_cycle)))


async def test_a_result_with_a_cycle_but_no_subject_still_needs_a_real_cycle():
    """The plain foreign key stays beside the composite one for exactly this row."""
    with pg() as cur:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO onboarding.verification_result (id, verification_type, entity_type, "
                " entity_reference, provider, status, performed_at, raw_result, "
                " normalized_result, cycle_id) "
                "VALUES (%s, 'KYC', 'DIRECTOR', %s, 'manual', 'PASSED', now(), '{}', '{}', %s)",
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())),
            )


# ── A sanctions hit is on a list its run screened ────────────────────────────


async def test_a_hit_must_be_on_a_list_the_run_screened():
    code = "TEST_" + uuid.uuid4().hex[:12].upper()
    with pg() as cur:
        company_id = insert_company(cur)
        list_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO onboarding.sanctions_list (id, code, version, name, list_version_date) "
            "VALUES (%s, %s, 1, 'Test list', current_date)",
            (str(list_id), code),
        )
        run_id = _sanctions_run(cur, company_id)
        cur.execute(
            "INSERT INTO onboarding.sanctions_run_list (id, run_id, list_id, code, "
            " list_version_date) VALUES (%s, %s, %s, %s, current_date)",
            (str(uuid.uuid4()), str(run_id), str(list_id), code),
        )
        insert = (
            "INSERT INTO onboarding.sanctions_hit (id, run_id, list_code, matched_name) "
            "VALUES (%s, %s, %s, 'A. Person')"
        )
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(insert, (str(uuid.uuid4()), str(run_id), "NOT_SCREENED"))

        cur.execute(insert, (str(uuid.uuid4()), str(run_id), code))


# ── A follow-up's completion belongs to the activity's company ───────────────


async def test_a_completion_cannot_name_another_company_than_its_follow_up():
    with pg() as cur:
        company_id, other_company_id = insert_company(cur), insert_company(cur)
        activity_id = _activity(cur, company_id)
        insert = (
            "INSERT INTO onboarding.follow_up_completion (id, activity_id, customer_id, outcome) "
            "VALUES (%s, %s, %s, 'DONE')"
        )
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(insert, (str(uuid.uuid4()), str(activity_id), str(other_company_id)))

        cur.execute(insert, (str(uuid.uuid4()), str(activity_id), str(company_id)))


# ── Derived values agree with what they are derived from ─────────────────────


async def test_identity_type_must_follow_the_pan():
    with pg() as cur:
        company_id = insert_company(cur)
        with pytest.raises(psycopg2.errors.CheckViolation, match="identity_type_derived"):
            cur.execute(
                "UPDATE onboarding.exporter_profile SET pan = %s WHERE customer_id = %s",
                (_pan(), str(company_id)),
            )
        cur.execute(
            "UPDATE onboarding.exporter_profile SET pan = %s, identity_type = 'IN_PAN' "
            "WHERE customer_id = %s",
            (_pan(), str(company_id)),
        )


async def test_a_pan_outranks_a_registration_number():
    with pg() as cur:
        company_id = insert_company(cur)
        with pytest.raises(psycopg2.errors.CheckViolation, match="identity_type_derived"):
            cur.execute(
                "UPDATE onboarding.exporter_profile SET pan = %s, registration_number = 'KVK123',"
                " identity_type = 'FOREIGN_REG' WHERE customer_id = %s",
                (_pan(), str(company_id)),
            )


async def test_a_company_holding_neither_has_no_identity_type():
    with pg() as cur:
        company_id = insert_company(cur)
        with pytest.raises(psycopg2.errors.CheckViolation, match="identity_type_derived"):
            cur.execute(
                "UPDATE onboarding.exporter_profile SET identity_type = 'FOREIGN_REG' "
                "WHERE customer_id = %s",
                (str(company_id),),
            )
        cur.execute(
            "UPDATE onboarding.exporter_profile SET registration_number = %s,"
            " country = 'NL', identity_type = 'FOREIGN_REG' WHERE customer_id = %s",
            ("KVK" + uuid.uuid4().hex[:10], str(company_id)),
        )


async def test_a_branch_state_code_must_be_its_gstins_first_two_characters():
    with pg() as cur:
        company_id = insert_company(cur)
        insert = (
            "INSERT INTO onboarding.exporter_gstin (id, customer_id, gstin, state_code) "
            "VALUES (%s, %s, %s, %s)"
        )
        gstin = "27" + _pan() + "1Z5"
        with pytest.raises(psycopg2.errors.CheckViolation, match="state_code"):
            cur.execute(insert, (str(uuid.uuid4()), str(company_id), gstin, "29"))

        cur.execute(insert, (str(uuid.uuid4()), str(company_id), gstin, "27"))
