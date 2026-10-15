"""Direct-SQL proof of every constraint and trigger ``onboarding_0021_verif_review``
adds (``docs/contracts/migration-register.md`` §2: "every new constraint
gets a direct-SQL violation test").

Nothing here goes through the ORM or the service: each test writes the violating
statement itself, so what is proved is the database's own guarantee.
"""

from __future__ import annotations

import uuid

import psycopg2.errors
import psycopg2.extras
import pytest

from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.modules.onboarding.tests.integration._verification_support import (
    insert_result,
    insert_review,
    pg,
)

pytestmark = pytest.mark.asyncio


# ── verification_review: append-only ────────────────────────────────────────


async def test_a_review_cannot_be_updated():
    with pg() as cur:
        review_id = insert_review(cur, insert_result(cur))
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            cur.execute(
                "UPDATE onboarding.verification_review SET review_status = 'REJECTED' "
                "WHERE id = %s",
                (str(review_id),),
            )


async def test_a_review_cannot_be_deleted():
    with pg() as cur:
        review_id = insert_review(cur, insert_result(cur))
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            cur.execute(
                "DELETE FROM onboarding.verification_review WHERE id = %s", (str(review_id),)
            )


# ── verification_review: one chain per result ───────────────────────────────


async def test_a_result_has_only_one_first_review():
    """uq_verification_review_first — two concurrent first reviews cannot both land."""
    with pg() as cur:
        result_id = insert_result(cur)
        insert_review(cur, result_id)
        with pytest.raises(psycopg2.errors.UniqueViolation, match="uq_verification_review_first"):
            insert_review(cur, result_id, status="REJECTED")


async def test_a_review_is_superseded_at_most_once():
    """uq_verification_review_supersedes — the chain cannot fork."""
    with pg() as cur:
        result_id = insert_result(cur)
        first = insert_review(cur, result_id)
        insert_review(cur, result_id, supersedes=first, note="second look")
        with pytest.raises(
            psycopg2.errors.UniqueViolation, match="uq_verification_review_supersedes"
        ):
            insert_review(cur, result_id, supersedes=first, note="racing second look")


async def test_a_review_cannot_supersede_a_review_of_another_result():
    """fk_verification_review_supersedes is composite on (id, verification_result_id)."""
    with pg() as cur:
        other = insert_review(cur, insert_result(cur))
        result_id = insert_result(cur)
        insert_review(cur, result_id)
        with pytest.raises(
            psycopg2.errors.ForeignKeyViolation, match="fk_verification_review_supersedes"
        ):
            insert_review(cur, result_id, supersedes=other, note="wrong chain")


async def test_a_review_cannot_supersede_itself():
    with pg() as cur:
        result_id = insert_result(cur)
        review_id = uuid.uuid4()
        with pytest.raises(psycopg2.errors.CheckViolation, match="ck_verification_review_not_self"):
            cur.execute(
                "INSERT INTO onboarding.verification_review (id, verification_result_id, "
                " review_status, reviewed_by, note, supersedes_review_id) "
                "VALUES (%s, %s, 'ACCEPTED', 'sql', 'x', %s)",
                (str(review_id), str(result_id), str(review_id)),
            )


@pytest.mark.parametrize("note", [None, "", "   "])
async def test_a_superseding_review_must_have_a_note(note):
    with pg() as cur:
        result_id = insert_result(cur)
        first = insert_review(cur, result_id)
        with pytest.raises(
            psycopg2.errors.CheckViolation, match="ck_verification_review_supersede_note"
        ):
            insert_review(cur, result_id, supersedes=first, note=note)


async def test_a_review_must_name_an_existing_result():
    with pg() as cur, pytest.raises(
        psycopg2.errors.ForeignKeyViolation, match="fk_verification_review_result_id"
    ):
        insert_review(cur, uuid.uuid4())


async def test_a_reviewed_result_cannot_be_deleted():
    """The review keeps the result it is about. Two guards hold it: the review's
    ``ON DELETE RESTRICT``, and — firing first — 0022's refusal to delete any
    verification result at all (``test_crm_integrity_guards_0022.py``)."""
    with pg() as cur:
        result_id = insert_result(cur)
        insert_review(cur, result_id)
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            cur.execute(
                "DELETE FROM onboarding.verification_result WHERE id = %s", (str(result_id),)
            )


async def test_the_review_status_uses_the_existing_enum():
    with pg() as cur:
        result_id = insert_result(cur)
        with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
            insert_review(cur, result_id, status="MAYBE")


# ── verification_result: reviewed outcome freeze (contract §2) ─────────────────────


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'FAILED'",
        "risk_level = 'HIGH'",
        "normalized_result = '{\"changed\": true}'::jsonb",
        "valid_until = now() + interval '1 year'",
    ],
    ids=["status", "risk_level", "normalized_result", "valid_until"],
)
async def test_a_reviewed_result_outcome_cannot_change(assignment):
    with pg() as cur:
        result_id = insert_result(cur)
        insert_review(cur, result_id)
        with pytest.raises(psycopg2.errors.RaiseException, match="has been reviewed"):
            cur.execute(
                f"UPDATE onboarding.verification_result SET {assignment} WHERE id = %s",
                (str(result_id),),
            )


