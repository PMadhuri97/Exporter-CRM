"""Direct-SQL proof of every guard ``onboarding_0022_integrity`` adds.

Each test writes as a caller that bypasses the services would, and expects the
database itself to refuse — or, for what must stay writable, to accept.
"""

from __future__ import annotations

import uuid

import psycopg2.errors
import pytest

from app.modules.onboarding.tests.fixtures.companies import make_company, make_prospect
from app.modules.onboarding.tests.integration._verification_support import (
    insert_document,
    insert_result,
    open_deal,
    pg,
)

pytestmark = pytest.mark.asyncio


# ── crm_document ─────────────────────────────────────────────────────────────


async def test_a_document_cannot_be_deleted():
    """Documents are kept (seven-year retention), pinned or not."""
    company_id = await make_company()
    with pg() as cur:
        document_id = insert_document(cur, company_id=company_id)
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            cur.execute("DELETE FROM onboarding.crm_document WHERE id = %s", (str(document_id),))
        cur.execute("SELECT count(*) FROM onboarding.crm_document WHERE id = %s", (str(document_id),))
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("storage_key", "elsewhere/other.pdf"),
        ("file_name", "renamed.pdf"),
        ("document_type", "other"),
        ("category", "OTHER"),
        ("source", "RXIL"),
        ("content_type", "text/plain"),
        ("size_bytes", 11),
        ("uploaded_at", "2020-01-01T00:00:00Z"),
    ],
)
async def test_what_a_document_is_cannot_change(column, value):
    company_id = await make_company()
    with pg() as cur:
        document_id = insert_document(cur, company_id=company_id)
        with pytest.raises(psycopg2.errors.RaiseException, match=f"Column {column} is immutable"):
            cur.execute(
                f"UPDATE onboarding.crm_document SET {column} = %s WHERE id = %s",
                (value, str(document_id)),
            )


async def test_a_document_cannot_move_to_another_owner():
    first, second = await make_company(), await make_company()
    with pg() as cur:
        document_id = insert_document(cur, company_id=first)
        with pytest.raises(psycopg2.errors.RaiseException, match="Column company_id is immutable"):
            cur.execute(
                "UPDATE onboarding.crm_document SET company_id = %s WHERE id = %s",
                (str(second), str(document_id)),
            )


async def test_the_uploader_is_fixed_once_recorded():
    company_id = await make_company()
    with pg() as cur:
        document_id = insert_document(cur, company_id=company_id)
        cur.execute(
            "UPDATE onboarding.crm_document SET uploaded_by = 'ops-1' WHERE id = %s",
            (str(document_id),),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="Column uploaded_by is immutable"):
            cur.execute(
                "UPDATE onboarding.crm_document SET uploaded_by = 'someone-else' WHERE id = %s",
                (str(document_id),),
            )


async def test_the_scan_verdict_can_still_be_recorded():
    """A real scanner reports after the upload, so the verdict stays writable."""
    company_id = await make_company()
    with pg() as cur:
        document_id = insert_document(cur, company_id=company_id, scan_status="PENDING_SCAN")
        cur.execute(
            "UPDATE onboarding.crm_document SET scan_status = 'QUARANTINED', "
            "scanner_name = 'a-real-scanner' WHERE id = %s",
            (str(document_id),),
        )
        cur.execute(
            "SELECT scan_status, scanner_name FROM onboarding.crm_document WHERE id = %s",
            (str(document_id),),
        )
        assert cur.fetchone() == ("QUARANTINED", "a-real-scanner")


# ── verification_result ──────────────────────────────────────────────────────


async def test_a_verification_result_cannot_be_deleted_even_unreviewed():
    """Before 0022 only a reviewed or pinned result was held by its foreign keys."""
    with pg() as cur:
        result_id = insert_result(cur)
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable"):
            cur.execute(
                "DELETE FROM onboarding.verification_result WHERE id = %s", (str(result_id),)
            )


# ── deal ─────────────────────────────────────────────────────────────────────


async def _deal_at(stage: str) -> uuid.UUID:
    """A deal moved straight to ``stage`` — the move itself is legal SQL, since only a
    deal already closed is frozen."""
    deal_id = await open_deal(await make_prospect())
    reason = "Buyer cancelled." if stage == "WITHDRAWN" else None
    handed_over_at = "now()" if stage == "HANDED_OVER" else "NULL"
    with pg() as cur:
        cur.execute(
            f"UPDATE onboarding.deal SET stage = %s, withdrawal_reason = %s, "
            f"handed_over_at = {handed_over_at} WHERE id = %s",
            (stage, reason, str(deal_id)),
        )
    return deal_id


@pytest.mark.parametrize("stage", ["HANDED_OVER", "WITHDRAWN"])
@pytest.mark.parametrize(
    "assignment",
    [
        "stage = 'OPEN'",
        "stage = 'GATHERING_PAPERWORK'",
        "reference = 'Renamed'",
        "handed_over_at = now() - interval '1 day'",
        "withdrawal_reason = 'Changed my mind.'",
    ],
)
async def test_a_closed_deal_no_longer_changes(stage, assignment):
    deal_id = await _deal_at(stage)
    with pg() as cur, pytest.raises(psycopg2.errors.RaiseException, match="a closed deal"):
        cur.execute(f"UPDATE onboarding.deal SET {assignment} WHERE id = %s", (str(deal_id),))


async def test_an_open_deal_still_changes():
    deal_id = await open_deal(await make_prospect())
    with pg() as cur:
        cur.execute(
            "UPDATE onboarding.deal SET reference = 'Renamed', stage = 'GATHERING_PAPERWORK' "
            "WHERE id = %s",
            (str(deal_id),),
        )
        cur.execute("SELECT reference, stage FROM onboarding.deal WHERE id = %s", (str(deal_id),))
        assert cur.fetchone() == ("Renamed", "GATHERING_PAPERWORK")
