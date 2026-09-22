"""The accepted idempotency key, as request-scoped context downstream code reads.

The middleware validates and registers a caller's key before the handler runs and
binds it here. Everything the request goes on to do — a row it writes, a workflow
it starts, a call it makes to an external rail — derives its own key from this
one. That is what makes a retry safe end to end: the caller resends the same key,
every derived key comes out the same, and each downstream side dedupes on its own
terms instead of acting twice.

**Why contextvars.** The key has to reach code several layers below the handler
without every intervening signature growing a parameter, and it has to survive the
tasks an async handler spawns. ``structlog.contextvars`` is copied into a task at
creation and is already where the correlation ID lives, so the two travel together
and cannot drift apart.

**Why an accessor and not ``get_contextvars()``.** The field name is then written
once rather than at every read site, and callers reaching for request context are
not reaching into the logging API to get it. The store is shared with logging; the
meaning of this field is not.

**Lifetime.** ``CorrelationIdMiddleware`` clears the contextvars at the start of
every request, so a key never survives into the next one. Outside a gated request
— an unlisted route, a Temporal worker, a scheduled job — there is no key and
``current_idempotency_key()`` returns ``None``. That is a normal state and not an
error: a caller that requires one must say so itself.
"""
from __future__ import annotations

import structlog.contextvars

#: The contextvar name the accepted key is bound under. Shared with the logging
#: context deliberately: a log line emitted anywhere inside a gated request should
#: carry the key without the emitting code knowing it exists.
IDEMPOTENCY_KEY_FIELD = "idempotency_key"


def bind_idempotency_key(key: str) -> None:
    """Publish ``key`` as the request's idempotency context.

    Called once, by the middleware, after the key has been validated and
    registered — never with a key that was rejected, so anything reading it back
    can treat it as usable without revalidating.
    """
    structlog.contextvars.bind_contextvars(**{IDEMPOTENCY_KEY_FIELD: key})


def current_idempotency_key() -> str | None:
    """The accepted key for the request in flight, or ``None`` outside one.

    ``None`` means no gated request is in scope. Callers that cannot proceed
    without a key should raise rather than inventing one: a generated substitute
    would be different on every retry, which is precisely the property the key
    exists to remove.
    """
    raw = structlog.contextvars.get_contextvars().get(IDEMPOTENCY_KEY_FIELD)
    return str(raw) if raw else None
