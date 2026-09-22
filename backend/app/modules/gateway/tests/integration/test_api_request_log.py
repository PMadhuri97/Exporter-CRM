"""api_request_logs — write path and append-only enforcement.

Mirrors app/modules/audit/tests/integration/test_audit.py's psycopg2 pattern:
the async app writes the row, a raw sync connection verifies it and proves
the DB trigger, independent of the ORM session that wrote it.
"""
import uuid

import psycopg2
import pytest


def _pg_connect():
    from app.platform.configuration.config import get_settings

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


@pytest.mark.asyncio
async def test_request_writes_an_api_request_log_row(client):
    cid = f"test-log-write-{uuid.uuid4().hex[:12]}"
    response = await client.get("/health", headers={"X-Correlation-Id": cid})
    assert response.status_code == 200

    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT method, path, status_code, duration_ms, customer_id "
            "FROM gateway.api_request_logs WHERE correlation_id = %s",
            (cid,),
        )
        row = cur.fetchone()
        assert row is not None, "no api_request_logs row was written for this request"
        method, path, status_code, duration_ms, customer_id = row
        assert method == "GET"
        assert path == "/health"
        assert status_code == 200
        assert duration_ms >= 0
        assert customer_id is None  # no authentication exists yet in this slice
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_unsupported_version_rejection_is_also_logged(client):
    cid = f"test-log-reject-{uuid.uuid4().hex[:12]}"
    response = await client.get("/v2/anything", headers={"X-Correlation-Id": cid})
    assert response.status_code == 404

    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT status_code FROM gateway.api_request_logs WHERE correlation_id = %s",
            (cid,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 404
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_update_blocked_by_trigger(client):
    cid = f"test-log-update-{uuid.uuid4().hex[:12]}"
    await client.get("/health", headers={"X-Correlation-Id": cid})

    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM gateway.api_request_logs WHERE correlation_id = %s", (cid,))
    row_id = cur.fetchone()[0]
    with pytest.raises(psycopg2.Error):
        cur.execute(
            "UPDATE gateway.api_request_logs SET status_code = 599 WHERE id = %s",
            (str(row_id),),
        )
        conn.commit()
    conn.rollback()
    cur.close()
    conn.close()


@pytest.mark.asyncio
async def test_delete_blocked_by_trigger(client):
    cid = f"test-log-delete-{uuid.uuid4().hex[:12]}"
    await client.get("/health", headers={"X-Correlation-Id": cid})

    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM gateway.api_request_logs WHERE correlation_id = %s", (cid,))
    row_id = cur.fetchone()[0]
    with pytest.raises(psycopg2.Error):
        cur.execute("DELETE FROM gateway.api_request_logs WHERE id = %s", (str(row_id),))
        conn.commit()
    conn.rollback()
    cur.close()
    conn.close()
