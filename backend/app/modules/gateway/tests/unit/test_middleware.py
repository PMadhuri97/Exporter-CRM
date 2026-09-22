from starlette.requests import Request

from app.modules.gateway.application.middleware import (
    owns_path,
    resolve_correlation_id,
)
from app.modules.gateway.config import CORRELATION_ID_HEADER


def _request(path: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {"type": "http", "method": "GET", "path": path, "headers": raw_headers}
    return Request(scope)


# ── owns_path ───────────────────────────────────────────────────────────────

def test_owns_health():
    assert owns_path("/health")


def test_owns_v1_paths():
    assert owns_path("/v1")
    assert owns_path("/v1/anything")


def test_owns_unsupported_version_paths_too():
    """Rejected requests still get correlation IDs and an audit log row."""
    assert owns_path("/v2/anything")


def test_does_not_own_internal_api_paths():
    assert not owns_path("/api/v1/health")
    assert not owns_path("/api/v1/payments")


def test_does_not_own_unrelated_root_paths():
    assert not owns_path("/metrics")
    assert not owns_path("/docs")
    assert not owns_path("/")


def test_does_not_own_paths_that_merely_start_with_v():
    assert not owns_path("/vendors")


# ── resolve_correlation_id ────────────────────────────────────────────────────

def test_resolve_generates_id_when_absent():
    cid = resolve_correlation_id(_request("/health"))
    assert cid


def test_resolve_propagates_valid_supplied_id_unchanged():
    cid = resolve_correlation_id(_request("/health", {CORRELATION_ID_HEADER: "abc-123"}))
    assert cid == "abc-123"


def test_resolve_replaces_invalid_supplied_id():
    supplied = "has a space"
    cid = resolve_correlation_id(_request("/health", {CORRELATION_ID_HEADER: supplied}))
    assert cid != supplied
    assert cid  # still non-empty — a usable ID is always returned
