from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from app.shared.exceptions import AnerBaseException
from app.shared.value_objects import CurrencyNotRegisteredError

logger = structlog.get_logger(__name__)


async def _extract_idempotency_key(request: Request, exc: Exception | None = None) -> str | None:
    """Extract idempotency key from exception extensions, request state, headers, query, or body."""
    if exc and hasattr(exc, "extensions") and isinstance(exc.extensions, dict):
        key = exc.extensions.get("idempotency_key")
        if key:
            return str(key)
    if hasattr(request.state, "idempotency_key") and request.state.idempotency_key:
        return str(request.state.idempotency_key)
    header_key = request.headers.get("x-idempotency-key") or request.headers.get("idempotency-key")
    if header_key:
        return str(header_key)

    # Try query parameters if query_string is in request scope
    if "query_string" in request.scope:
        try:
            query_key = request.query_params.get("idempotency_key") or request.query_params.get("x-idempotency-key")
            if query_key:
                return str(query_key)
        except Exception:  # noqa: BLE001
            pass

    # Try JSON body (safe read if content-type is json or method is POST/PUT/PATCH)
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("application/json") or request.method in ("POST", "PUT", "PATCH"):
        try:
            body_json = await request.json()
            if isinstance(body_json, dict):
                key = body_json.get("idempotency_key") or body_json.get("x-idempotency-key")
                if key:
                    return str(key)
        except Exception:  # noqa: BLE001
            pass

    return None


def _sanitize_message(message: str) -> str:
    """Ensure message exposes no internal system details, DB error strings, or stack traces."""
    if not message:
        return "An error occurred during request processing"

    msg_lower = message.lower()
    # Mask database and internal system traces
    if any(
        db_term in msg_lower
        for db_term in (
            "asyncpg",
            "sqlalchemy",
            "psycopg",
            "pgcode",
            "sqlstate",
            "foreign key constraint",
            "unique constraint",
            "syntaxerror",
            "traceback",
        )
    ):
        return "Internal system processing error"
    return message


async def aner_exception_handler(request: Request, exc: AnerBaseException) -> JSONResponse:
    import structlog.contextvars

    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id")
    idempotency_key = await _extract_idempotency_key(request, exc)
    now_iso = datetime.now(UTC).isoformat()

    clean_message = _sanitize_message(exc.detail)

    logger.warning(
        "application_error",
        error_code=exc.error_code,
        detail=clean_message,
        error_context=exc.extensions,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )

    content = {
        "error_code": exc.error_code or "APPLICATION_ERROR",
        "human_readable_message": clean_message,
        "detail": clean_message,
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
        "timestamp": now_iso,
    }

    if exc.extensions:
        content["error_context"] = exc.extensions

    causes = []
    current_exc = exc.__cause__
    while current_exc is not None:
        if isinstance(current_exc, AnerBaseException):
            cause_data: dict[str, Any] = {
                "detail": _sanitize_message(current_exc.detail),
                "error_code": current_exc.error_code,
            }
            if current_exc.extensions:
                cause_data["error_context"] = current_exc.extensions
            causes.append(cause_data)
        current_exc = current_exc.__cause__

    if causes:
        content["causes"] = causes

    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


async def currency_not_registered_handler(
    request: Request, exc: CurrencyNotRegisteredError
) -> JSONResponse:
    import structlog.contextvars

    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id")
    idempotency_key = await _extract_idempotency_key(request)
    now_iso = datetime.now(UTC).isoformat()

    detail = str(exc.args[0]) if exc.args else "Asset is not in the currency registry"
    clean_message = _sanitize_message(detail)

    logger.warning("application_error", error_code="UNSUPPORTED_CURRENCY", detail=clean_message)

    return JSONResponse(
        status_code=422,
        content={
            "error_code": "UNSUPPORTED_CURRENCY",
            "human_readable_message": clean_message,
            "detail": clean_message,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "timestamp": now_iso,
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import structlog.contextvars

    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id")
    idempotency_key = await _extract_idempotency_key(request)
    now_iso = datetime.now(UTC).isoformat()

    logger.error("unhandled_exception", exc_info=exc)

    # Unhandled exceptions (500 Internal Server Errors) must always return a generic
    # message to guarantee that internal details or identifier strings never leak.
    clean_message = "An unexpected error occurred"

    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "human_readable_message": clean_message,
            "detail": clean_message,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "timestamp": now_iso,
        },
    )
