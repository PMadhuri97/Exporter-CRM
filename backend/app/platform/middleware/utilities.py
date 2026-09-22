from typing import Any

from app.platform.middleware.config import IDEMPOTENT_ROUTES
from app.platform.middleware.services import (
    ERROR_ALREADY_USED,
    ERROR_IN_PROGRESS,
    ERROR_INVALID_KEY,
    ERROR_MISSING_KEY,
    IDEMPOTENCY_HEADER,
    REPLAY_HEADER,
)

#: Component name for the 400 body, so generated clients get a named type rather
#: than an inline anonymous object repeated per route.
ERROR_SCHEMA_NAME = "IdempotencyErrorResponse"

_ERROR_SCHEMA_REF = f"#/components/schemas/{ERROR_SCHEMA_NAME}"


def _header_parameter() -> dict[str, Any]:
    """The required idempotency header, as an OpenAPI parameter object.

    ``format: uuid`` is the closest OpenAPI gets — it cannot express "version 4
    specifically", which is what the middleware enforces, so the description
    carries that.
    """
    return {
        "name": IDEMPOTENCY_HEADER,
        "in": "header",
        "required": True,
        "schema": {"type": "string", "format": "uuid", "maxLength": 64},
        "description": (
            "Client-generated idempotency key. Must be a canonical UUID **v4** "
            "(any case), at most 64 characters. Enforced by the platform "
            "idempotency middleware before the request reaches this endpoint, so "
            "a missing or malformed key returns 400 rather than the endpoint's "
            "own errors — including in preference to 401/403, since the check "
            "runs ahead of authentication."
        ),
    }


def _error_schema() -> dict[str, Any]:
    """The 400 body, mirroring what ``_idempotency_error`` actually emits.

    Kept structurally identical to the platform error shape rendered by
    ``aner_exception_handler`` so clients parse one shape across the API.
    """
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    return {
        "title": ERROR_SCHEMA_NAME,
        "type": "object",
        "required": [
            "error_code",
            "human_readable_message",
            "detail",
            "correlation_id",
            "timestamp",
        ],
        "properties": {
            "error_code": {
                "type": "string",
                "enum": [ERROR_MISSING_KEY, ERROR_INVALID_KEY],
                "description": (
                    f"`{ERROR_MISSING_KEY}` when no key was supplied; "
                    f"`{ERROR_INVALID_KEY}` when one was supplied but is not a "
                    "valid UUID v4 or exceeds the length limit."
                ),
            },
            "human_readable_message": {"type": "string"},
            "detail": {"type": "string"},
            "idempotency_key": {
                **nullable_string,
                "description": (
                    "The rejected key, whitespace-stripped, echoed back so the "
                    "caller can correlate. Null when no key was supplied."
                ),
            },
            "correlation_id": nullable_string,
            "timestamp": {"type": "string", "format": "date-time"},
            "error_context": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Machine-readable reason the key was rejected, from "
                            "the key-validation vocabulary."
                        ),
                    }
                },
            },
        },
    }


def _error_response() -> dict[str, Any]:
    return {
        "description": f"Missing or malformed {IDEMPOTENCY_HEADER}",
        "content": {"application/json": {"schema": {"$ref": _ERROR_SCHEMA_REF}}},
    }


#: What the middleware's own 409 means, in the two forms the description needs.
#:
#: Both branches of ``_merge_conflict`` name the codes: a client cannot act on
#: "409 Conflict" alone, and which branch ran is an accident of whether the route
#: happened to declare a 409 of its own.
_CONFLICT_CODES = (
    f"`{ERROR_IN_PROGRESS}` when a request with the same {IDEMPOTENCY_HEADER} is "
    f"still in flight, or `{ERROR_ALREADY_USED}` when the key reached a terminal "
    f"state whose response cannot be replayed. Those carry "
    f"`{ERROR_SCHEMA_NAME}`."
)

#: Sentence appended to an operation's existing 409, which the middleware can now
#: also produce for its own reasons.
_CONFLICT_NOTE = (
    f"May also be returned by the platform idempotency middleware: {_CONFLICT_CODES}"
)


def _replay_header() -> dict[str, Any]:
    return {
        REPLAY_HEADER: {
            "description": (
                "Present and `true` when this response was served from the "
                "idempotency record rather than by executing the operation again. "
                "A replay reproduces the original status code, so this header — "
                "not the status — is what distinguishes a replay from a fresh "
                "execution."
            ),
            "schema": {"type": "string", "enum": ["true"]},
        }
    }


def _merge_conflict(operation: dict[str, Any]) -> None:
    """Make the operation's 409 describe the middleware's conflicts too.

    The middleware returns 409 for its own reasons, with its own body. Routes
    typically already declare a 409 for a business conflict, so the status code
    alone is not enough to tell a client what shape to expect.

    An existing 409 is extended rather than replaced: its description gains a
    sentence and, if it declared no schema — as
    ``POST /settlement/execute`` does — the idempotency one is attached. A 409
    that already documents a body is left alone apart from the description, since
    overwriting another endpoint's declared contract would be worse than an
    incomplete one.
    """
    responses = operation.setdefault("responses", {})
    existing = responses.get("409")

    if existing is None:
        responses["409"] = {
            "description": (
                f"Idempotency conflict on {IDEMPOTENCY_HEADER}: {_CONFLICT_CODES}"
            ),
            "content": {"application/json": {"schema": {"$ref": _ERROR_SCHEMA_REF}}},
        }
        return

    description = existing.get("description", "").rstrip()
    if _CONFLICT_NOTE not in description:
        existing["description"] = f"{description} {_CONFLICT_NOTE}".strip()

    existing.setdefault(
        "content", {"application/json": {"schema": {"$ref": _ERROR_SCHEMA_REF}}}
    )


def document_idempotent_routes(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the idempotency header and 400 response to every allowlisted operation.

    Mutates and returns ``schema``. Safe to apply twice: the header is matched by
    name before being added, and the response is keyed by status code, so a second
    application is a no-op rather than a duplicate.

    An allowlist entry with no matching operation in the document is skipped
    silently — a route may legitimately be hidden with ``include_in_schema=False``,
    and a missing route is caught by the wiring tests, not here.
    """
    documented = False

    for method, template in sorted(IDEMPOTENT_ROUTES):
        operation = schema.get("paths", {}).get(template, {}).get(method.lower())
        if operation is None:
            continue

        parameters = operation.setdefault("parameters", [])
        if not any(
            p.get("name") == IDEMPOTENCY_HEADER and p.get("in") == "header"
            for p in parameters
        ):
            parameters.append(_header_parameter())

        operation.setdefault("responses", {}).setdefault("400", _error_response())
        _merge_conflict(operation)

        # A replay reproduces the handler's original status, so any success the
        # operation declares can arrive as one. Marked on those rather than on
        # every response: the middleware's own 400 and 409 are never replays.
        for status_code, response in operation["responses"].items():
            if status_code.startswith("2"):
                response.setdefault("headers", {}).update(_replay_header())

        documented = True

    # Only register the component if something references it, so an empty
    # allowlist does not leave an orphan schema in the document.
    if documented:
        schema.setdefault("components", {}).setdefault("schemas", {}).setdefault(
            ERROR_SCHEMA_NAME, _error_schema()
        )

    return schema
