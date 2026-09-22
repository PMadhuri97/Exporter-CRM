import pytest


@pytest.mark.asyncio
async def test_missing_correlation_id_is_generated(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert "x-correlation-id" in response.headers
    assert response.headers["x-correlation-id"]


@pytest.mark.asyncio
async def test_valid_supplied_correlation_id_is_propagated_unchanged(client):
    cid = "test-gateway-correlation-id-123"
    response = await client.get("/health", headers={"X-Correlation-Id": cid})
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == cid


@pytest.mark.asyncio
async def test_invalid_supplied_correlation_id_is_replaced_not_echoed(client):
    invalid = "has a space and is way too long " + ("x" * 200)
    response = await client.get("/health", headers={"X-Correlation-Id": invalid})
    assert response.status_code == 200
    returned = response.headers["x-correlation-id"]
    assert returned != invalid
    assert returned
