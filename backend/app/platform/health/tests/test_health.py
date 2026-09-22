import pytest


@pytest.mark.asyncio
async def test_liveness(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "version" in body
    assert "environment" in body


@pytest.mark.asyncio
async def test_liveness_returns_correlation_id_header(client):
    response = await client.get("/api/v1/health")
    assert "x-correlation-id" in response.headers


@pytest.mark.asyncio
async def test_liveness_accepts_existing_correlation_id(client):
    cid = "test-correlation-id-123"
    response = await client.get("/api/v1/health", headers={"X-Correlation-Id": cid})
    assert response.headers["x-correlation-id"] == cid
