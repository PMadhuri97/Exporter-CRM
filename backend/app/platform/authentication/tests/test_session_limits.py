"""Sessions end after inactivity and after a maximum length, on the server.

A refresh token lives one inactivity timeout and each rotation renews only that
window; the session's start, carried through every rotation, bounds it to
``SESSION_MAX_HOURS``. Time is moved by rewriting the token's row, the way an idle
browser or a long day would leave it.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest
from httpx import AsyncClient

from app.platform.authentication.services import SERVER_IDLE_GRACE
from app.platform.configuration.config import get_settings, settings

pytestmark = pytest.mark.asyncio


async def _signed_in(client: AsyncClient) -> dict:
    email = f"session-{uuid.uuid4().hex[:10]}@aner-test.com"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password1", "full_name": "Session Test"},
    )
    assert registered.status_code == 201, registered.text
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password1"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _row(raw_refresh: str) -> tuple[datetime, datetime]:
    """(expires_at, session_started_at) of a refresh token."""
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT expires_at, session_started_at FROM auth.refresh_tokens WHERE token_hash = %s",
            (hashlib.sha256(raw_refresh.encode()).hexdigest(),),
        )
        return cur.fetchone()


def _age(raw_refresh: str, *, expires_at: datetime, started_at: datetime | None = None) -> None:
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE auth.refresh_tokens SET expires_at = %s,"
            " session_started_at = COALESCE(%s, session_started_at) WHERE token_hash = %s",
            (expires_at, started_at, hashlib.sha256(raw_refresh.encode()).hexdigest()),
        )


async def _refresh(client: AsyncClient, raw_refresh: str):
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})


async def test_a_token_lives_one_inactivity_timeout_and_says_so(client: AsyncClient):
    tokens = await _signed_in(client)
    idle = settings.session_idle_timeout_minutes

    expires_at, started_at = _row(tokens["refresh_token"])

    assert tokens["session_idle_timeout"] == idle * 60
    assert tokens["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    # The timeout people see, plus the server's grace for a last-second "Stay signed in".
    assert abs((expires_at - started_at) - (timedelta(minutes=idle) + SERVER_IDLE_GRACE)) < (
        timedelta(seconds=5)
    )


async def test_a_session_left_idle_past_the_timeout_is_refused(client: AsyncClient):
    tokens = await _signed_in(client)
    _age(tokens["refresh_token"], expires_at=datetime.now(tz=UTC) - timedelta(seconds=1))

    resp = await _refresh(client, tokens["refresh_token"])

    assert resp.status_code == 401, resp.text
    assert "inactivity" in resp.json()["detail"]


async def test_a_refresh_renews_the_window_but_keeps_the_sign_in_time(client: AsyncClient):
    tokens = await _signed_in(client)
    _, started_at = _row(tokens["refresh_token"])

    renewed = await _refresh(client, tokens["refresh_token"])

    assert renewed.status_code == 200, renewed.text
    expires_at, carried = _row(renewed.json()["refresh_token"])
    assert carried == started_at
    assert expires_at > datetime.now(tz=UTC) + timedelta(
        minutes=settings.session_idle_timeout_minutes - 1
    )


async def test_a_session_ends_at_its_maximum_length_however_active(client: AsyncClient):
    tokens = await _signed_in(client)
    long_ago = datetime.now(tz=UTC) - timedelta(hours=settings.SESSION_MAX_HOURS, minutes=1)
    # Active a moment ago, so only the maximum length can be what ends it.
    _age(
        tokens["refresh_token"],
        expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
        started_at=long_ago,
    )

    resp = await _refresh(client, tokens["refresh_token"])

    assert resp.status_code == 401, resp.text
    assert "maximum length" in resp.json()["detail"]


async def test_a_renewed_token_never_outlives_the_maximum_length(client: AsyncClient):
    """A minute before the maximum, a refresh gets that minute, not a full window —
    shorter than any inactivity window plus its grace, whatever the timeout is set to."""
    tokens = await _signed_in(client)
    started = datetime.now(tz=UTC) - timedelta(hours=settings.SESSION_MAX_HOURS, minutes=-1)
    _age(
        tokens["refresh_token"],
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        started_at=started,
    )

    renewed = await _refresh(client, tokens["refresh_token"])

    assert renewed.status_code == 200, renewed.text
    expires_at, _ = _row(renewed.json()["refresh_token"])
    assert abs(expires_at - (started + timedelta(hours=settings.SESSION_MAX_HOURS))) < timedelta(
        seconds=5
    )


def test_the_timeout_follows_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "SESSION_IDLE_TIMEOUT_MINUTES", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert settings.session_idle_timeout_minutes == 30
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    assert settings.session_idle_timeout_minutes == 60
    monkeypatch.setattr(settings, "SESSION_IDLE_TIMEOUT_MINUTES", 15)
    assert settings.session_idle_timeout_minutes == 15
