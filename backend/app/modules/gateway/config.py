"""Gateway configuration: supported API versions and correlation-ID validation.

Kept as simple module-level constants rather than environment-driven settings —
this is the S1T1 skeleton and nothing yet requires a per-environment override.
Both are read through functions rather than imported as bare names, so a later
story can change the source (e.g. a feature-flagged rollout of v2) without
touching every call site — the version-routing logic itself never branches on
a hardcoded string.
"""
import re

#: Version prefixes the gateway accepts and passes through to that version's
#: own router. Adding "v2" here — plus wiring its router — is the entire
#: change needed to open a new version; nothing else in this module branches
#: on a hardcoded list of versions.
_SUPPORTED_API_VERSIONS: frozenset[str] = frozenset({"v1"})

#: Matches a version-shaped path segment ("v1", "v12") whether supported or
#: not. Used to distinguish "a deliberate, unsupported version" (normalized
#: 404) from "a path that was never version-shaped at all" (ordinary 404,
#: identical to today's behavior for any other unmatched path).
VERSION_SEGMENT_PATTERN: re.Pattern[str] = re.compile(r"^v\d+$")

#: X-Correlation-Id constraints for external callers. Conservative on purpose:
#: this value is persisted (gateway.api_request_logs), placed in a response
#: header, and bound into log context, so it is validated as strictly as any
#: caller-controlled string that reaches all three ever should be.
CORRELATION_ID_HEADER = "X-Correlation-Id"
CORRELATION_ID_MAX_LENGTH = 128
CORRELATION_ID_PATTERN: re.Pattern[str] = re.compile(
    rf"^[A-Za-z0-9._-]{{1,{CORRELATION_ID_MAX_LENGTH}}}$"
)


def supported_api_versions() -> frozenset[str]:
    return _SUPPORTED_API_VERSIONS


def is_supported_version(version_segment: str) -> bool:
    return version_segment in _SUPPORTED_API_VERSIONS


def is_valid_correlation_id(value: str) -> bool:
    """Reasonable format and length — alphanumeric plus '.', '_', '-', 1-128 chars.

    Deliberately not a UUID-only check: callers are free to send their own
    trace ID format (many API gateways accept this), so long as it cannot
    carry header-injection characters, blow out the log/DB column, or contain
    whitespace that would make it ambiguous in a log line.
    """
    return bool(CORRELATION_ID_PATTERN.match(value))
