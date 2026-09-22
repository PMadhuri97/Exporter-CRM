import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.exc import NoResultFound
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import compile_path, get_route_path

from app.platform.database import services as database
from app.platform.idempotency import (
    IdempotencyKeyType,
    IdempotencyStatus,
    RegistrationResultType,
    ValidationReason,
    bind_idempotency_key,
    complete_key,
    register_key,
    validate_customer_key,
)
from app.platform.middleware.config import IDEMPOTENT_METHODS, IDEMPOTENT_ROUTES
from app.platform.observability.tracing import set_span_correlation_id

logger = structlog.get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request and propagate it in the response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        start = time.perf_counter()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
        )
        # Make the trace searchable by the same ID the client sees in the response.
        set_span_correlation_id(correlation_id)

        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)

        logger.info(
            "request_completed",
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )

        return response


#: The allowlist compiled once, as ``(method, anchored regex, template)``.
#:
#: ``compile_path`` is Starlette's own template compiler — the one the router
#: uses — so a template matches here exactly when it would match there, including
#: ``{param}`` segments, and the pattern is anchored at both ends.
_COMPILED_ROUTES: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (method, compile_path(template)[0], template) for method, template in sorted(IDEMPOTENT_ROUTES)
)


#: The one header the middleware reads a key from. Lookup through
#: ``request.headers`` is case-insensitive — Starlette lower-cases both stored names and the lookup key —
#: so clients may send any casing.
IDEMPOTENCY_HEADER = "X-Idempotency-Key"

#: Reused verbatim rather than given a new name: payments, onboarding and ledger
#: already return this code for the same condition, and it is the documented one
#: in docs/api-conventions.md §6.
ERROR_MISSING_KEY = "MISSING_IDEMPOTENCY_KEY"

#: New. SCREAMING_SNAKE per docs/api-conventions.md §6, and deliberately distinct
#: from MISSING: "you sent nothing" and "you sent something unusable" are
#: different client bugs with different fixes.
ERROR_INVALID_KEY = "INVALID_IDEMPOTENCY_KEY"

#: 409. The same key is mid-flight on another request; the caller should retry
#: rather than treat this as a permanent failure.
ERROR_IN_PROGRESS = "IDEMPOTENT_REQUEST_IN_PROGRESS"

#: 409. The key reached a terminal state but carries no replayable response, so
#: the operation can be neither replayed nor safely re-run. Distinct from
#: IN_PROGRESS because retrying will never help — the caller needs a new key.
ERROR_ALREADY_USED = "IDEMPOTENCY_KEY_ALREADY_USED"

#: Marks a response served from the idempotency record rather than the handler.
REPLAY_HEADER = "X-Idempotent-Replay"

#: How long a registered key remains the owner of its operation.
#:
#: Nothing reads this yet — no reaper exists, and nothing ever writes EXPIRED —
#: but it is recorded so that when a reaper is built, the rows this middleware
#: created carry the expiry it needs to reclaim them.
#: 24h matches the TTL the payments module already uses for its own key table.
KEY_TTL = timedelta(hours=24)

#: Ceiling on the serialised envelope, below the DB's 64 KiB ck_response_cache_size.
#:
#: The margin is not decoration. That constraint measures
#: octet_length(response_cache::text) — Postgres's own rendering of the JSONB,
#: whose whitespace, key order and escaping all differ from json.dumps here. A
#: payload sized exactly at the limit locally could still be rejected by the
#: database, and a rejected write would turn a perfectly good handler response
#: into a 500.
MAX_CACHE_BYTES = 60_000


@dataclass(frozen=True)
class _Registration:
    """Plain values lifted out of the registration session before it closes.

    Deliberately not the ORM instance: that would be a detached object whose
    lifetime is tangled with a session this middleware has already committed and
    closed. Only these four values are needed downstream.
    """

    is_new: bool
    status: IdempotencyStatus | None
    response_cache: dict[str, Any] | None
    scope_id: str


def _idempotency_error(
    detail: str,
    error_code: str,
    reason: str,
    idempotency_key: str | None,
    status_code: int = 400,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "human_readable_message": detail,
            "detail": detail,
            "idempotency_key": idempotency_key,
            "correlation_id": structlog.contextvars.get_contextvars().get("correlation_id"),
            "timestamp": datetime.now(UTC).isoformat(),
            "error_context": {"reason": reason},
        },
    )


