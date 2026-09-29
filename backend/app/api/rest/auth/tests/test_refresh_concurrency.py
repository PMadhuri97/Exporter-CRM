"""Two exchanges of one refresh token: exactly one succeeds. And a refresh whose
caller has gone changes nothing.

`POST /auth/refresh` rotates the token — it revokes the one presented and issues a
successor. Two browser tabs, or a page reloaded mid-refresh, can present the same
token at once. The route reads the token's row `FOR UPDATE`, so the second exchange
waits for the first to commit and is then refused, instead of both reading the row
unrevoked and both being handed a new token.

The race is made certain rather than lucky: revoking is slowed down, so without the
lock both requests would have read the row before either wrote it.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import AsyncClient

from app.main import app
from app.platform.authentication.adapters.repository import RefreshTokenRepository
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import PASSWORD, create_user_direct

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/auth"


async def test_two_concurrent_refreshes_with_one_token_give_exactly_one_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    email = f"refresh-race-{uuid.uuid4().hex[:8]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS)
    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    revoke = RefreshTokenRepository.revoke

    async def slow_revoke(self, token):
        await asyncio.sleep(0.3)
        return await revoke(self, token)

    monkeypatch.setattr(RefreshTokenRepository, "revoke", slow_revoke)

    first, second = await asyncio.gather(
        client.post(f"{BASE}/refresh", json={"refresh_token": refresh_token}),
        client.post(f"{BASE}/refresh", json={"refresh_token": refresh_token}),
    )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 401], (first.text, second.text)

    # The winner's successor works; the token both presented does not.
    winner = first if first.status_code == 200 else second
    again = await client.post(
        f"{BASE}/refresh", json={"refresh_token": winner.json()["refresh_token"]}
    )
    assert again.status_code == 200, again.text
    stale = await client.post(f"{BASE}/refresh", json={"refresh_token": refresh_token})
    assert stale.status_code == 401


async def test_a_refresh_whose_caller_has_gone_rotates_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """A page reloaded while its refresh is out never receives the new token. Had the
    rotation been committed, the token the page still holds would be revoked and its
    next load signed out. So the route checks the connection before it commits, and a
    caller that has gone changes nothing.

    The connection is dropped at a known moment — once the successor has been written
    but before the commit — by an ASGI `receive` that reports the disconnect only then.
    """
    email = f"refresh-gone-{uuid.uuid4().hex[:8]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS)
    login = await client.post(f"{BASE}/login", json={"email": email, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    gone = asyncio.Event()
    create = RefreshTokenRepository.create

    async def create_then_drop_the_connection(self, token):
        created = await create(self, token)
        gone.set()
        return created

    monkeypatch.setattr(RefreshTokenRepository, "create", create_then_drop_the_connection)

    body = json.dumps({"refresh_token": refresh_token}).encode()
    messages = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if messages:
            return messages.pop(0)
        await gone.wait()
        return {"type": "http.disconnect"}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"{BASE}/refresh",
        "raw_path": f"{BASE}/refresh".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
    }
    await app(scope, receive, send)

    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert starts and starts[0]["status"] == 499, sent
    monkeypatch.undo()

    # The token the page still holds was never revoked: its next load signs in.
    again = await client.post(f"{BASE}/refresh", json={"refresh_token": refresh_token})
    assert again.status_code == 200, again.text
