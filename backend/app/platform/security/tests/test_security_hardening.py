"""The penetration-test findings of October 2026, each pinned by a test.

One test (or a few) per fix, named for what an attacker tried and what now happens:
a forgeable JWT key, sign-in brute force, access tokens outliving logout, CORS
reflection, missing browser headers, an open /metrics, open sign-up, unchecked upload
content, oversized bodies, a 500 on a malformed idempotency key, and an unsanitised
correlation ID.
"""

from __future__ import annotations

import io
import random
import string
import uuid
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.modules.onboarding.application.storage_service import content_matches_type
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import auth_header, create_user_direct, user_with_role
from app.platform.configuration.config import Settings, settings
from app.platform.middleware.request_limits import RequestSizeLimitMiddleware
from app.platform.security.startup_checks import (
    DEFAULT_JWT_SECRET_KEY,
    InsecureConfigurationError,
    enforce_security_settings,
)

AUTH = "/api/v1/auth"
PASSWORD = "Password1"
STRONG_KEY = "k" * 48


# ── P1: the JWT signing key ──────────────────────────────────────────────────


@pytest.mark.parametrize("key", [DEFAULT_JWT_SECRET_KEY, "", "short-but-not-default"])
def test_weak_jwt_key_stops_start_up_outside_local_and_test(key: str):
    configured = Settings(ENVIRONMENT="production", JWT_SECRET_KEY=key)
    with pytest.raises(InsecureConfigurationError, match="JWT_SECRET_KEY"):
        enforce_security_settings(configured)


def test_development_is_not_exempt_from_the_jwt_key_check():
    # `development` is the default ENVIRONMENT; a server nobody renamed must not
    # quietly run with the public key.
    configured = Settings(ENVIRONMENT="development", JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY)
    with pytest.raises(InsecureConfigurationError):
        enforce_security_settings(configured)


def test_local_and_test_may_use_the_default_key_and_a_strong_key_starts_anywhere():
    enforce_security_settings(Settings(ENVIRONMENT="local", JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY))
    enforce_security_settings(Settings(ENVIRONMENT="production", JWT_SECRET_KEY=STRONG_KEY))


# ── P5: sign-in brute force ──────────────────────────────────────────────────


async def test_repeated_wrong_passwords_lock_the_account(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 3)
    email = f"lockout-{uuid.uuid4().hex[:10]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS, password=PASSWORD)

    for _ in range(3):
        wrong = await client.post(f"{AUTH}/login", json={"email": email, "password": "Wrong1234"})
        assert wrong.status_code == 401, wrong.text

    # Locked: even the right password is refused, without being checked.
    locked = await client.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 429, locked.text
    assert locked.json()["error_code"] == "LOGIN_LOCKED"


async def test_a_correct_password_resets_the_failure_count(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 3)
    email = f"reset-{uuid.uuid4().hex[:10]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS, password=PASSWORD)

    for _ in range(2):
        await client.post(f"{AUTH}/login", json={"email": email, "password": "Wrong1234"})
    ok = await client.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})
    assert ok.status_code == 200, ok.text
    for _ in range(2):
        await client.post(f"{AUTH}/login", json={"email": email, "password": "Wrong1234"})
    still_ok = await client.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})
    assert still_ok.status_code == 200, still_ok.text


# ── P11: access tokens end with their session ────────────────────────────────


