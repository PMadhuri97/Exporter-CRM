from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import URL

from app.platform.middleware.handlers import aner_exception_handler, unhandled_exception_handler
from app.shared.exceptions import AnerBaseException


@pytest.mark.asyncio
async def test_aner_exception_handler_returns_structured_error():
    request = MagicMock()
    request.state = MagicMock()
    request.state.idempotency_key = "idemp-abc-123"
    request.headers = {"x-idempotency-key": "idemp-abc-123"}

    exc = AnerBaseException(
        detail="Invalid posting amount",
        error_code="INVALID_AMOUNT",
        status_code=422,
    )

    response = await aner_exception_handler(request, exc)
    assert response.status_code == 422

    import json

    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "INVALID_AMOUNT"
    assert body["human_readable_message"] == "Invalid posting amount"
    assert body["detail"] == "Invalid posting amount"
    assert body["idempotency_key"] == "idemp-abc-123"
    assert "timestamp" in body


@pytest.mark.asyncio
async def test_unhandled_exception_handler_sanitizes_internal_errors():
    request = MagicMock()
    request.state = MagicMock()
    request.state.idempotency_key = None
    request.headers = {}

    exc = Exception("asyncpg.exceptions.UniqueViolationError: table constraint violated")

    response = await unhandled_exception_handler(request, exc)
    assert response.status_code == 500

    import json

    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "INTERNAL_ERROR"
    assert body["human_readable_message"] == "An unexpected error occurred"
    assert body["detail"] == "An unexpected error occurred"
    assert "asyncpg" not in body["human_readable_message"]
    assert "timestamp" in body


@pytest.mark.asyncio
async def test_aner_exception_handler_chaining():
    # Arrange
    root_cause = AnerBaseException(
        detail="Database connection failed", error_code="DB_ERROR", extensions={"retry_count": 3}
    )

    middle_cause = AnerBaseException(
        detail="Ledger post failed", error_code="LEDGER_ERROR", extensions={"asset": "USD"}
    )
    middle_cause.__cause__ = root_cause

    top_error = AnerBaseException(
        detail="Settlement failed",
        error_code="SETTLEMENT_ERROR",
        extensions={"transaction_id": "123"},
    )
    top_error.__cause__ = middle_cause

    # Mock request
    scope = {
        "type": "http",
        "method": "GET",
        "url": URL("http://testserver/"),
        "headers": [],
    }
    mock_request = Request(scope)

    # Act
    response: JSONResponse = await aner_exception_handler(mock_request, top_error)
    body = response.body.decode()

    import json

    data = json.loads(body)

    # Assert Main Error
    assert data["detail"] == "Settlement failed"
    assert data["error_code"] == "SETTLEMENT_ERROR"
    assert data["error_context"] == {"transaction_id": "123"}

    # Assert Hierarchy
    assert "causes" in data
    assert len(data["causes"]) == 2

    # First cause (middle)
    assert data["causes"][0]["detail"] == "Ledger post failed"
    assert data["causes"][0]["error_code"] == "LEDGER_ERROR"
    assert data["causes"][0]["error_context"] == {"asset": "USD"}

    # Second cause (root)
    assert data["causes"][1]["detail"] == "Database connection failed"
    assert data["causes"][1]["error_code"] == "DB_ERROR"
    assert data["causes"][1]["error_context"] == {"retry_count": 3}
