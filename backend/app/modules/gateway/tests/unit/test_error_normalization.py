"""Proves the shared envelope shape the gateway's own errors rely on.

The gateway registers no exception handlers of its own — it reuses the
platform-wide ones already wired in app/main.py
(app.platform.middleware.handlers), so an unsupported-version 404
(app.modules.gateway.api.router._reject_version_or_404), a validation
failure, and a genuinely unhandled exception all come back in the identical
JSON shape. This calls the real, shipped handler functions directly (not a
copy of their logic) with each exception type the gateway can produce.
"""
import json

import pytest
from starlette.requests import Request

from app.platform.middleware.handlers import (
    aner_exception_handler,
    unhandled_exception_handler,
)
from app.shared.exceptions import NotFoundError, ValidationError

_ENVELOPE_KEYS = {"error_code", "human_readable_message", "detail", "correlation_id", "timestamp"}


def _request() -> Request:
    scope = {"type": "http", "method": "GET", "path": "/v2/example", "headers": []}
    return Request(scope)


@pytest.mark.asyncio
async def test_404_422_and_500_share_the_same_envelope_shape():
    responses = [
        (await aner_exception_handler(_request(), NotFoundError("API version 'v2' is not supported")), 404),
        (await aner_exception_handler(_request(), ValidationError("bad input")), 422),
        (await unhandled_exception_handler(_request(), RuntimeError("boom")), 500),
    ]

    for response, expected_status in responses:
        assert response.status_code == expected_status
        body = json.loads(bytes(response.body))
        assert _ENVELOPE_KEYS <= body.keys()


@pytest.mark.asyncio
async def test_unhandled_exception_never_leaks_internal_details():
    response = await unhandled_exception_handler(_request(), RuntimeError("asyncpg.exceptions.PostgresError"))
    body = json.loads(bytes(response.body))
    assert "asyncpg" not in body["detail"]
    assert "asyncpg" not in body["human_readable_message"]