async def test_logout_ends_the_access_token_at_once(client: AsyncClient):
    email = f"logout-{uuid.uuid4().hex[:10]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS, password=PASSWORD)
    tokens = (await client.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})).json()
    headers = auth_header(tokens["access_token"])

    assert (await client.get(f"{AUTH}/me", headers=headers)).status_code == 200
    out = await client.post(
        f"{AUTH}/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert out.status_code == 204, out.text

    after = await client.get(f"{AUTH}/me", headers=headers)
    assert after.status_code == 401, after.text


async def test_a_refreshed_session_keeps_working(client: AsyncClient):
    email = f"refresh-{uuid.uuid4().hex[:10]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS, password=PASSWORD)
    first = (await client.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})).json()
    second = await client.post(f"{AUTH}/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200, second.text

    # Both the new token and the one issued before the rotation belong to a live session.
    for token in (second.json()["access_token"], first["access_token"]):
        assert (await client.get(f"{AUTH}/me", headers=auth_header(token))).status_code == 200


async def test_a_token_without_a_session_is_refused(client: AsyncClient):
    import jwt

    user_id, _ = await user_with_role(client, UserRole.OPERATIONS)
    legacy = jwt.encode(
        {"sub": user_id, "type": "access", "exp": 9999999999},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert (await client.get(f"{AUTH}/me", headers=auth_header(legacy))).status_code == 401


# ── P8: self-service sign-up ─────────────────────────────────────────────────


def test_self_service_signup_is_off_by_default():
    assert Settings.model_fields["SELF_SERVICE_SIGNUP_ENABLED"].default is False


# ── P3, P6, P9: CORS, docs, headers ──────────────────────────────────────────


async def test_cors_does_not_reflect_an_arbitrary_origin(client: AsyncClient):
    evil = {"Origin": "https://evil.example.com"}
    simple = await client.get("/api/v1/health", headers=evil)
    assert "access-control-allow-origin" not in simple.headers
    assert "access-control-allow-credentials" not in simple.headers

    preflight = await client.options(
        f"{AUTH}/me",
        headers={**evil, "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_cors_origins_never_include_a_wildcard():
    configured = Settings(CORS_ALLOWED_ORIGINS="*, https://crm.example.com/")
    assert configured.cors_allowed_origins == ["https://crm.example.com"]


def test_api_docs_default_to_local_and_test_only():
    assert Settings(ENVIRONMENT="production").api_docs_enabled is False
    assert Settings(ENVIRONMENT="development").api_docs_enabled is False
    assert Settings(ENVIRONMENT="test").api_docs_enabled is True
    assert Settings(ENVIRONMENT="production", API_DOCS_ENABLED=True).api_docs_enabled is True


async def test_api_responses_carry_security_headers(client: AsyncClient):
    resp = await client.get("/api/v1/health", headers={"X-Forwarded-Proto": "https"})
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["strict-transport-security"].startswith("max-age=")


async def test_hsts_is_not_sent_over_plain_http(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert "strict-transport-security" not in resp.headers


# ── P7: /metrics ─────────────────────────────────────────────────────────────


async def test_metrics_are_hidden_outside_local_and_test_without_a_token(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "METRICS_BEARER_TOKEN", "")
    assert (await client.get("/metrics")).status_code == 404


async def test_metrics_need_the_configured_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "METRICS_BEARER_TOKEN", "scrape-secret")
    assert (await client.get("/metrics")).status_code == 404
    wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 404
    right = await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert right.status_code == 200


# ── P4: upload content must match its declared type ──────────────────────────


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"%PDF-1.7\n...", "application/pdf"),
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"II*\x00rest", "image/tiff"),
        (b"name,amount\nAcme,10\n", "text/csv"),
        (b"\xef\xbb\xbfplain notes", "text/plain"),
        (_zip({"[Content_Types].xml": b"x", "word/document.xml": b"x"}),
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (_zip({"[Content_Types].xml": b"x", "xl/workbook.xml": b"x"}),
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "application/msword"),
        (_zip({"a.txt": b"x"}), "application/zip"),
    ],
)
def test_genuine_files_match_their_type(content: bytes, content_type: str):
    assert content_matches_type(content, content_type)


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        # The pen test's payload: a web page declared as a PDF.
        (b"<html><script>alert(1)</script></html>", "application/pdf"),
        (b"<!DOCTYPE html><script>alert(1)</script>", "text/plain"),
        (b"  <svg onload=alert(1)>", "text/csv"),
        (b"MZ\x90\x00 executable", "image/png"),
        (b"text\x00with nul", "text/plain"),
        # Any ZIP is not a Word document: it must have the parts Word requires.
        (_zip({"payload.html": b"x"}),
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (b"not a zip", "application/zip"),
    ],
)
def test_disguised_files_are_refused(content: bytes, content_type: str):
    assert not content_matches_type(content, content_type)


# ── P13: request body ceiling ────────────────────────────────────────────────


async def test_an_oversized_body_is_refused_before_it_is_read():
    async def echo(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    app = RequestSizeLimitMiddleware(
        Starlette(routes=[Route("/", echo, methods=["POST"])]), max_bytes=10
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as small:
        assert (await small.post("/", content=b"x" * 10)).status_code == 200
        assert (await small.post("/", content=b"x" * 11)).status_code == 413


# ── P12: a malformed legacy Idempotency-Key ──────────────────────────────────


def _pan() -> str:
    letters = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
    return f"{letters}{random.randint(0, 9999):04d}{random.choice(string.ascii_uppercase)}"


async def test_malformed_idempotency_key_is_a_400_not_a_500(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        "/api/v1/onboarding/exporters",
        json={"source": "SALES", "name": f"Key Co {uuid.uuid4().hex[:8]}", "country": "IN",
              "pan": _pan(), "industry": "Textiles"},
        headers={**auth_header(token), "Idempotency-Key": "not-a-uuid"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "INVALID_IDEMPOTENCY_KEY"


# ── P14: correlation IDs ─────────────────────────────────────────────────────


async def test_a_markup_correlation_id_is_replaced_not_echoed(client: AsyncClient):
    resp = await client.get(
        "/api/v1/health", headers={"X-Correlation-Id": "<script>alert(1)</script>"}
    )
    echoed = resp.headers["x-correlation-id"]
    assert "<" not in echoed
    uuid.UUID(echoed)  # a fresh one was generated


async def test_a_well_formed_correlation_id_is_kept(client: AsyncClient):
    cid = f"svc:req-{uuid.uuid4().hex}"
    resp = await client.get("/api/v1/health", headers={"X-Correlation-Id": cid})
    assert resp.headers["x-correlation-id"] == cid
