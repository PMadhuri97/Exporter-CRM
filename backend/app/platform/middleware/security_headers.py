"""Browser hardening headers on every API response.

A plain ASGI middleware rather than ``BaseHTTPMiddleware``: it only adds headers at
``http.response.start``, so it never buffers a body and cannot disturb a streamed
document download.

* ``Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`` — the API
  serves data, never a page, so nothing it returns may run script, load anything or be
  framed. The interactive docs are the one HTML page here and get no CSP (Swagger UI
  loads its script from a CDN); they are off outside local and test anyway.
* ``X-Content-Type-Options: nosniff`` — a document served as ``text/plain`` stays text,
  whatever its bytes look like.
* ``X-Frame-Options: DENY`` — ``frame-ancestors`` for browsers that predate CSP 2.
* ``Referrer-Policy: no-referrer`` — a signed download link never leaks onward.
* ``Strict-Transport-Security`` — only when the load balancer says the request arrived
  over HTTPS (``X-Forwarded-Proto``). Trusting that header here is safe: the worst a
  forged one can do is ask the browser to insist on HTTPS.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_API_CSP = b"default-src 'none'; frame-ancestors 'none'"
_HSTS = b"max-age=31536000"

_ALWAYS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class SecurityHeadersMiddleware:
    """Adds the headers above unless the route already set its own value."""

    def __init__(self, app: ASGIApp, *, docs_paths: tuple[str, ...] = ()) -> None:
        self.app = app
        self._docs_paths = docs_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        is_docs = any(path == p or path.startswith(p + "/") for p in self._docs_paths)
        over_https = any(
            name == b"x-forwarded-proto" and value.split(b",")[0].strip().lower() == b"https"
            for name, value in scope.get("headers", [])
        ) or scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = list(_ALWAYS)
                if not is_docs:
                    extra.append((b"content-security-policy", _API_CSP))
                if over_https:
                    extra.append((b"strict-transport-security", _HSTS))
                headers.extend(pair for pair in extra if pair[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
