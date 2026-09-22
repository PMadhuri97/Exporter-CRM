import pytest


@pytest.mark.asyncio
async def test_v1_undefined_path_returns_404(client):
    """No real endpoints exist under /v1 yet — a plain 404 is expected."""
    response = await client.get("/v1/does-not-exist-yet")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bare_v1_returns_404(client):
    response = await client.get("/v1")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_version_prefix_returns_normalized_404(client):
    response = await client.get("/v2/anything")
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "NOT_FOUND"
    assert "correlation_id" in body


@pytest.mark.asyncio
async def test_another_unsupported_version_prefix_also_rejected(client):
    response = await client.get("/v99/whatever")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_unrelated_unmatched_path_is_an_ordinary_404(client):
    """Paths that were never version-shaped keep today's plain 404 shape —
    the gateway's fallback route must not widen its normalization to every
    unmatched URL on the whole application."""
    response = await client.get("/this-path-has-never-existed")
    assert response.status_code == 404
    assert "error_code" not in response.json()