def _operation_type(method: str, route_template: str) -> str:
    """A stable, human-readable name for the operation the key belongs to.

    The endpoint's function name would read better, but reading it means walking
    the route table, which this middleware deliberately does not do: FastAPI's
    table shape is not stable across versions. ``"METHOD /template"`` is derived
    from data already in hand, is just as deterministic, and does not depend on
    an endpoint keeping its Python name.

    Truncated to the column width. Safe to truncate because this field is
    descriptive only; ``scope_id`` is deliberately *not* truncated, since it is
    half of the uniqueness key and a silent trim there could collapse two
    distinct scopes into one.
    """
    return f"{method} {route_template}"[:100]


async def _register_once(
    key: str, scope_id: str, operation_type: str, correlation_id: str | None
) -> _Registration:
    async with database.AsyncSessionLocal() as session:
        try:
            result = await register_key(
                session=session,
                key_value=key,
                key_type=IdempotencyKeyType.CUSTOMER_KEY,
                scope_id=scope_id,
                operation_type=operation_type,
                correlation_id=correlation_id,
                created_by=None,
                expires_at=datetime.now(UTC) + KEY_TTL,
            )

            record = result.record
            snapshot = _Registration(
                is_new=result.result is RegistrationResultType.NEW,
                status=record.status if record is not None else None,
                response_cache=record.response_cache if record is not None else None,
                scope_id=scope_id,
            )

            await session.commit()
            return snapshot
        except Exception:
            await session.rollback()
            raise


async def _register(
    key: str, scope_id: str, operation_type: str, correlation_id: str | None
) -> _Registration:
    try:
        return await _register_once(key, scope_id, operation_type, correlation_id)
    except NoResultFound:
        logger.warning("idempotency_registration_race_retry", scope_id=scope_id)
        return await _register_once(key, scope_id, operation_type, correlation_id)


def _rebuild_headers(original: Response, rebuilt: Response) -> list[tuple[bytes, bytes]]:
    """Carry the original headers over, preserving repeats.

    Copied from ``raw_headers`` rather than ``dict(response.headers)``, because a
    dict keeps one value per name and HTTP allows several. ``Set-Cookie`` is the
    case that bites — two cookies become one — but ``Vary``, ``Link`` and
    ``WWW-Authenticate`` repeat legitimately too.

    ``content-length`` is taken from the rebuilt response instead, since only it
    knows the buffered length; Starlette omits it entirely for statuses that must
    not carry one (204, 304), and this preserves that.
    """
    computed = [(k, v) for k, v in rebuilt.raw_headers if k.lower() == b"content-length"]
    preserved = [(k, v) for k, v in original.raw_headers if k.lower() != b"content-length"]
    return computed + preserved


async def _capture(response: Response) -> tuple[bytes | None, Response]:
    # Starlette types call_next as returning Response, but the object it actually
    # returns is the private _StreamingResponse, which carries body_iterator and
    # subclasses Response rather than StreamingResponse. There is no public type
    # that expresses "Response that streams", so the attribute is unreachable to
    # mypy even though it is always present here.
    chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]

    if not all(isinstance(chunk, bytes) for chunk in chunks):

        async def _reemit() -> Any:
            for chunk in chunks:
                yield chunk

        streamed = StreamingResponse(_reemit(), status_code=response.status_code)
        streamed.raw_headers = _rebuild_headers(response, streamed)
        return None, streamed

    body = b"".join(chunks)
    rebuilt = Response(content=body, status_code=response.status_code)
    rebuilt.raw_headers = _rebuild_headers(response, rebuilt)
    return body, rebuilt


def _envelope(response: Response, body: bytes | None) -> dict[str, Any] | None:
    if body is None:
        return None

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return None

    try:
        decoded = json.loads(body) if body else None
    except ValueError:
        return None

    envelope = {"status_code": response.status_code, "body": decoded}

    if len(json.dumps(envelope).encode()) > MAX_CACHE_BYTES:
        return None

    return envelope


