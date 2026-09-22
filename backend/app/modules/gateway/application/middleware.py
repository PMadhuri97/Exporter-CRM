"""The gateway's request-handling pipeline: correlation-ID resolution plus
append-only request logging, scoped to exactly the paths this module owns.

Registered as the OUTERMOST ASGI middleware on the shared FastAPI app (see
app/main.py), added after app.platform.middleware.services.CorrelationIdMiddleware
so its own response-header write runs last and wins. For any path this module
does not own it is a pure pass-through — `dispatch()` returns immediately —
so it can never change behavior for the platform's existing internal
/api/v1 traffic. Version-prefix REJECTION (unsupported /v2/...) is deliberately
NOT handled here: it is a route (see api/router.py), so a rejected request
still passes through FastAPI's normal exception-handler pipeline and comes
back in the platform's shared, normalized error shape.

Known gap: app.platform.middleware.services.CorrelationIdMiddleware still runs
for gateway paths too (it is not gateway-specific) and binds whatever raw
X-Correlation-Id header was supplied — including an invalid one — into
structlog's contextvars for the platform-wide `request_completed` log line.
This middleware does not attempt to reconcile that: doing so would mean
mutating the ASGI scope's header list before call_next, which was judged not
worth the fragility for a first-slice skeleton. The value returned to the
caller (response header, request.state.correlation_id, and the
api_request_logs row) is always the validated one; only the platform's own
internal log line for the same request may show the raw, rejected value
alongside it. Flagged for whoever picks up S1T2+ to revisit if it proves
confusing in practice.
"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.modules.gateway.application.services import GatewayRequestLogger
from app.modules.gateway.config import CORRELATION_ID_HEADER, is_valid_correlation_id

logger = structlog.get_logger(__name__)


def owns_path(path: str) -> bool:
    """True for exactly the paths this pipeline is responsible for.

    "/health" and every "/v<digits>[...]" — never anything under the
    platform's existing internal prefix (settings.API_V1_PREFIX, "/api/v1"),
    since that always starts with "api", not a version segment.
    """
    if path == "/health":
        return True
    segment = path.strip("/").split("/", 1)[0]
    return len(segment) > 1 and segment[0] == "v" and segment[1:].isdigit()


def resolve_correlation_id(request: Request) -> str:
    """Validated caller-supplied ID, or a freshly generated one.

    An invalid supplied value is never echoed back — only ever replaced —
    since it may already be unsafe to place in a header, a log line, or a
    database column by the time it reaches here.
    """
    supplied = request.headers.get(CORRELATION_ID_HEADER)
    if supplied and is_valid_correlation_id(supplied):
        return supplied
    if supplied:
        logger.warning("gateway_correlation_id_invalid", supplied=supplied[:200])
    return str(uuid.uuid4())


class GatewayRequestMiddleware(BaseHTTPMiddleware):
    """Correlation-ID handling + api_request_logs write, gateway paths only."""

    def __init__(self, app, request_logger: GatewayRequestLogger | None = None) -> None:
        super().__init__(app)
        self._request_logger = request_logger or GatewayRequestLogger()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not owns_path(request.url.path):
            return await call_next(request)

        correlation_id = resolve_correlation_id(request)
        request.state.correlation_id = correlation_id
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000)
            await self._request_logger.record(
                correlation_id=correlation_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000)
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        await self._request_logger.record(
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response