async def test_an_unreviewed_result_outcome_can_still_change():
    with pg() as cur:
        result_id = insert_result(cur, status="PENDING")
        cur.execute(
            "UPDATE onboarding.verification_result SET status = 'PASSED', risk_level = 'LOW' "
            "WHERE id = %s",
            (str(result_id),),
        )
        cur.execute(
            "SELECT status, risk_level FROM onboarding.verification_result WHERE id = %s",
            (str(result_id),),
        )
        assert cur.fetchone() == ("PASSED", "LOW")


async def test_the_legacy_review_trigger_is_still_in_place():
    """trg_verification_result_field_immutability (0006) is kept, never dropped."""
    with pg() as cur:
        result_id = insert_result(cur)
        cur.execute(
            "UPDATE onboarding.verification_result SET review_status = 'ACCEPTED' WHERE id = %s",
            (str(result_id),),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="review_status is immutable"):
            cur.execute(
                "UPDATE onboarding.verification_result SET review_status = 'REJECTED' "
                "WHERE id = %s",
                (str(result_id),),
            )


# ── verification_result: evidence and snapshot (contract §3, §6) ─────────────────


@pytest.mark.parametrize(
    ("column", "first", "second"),
    [
        ("evidence_note", "'first note'", "'rewritten'"),
        ("subject_snapshot", "'{\"name\": \"A\"}'::jsonb", "'{\"name\": \"B\"}'::jsonb"),
    ],
)
async def test_evidence_and_snapshot_are_frozen_once_set(column, first, second):
    with pg() as cur:
        result_id = insert_result(cur)
        cur.execute(
            f"UPDATE onboarding.verification_result SET {column} = {first} WHERE id = %s",
            (str(result_id),),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match=f"{column} is immutable"):
            cur.execute(
                f"UPDATE onboarding.verification_result SET {column} = {second} WHERE id = %s",
                (str(result_id),),
            )


async def test_evidence_refs_are_frozen_from_the_moment_of_recording():
    """``evidence_refs`` is never null (it defaults to ``[]``), so it is "set" at
    insert: references cannot be added to a result after it was recorded."""
    with pg() as cur:
        result_id = insert_result(cur)
        with pytest.raises(psycopg2.errors.RaiseException, match="evidence_refs is immutable"):
            cur.execute(
                "UPDATE onboarding.verification_result "
                "SET evidence_refs = '[{\"type\": \"url\", \"ref\": \"a\"}]'::jsonb "
                "WHERE id = %s",
                (str(result_id),),
            )


async def test_evidence_refs_defaults_to_an_empty_array_and_must_be_one():
    with pg() as cur:
        result_id = insert_result(cur)
        cur.execute(
            "SELECT evidence_refs FROM onboarding.verification_result WHERE id = %s",
            (str(result_id),),
        )
        assert cur.fetchone() == ([],)
        with pytest.raises(
            psycopg2.errors.CheckViolation, match="ck_verification_result_evidence_refs_array"
        ):
            cur.execute(
                "INSERT INTO onboarding.verification_result (id, verification_type, entity_type, "
                " entity_reference, provider, status, performed_at, raw_result, "
                " normalized_result, evidence_refs) VALUES (%s, 'KYC', 'DIRECTOR', %s, 'manual', "
                " 'REVIEW', now(), '{}', '{}', %s)",
                (str(uuid.uuid4()), str(uuid.uuid4()), psycopg2.extras.Json({"type": "url"})),
            )


# ── screening_review_item: status CHECK (contract §5) ──────────────────────────────


async def test_a_screening_status_outside_the_four_is_refused():
    with pg() as cur:
        company_id = insert_company(cur)
        with pytest.raises(
            psycopg2.errors.CheckViolation, match="ck_screening_review_item_status"
        ):
            cur.execute(
                "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status) "
                "VALUES (%s, %s, 'website-reviewed', 'MAYBE')",
                (str(uuid.uuid4()), str(company_id)),
            )


@pytest.mark.parametrize("status", ["NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT"])
async def test_each_of_the_four_screening_statuses_is_accepted(status):
    with pg() as cur:
        company_id = insert_company(cur)
        cur.execute(
            "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status) "
            "VALUES (%s, %s, 'website-reviewed', %s)",
            (str(uuid.uuid4()), str(company_id), status),
        )


async def test_the_screening_append_only_trigger_is_still_in_place():
    with pg() as cur:
        company_id = insert_company(cur)
        cur.execute(
            "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status) "
            "VALUES (%s, %s, 'website-reviewed', 'PASSED')",
            (str(uuid.uuid4()), str(company_id)),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            cur.execute(
                "UPDATE onboarding.screening_review_item SET status = 'FAILED' "
                "WHERE customer_id = %s",
                (str(company_id),),
            )