async def _complete(
    key: str, scope_id: str, terminal: IdempotencyStatus, payload: dict[str, Any] | None
) -> None:
    try:
        async with database.AsyncSessionLocal() as session:
            try:
                await complete_key(
                    session=session,
                    key_value=key,
                    scope_id=scope_id,
                    terminal_status=terminal,
                    response_payload=payload,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.error(
            "idempotency_completion_failed",
            idempotency_key=key,
            scope_id=scope_id,
            terminal_status=terminal.value,
            error=str(exc),
        )


def _replay(cached: dict[str, Any]) -> Response | None:
    if not isinstance(cached, dict):
        return None

    status_code = cached.get("status_code")

    # `not isinstance(bool)` because bool subclasses int, so a cache holding
    # {"status_code": true} would otherwise pass and replay as status 1.
    # Unreachable through our own writer; this guards a hand-edited or
    # future-shaped row rather than trusting one.
    if not isinstance(status_code, int) or isinstance(status_code, bool) or "body" not in cached:
        return None

    # Only the boolean marker. The terminal state was also exposed here as
    # X-Idempotent-Replay-Status, which was dropped: it is inferable from the
    # replayed status code, and publishing the registry's internal enum
    # vocabulary would freeze it into the public contract.
    return JSONResponse(
        status_code=status_code,
        content=cached["body"],
        headers={REPLAY_HEADER: "true"},
    )


def resolve_idempotent_route(request: Request) -> str | None:
    """Return the route template if this request is idempotency-gated, else ``None``.

    The template cannot be read from ``request.scope["route"]``: the router is
    what puts ``"route"`` into the scope, and it only runs *inside* ``call_next``
    — at middleware time the key does not exist yet.

    So the request path is matched against the allowlist directly. The obvious
    alternative — walking ``request.scope["app"].routes`` and asking each route
    to match — was tried and rejected, because the shape of that table is not
    stable across FastAPI versions: 0.141.0 stopped flattening ``include_router``
    and now hides module routes behind a private ``_IncludedRouter`` whose
    ``path`` is ``None``. A gate built on that walk silently degrades to
    pass-through on upgrade, which is exactly the failure a gate must not have.
    Matching our own configured templates depends on nothing but the path.

    ``get_route_path`` rather than ``request.url.path`` so a mounted
    ``root_path`` is stripped the same way the router strips it.
    """
    if request.method not in IDEMPOTENT_METHODS:
        return None

    path = get_route_path(request.scope)

    for method, pattern, template in _COMPILED_ROUTES:
        if method == request.method and pattern.match(path):
            return template

    return None


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Enforce an idempotency key on an explicitly enabled set of routes.

    Registered between ``CorrelationIdMiddleware`` and ``CORSMiddleware``, so a
    correlation ID is already bound to the logging context by the time this runs
    (see ``app/main.py``).

    A gated request runs four steps in order: match the route, extract and
    validate the header, register the key and route duplicates, then bind the
    accepted key into the request's logging context.

    A registered key is completed from the response the handler produced, so a
    later request with the same key replays rather than re-executing. The replay
    carries status and body only, which is all the response_cache column can
    round-trip.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        route_template = resolve_idempotent_route(request)
        if route_template is None:
            return await call_next(request)

        raw_key = request.headers.get(IDEMPOTENCY_HEADER)

        # Strip before every other check. A trailing newline from a shell client
        # is not a malformed key, and the anchored UUID pattern would otherwise
        # reject it with a reason that sends the caller looking in the wrong
        # place. Stripping is lossless here: a UUID has no significant whitespace.
        key = (raw_key or "").strip()

        if not key:
            # Absent, empty and whitespace-only are one condition from the
            # caller's side — no usable key was supplied — and take one code.
            # header_present keeps the distinction where it is actually useful.
            logger.warning(
                "idempotency_key_missing",
                route_template=route_template,
                header_present=raw_key is not None,
            )
            return _idempotency_error(
                detail=f"{IDEMPOTENCY_HEADER} header is required for this operation",
                error_code=ERROR_MISSING_KEY,
                reason=ValidationReason.EMPTY_KEY.value,
                # Null rather than the blank string: no key was supplied, and
                # echoing "" would suggest one was and it was preserved.
                idempotency_key=None,
            )

        # The key grammar lives in the idempotency package, not here. The
        # middleware neither parses UUIDs nor measures lengths: it asks, and
        # reports what it is told, so one definition of a valid key serves
        # every caller that accepts one.
        validation = validate_customer_key(key)
        if not validation.is_valid:
            reason = (
                validation.reason.value
                if validation.reason is not None
                else ValidationReason.INVALID_FORMAT.value
            )
            logger.warning("idempotency_key_invalid", route_template=route_template, reason=reason)
            return _idempotency_error(
                detail=f"{IDEMPOTENCY_HEADER}: {validation.message}",
                error_code=ERROR_INVALID_KEY,
                reason=reason,
                # The stripped key, echoed so the caller can correlate the
                # rejection with what they sent. Matches what
                # aner_exception_handler already puts in this field for any
                # request carrying the header.
                idempotency_key=key,
            )

        scope_id = route_template
        operation_type = _operation_type(request.method, route_template)
        correlation_id = structlog.contextvars.get_contextvars().get("correlation_id")

        registration = await _register(key, scope_id, operation_type, correlation_id)

        if registration.is_new:
            # Before call_next: the downstream task copies the context at creation.
            # Not unbound afterwards — CorrelationIdMiddleware's clear_contextvars()
            # owns that, which is why this must stay inside it.
            #
            # This is the propagation point, not merely a logging one: everything
            # the request goes on to do reads the key back through
            # current_idempotency_key() and derives its own keys from it.
            bind_idempotency_key(key)

            logger.info(
                "idempotency_key_registered",
                route_template=route_template,
                idempotency_key=key,
                operation_type=operation_type,
            )

            try:
                response = await call_next(request)
            except Exception:
                # Only genuinely unhandled errors arrive here. AnerBaseException
                # and friends are rendered by ExceptionMiddleware, which is built
                # *inside* this one, so they come back as ordinary 4xx responses
                # and take the status branch below.
                #
                # Exception, not BaseException: attempting a database write while
                # a CancelledError unwinds is unreliable and would mask the
                # cancellation. Re-raised unchanged so ServerErrorMiddleware still
                # produces the 500 and its logging.
                await _complete(key, scope_id, IdempotencyStatus.FAILED, None)
                raise

            body, response = await _capture(response)
            terminal = (
                IdempotencyStatus.COMPLETED
                if response.status_code < 400
                else IdempotencyStatus.FAILED
            )
            payload = _envelope(response, body)

            if payload is None:
                logger.warning(
                    "idempotency_response_not_cacheable",
                    idempotency_key=key,
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type"),
                )

            await _complete(key, scope_id, terminal, payload)
            return response

        status = registration.status
        logger.info(
            "idempotency_key_duplicate",
            route_template=route_template,
            idempotency_key=key,
            existing_status=status.value if status is not None else None,
        )

        if status in (IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED):
            replayed = _replay(registration.response_cache or {})
            if replayed is not None:
                return replayed

            # Terminal, but nothing replayable was stored. Re-running the handler
            # is not an option — that is the duplicate execution the key exists to
            # prevent — so the request is refused and the caller needs a new key.
            logger.warning(
                "idempotency_replay_unavailable",
                route_template=route_template,
                idempotency_key=key,
                existing_status=status.value,
            )
            return _idempotency_error(
                detail=(
                    f"{IDEMPOTENCY_HEADER} has already been used for this operation "
                    "and the original response is no longer available for replay"
                ),
                error_code=ERROR_ALREADY_USED,
                reason=status.value,
                idempotency_key=key,
                status_code=409,
            )

        # ACTIVE, and defensively anything else. EXPIRED is now reclaimed by the
        # registration service and treated as NEW, so it will not reach this point.
        # Routing on "not replayable" means a state added to the enum later
        # fails closed instead of falling through.
        return _idempotency_error(
            detail=(
                f"A request with this {IDEMPOTENCY_HEADER} is already in progress; "
                "retry once it completes"
            ),
            error_code=ERROR_IN_PROGRESS,
            reason=status.value if status is not None else "UNKNOWN",
            idempotency_key=key,
            status_code=409,
        )
