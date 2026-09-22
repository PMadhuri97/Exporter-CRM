import pytest


@pytest.mark.asyncio
async def test_health_returns_200_with_dependency_breakdown(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "database" in body["dependencies"]
    assert body["dependencies"]["database"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_is_unversioned(client):
    """/health is gateway infrastructure, not a v1 business capability."""
    response = await client.get("/health")
    assert response.status_code == 200
    not_under_v1 = await client.get("/v1/health")
    assert not_under_v1.status_code == 404
