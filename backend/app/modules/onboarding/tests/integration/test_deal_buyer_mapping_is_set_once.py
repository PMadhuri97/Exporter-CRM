"""Direct-SQL proof that a deal buyer's mapping is written whole and never changed.

Migration ``onboarding_0056_buyer_map_cols`` moved the buyer migration's answer onto
``deal_buyer``: ``mapped_company_id``, ``match_rule``, ``matched_by``, ``matched_at`` and
``mapping_run_id``. A mapping is the record of how a buyer's identity was decided, and a
re-run of the migration skips any row that has one, so it must arrive complete and stay
exactly as written.
"""

from __future__ import annotations

import uuid

import psycopg2.errors
import pytest

from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.modules.onboarding.tests.integration._verification_support import deal_buyer, pg

pytestmark = pytest.mark.asyncio

MAP = (
    "UPDATE onboarding.deal_buyer SET mapped_company_id = %s, match_rule = 'NEW', "
    "matched_by = 'tester', matched_at = now(), mapping_run_id = %s WHERE id = %s"
)


async def _mapped_buyer(cur) -> uuid.UUID:
    _, _, buyer_id = await deal_buyer(name=f"Mapped {uuid.uuid4().hex[:8]}")
    cur.execute(MAP, (str(insert_company(cur)), "run-1", str(buyer_id)))
    return buyer_id


async def test_a_complete_mapping_is_written_once():
    with pg() as cur:
        buyer_id = await _mapped_buyer(cur)
        cur.execute(
            "SELECT match_rule, mapping_run_id FROM onboarding.deal_buyer WHERE id = %s",
            (str(buyer_id),),
        )
        assert cur.fetchone() == ("NEW", "run-1")


async def test_a_mapping_cannot_move_to_another_company():
    with pg() as cur:
        buyer_id = await _mapped_buyer(cur)
        with pytest.raises(
            psycopg2.errors.RaiseException, match="Column mapped_company_id is immutable"
        ):
            cur.execute(
                "UPDATE onboarding.deal_buyer SET mapped_company_id = %s WHERE id = %s",
                (str(insert_company(cur)), str(buyer_id)),
            )


@pytest.mark.parametrize(
    ("column", "value"),
    [("match_rule", "PAN"), ("matched_by", "someone else"), ("mapping_run_id", "run-2")],
)
async def test_a_mapping_cannot_be_changed(column, value):
    with pg() as cur:
        buyer_id = await _mapped_buyer(cur)
        with pytest.raises(psycopg2.errors.RaiseException, match=f"Column {column} is immutable"):
            cur.execute(
                f"UPDATE onboarding.deal_buyer SET {column} = %s WHERE id = %s",
                (value, str(buyer_id)),
            )


async def test_a_mapping_cannot_be_cleared():
    with pg() as cur:
        buyer_id = await _mapped_buyer(cur)
        with pytest.raises(psycopg2.errors.RaiseException, match="is immutable"):
            cur.execute(
                "UPDATE onboarding.deal_buyer SET mapped_company_id = NULL, match_rule = NULL, "
                "matched_at = NULL, mapping_run_id = NULL WHERE id = %s",
                (str(buyer_id),),
            )


@pytest.mark.parametrize("missing", ["match_rule", "matched_at", "mapping_run_id"])
async def test_a_partial_mapping_is_refused(missing):
    columns = {
        "match_rule": "'NEW'",
        "matched_at": "now()",
        "mapping_run_id": "'run-1'",
    }
    del columns[missing]
    assignments = ", ".join(f"{column} = {value}" for column, value in columns.items())
    with pg() as cur:
        _, _, buyer_id = await deal_buyer(name=f"Partial {uuid.uuid4().hex[:8]}")
        with pytest.raises(psycopg2.errors.CheckViolation, match="ck_deal_buyer_mapping_complete"):
            cur.execute(
                f"UPDATE onboarding.deal_buyer SET mapped_company_id = %s, {assignments} "
                "WHERE id = %s",
                (str(insert_company(cur)), str(buyer_id)),
            )


async def test_a_mapping_names_an_existing_company():
    with pg() as cur:
        _, _, buyer_id = await deal_buyer(name=f"Nowhere {uuid.uuid4().hex[:8]}")
        with pytest.raises(psycopg2.errors.ForeignKeyViolation, match="fk_deal_buyer_mapped_company"):
            cur.execute(MAP, (str(uuid.uuid4()), "run-1", str(buyer_id)))
