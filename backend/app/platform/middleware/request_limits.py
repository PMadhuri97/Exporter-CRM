"""A ceiling on the size of any request body.

Without one, a multipart upload is parsed — and spooled to memory and disk — in full
before a route sees it and can apply its own limit. This middleware refuses a request
whose ``Content-Length`` is over the ceiling before reading a byte (413), and counts
the bytes of one sent without a length (chunked), stopping it at the same point.

The ceiling sits just above the largest thing any route accepts (a 25 MB document or
CSV import, plus multipart framing); each route still applies its own, smaller limit.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BODY_BYTES = 26 * 1024 * 1024

_DETAIL = f"The request is larger than {MAX_REQUEST_BODY_BYTES // (1024 * 1024)} MB"


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = next(
            (value for name, value in scope.get("headers", []) if name == b"content-length"),
            None,
        )
        if declared is not None:
            try:
                too_large = int(declared) > self._max
            except ValueError:
                too_large = False  # malformed; the server rejects it on its own
            if too_large:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error_code": "REQUEST_TOO_LARGE",
                        "human_readable_message": _DETAIL,
                        "detail": _DETAIL,
                    },
                )
                await response(scope, receive, send)
                return

        received = 0

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    # Raised inside the route's body parsing, where FastAPI lets an
                    # HTTPException through as the response.
                    raise HTTPException(status_code=413, detail=_DETAIL)
            return message

        await self.app(scope, counted_receive, send)
