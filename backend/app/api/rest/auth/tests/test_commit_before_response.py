"""A write is committed before its response leaves the server.

`get_db` commits in its teardown, which FastAPI runs after the response has been sent.
A route that relied on it answered 201 while its row was still uncommitted, and a
client acting on the answer at once — signing in straight after signing up, reloading
the user list after creating an account — missed the write (measured against a live
server: 9 of 15 immediate sign-ins refused). The auth routes now commit before they
return.

An in-process client waits for the whole request, teardown included, so asking again
afterwards cannot see the race. These tests look at the moment it matters instead:
when the app starts sending the response, a separate connection must already see the
row. `get_db` is replaced for that one request by a copy whose teardown commit is
half a second late, so a route that still relied on it would fail every time rather
than only when the timing is unlucky.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import (
    PASSWORD,
    auth_header,
    create_user_direct,
    token_with_role,
)
from app.platform.configuration.config import get_settings
from app.platform.database import services as database
from app.platform.database.services import get_db

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/auth"


def _count(sql: str, *args: object) -> int:
    """Read through a connection of its own, so only committed rows are seen."""
    dsn = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()[0]
    finally:
        conn.close()


def _user_committed(email: str) -> Callable[[], bool]:
    return lambda: _count("SELECT count(*) FROM auth.users WHERE email = %s", email) == 1


async def _get_db_with_a_late_commit() -> AsyncGenerator:
    """`get_db`, with its teardown commit deliberately late."""
    async with database.AsyncSessionLocal() as session:
        try:
            yield session
            await asyncio.sleep(0.5)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _post_watching_the_response(
    path: str, *, json: dict, committed: Callable[[], bool], headers: dict | None = None
):
    """POST ``path`` and report whether ``committed()`` held when the response began."""
    seen: dict[str, bool] = {}

    async def watched(scope, receive, send):
        async def spy(message):
            if message["type"] == "http.response.start" and "committed" not in seen:
                seen["committed"] = committed()
            await send(message)

        await app(scope, receive, spy)

    app.dependency_overrides[get_db] = _get_db_with_a_late_commit
    try:
        async with AsyncClient(transport=ASGITransport(app=watched), base_url="http://test") as c:
            response = await c.post(path, json=json, headers=headers or {})
    finally:
        app.dependency_overrides.pop(get_db, None)
    return response, seen["committed"]


async def test_a_sign_up_is_committed_before_the_response():
    email = f"signup-{uuid.uuid4().hex[:8]}@aner-test.com"
    response, committed = await _post_watching_the_response(
        f"{BASE}/register",
        json={"email": email, "password": PASSWORD},
        committed=_user_committed(email),
    )
    assert response.status_code == 201, response.text
    assert committed, "the account was not committed when the 201 was sent"


async def test_an_account_created_in_settings_is_committed_before_the_response(
    client: AsyncClient,
):
    admin = await token_with_role(client, UserRole.ADMIN)
    email = f"created-{uuid.uuid4().hex[:8]}@aner-test.com"
    response, committed = await _post_watching_the_response(
        f"{BASE}/users",
        json={"email": email, "password": PASSWORD, "role": "OPERATIONS"},
        headers=auth_header(admin),
        committed=_user_committed(email),
    )
    assert response.status_code == 201, response.text
    assert committed, "the account was not committed when the 201 was sent"


async def test_a_sign_in_commits_its_refresh_token_before_the_response():
    """So a client may use the refresh token it was just given."""
    email = f"signin-{uuid.uuid4().hex[:8]}@aner-test.com"
    create_user_direct(email, UserRole.OPERATIONS)

    def token_committed() -> bool:
        return (
            _count(
                "SELECT count(*) FROM auth.refresh_tokens t JOIN auth.users u "
                "ON u.id = t.user_id WHERE u.email = %s",
                email,
            )
            == 1
        )

    response, committed = await _post_watching_the_response(
        f"{BASE}/login", json={"email": email, "password": PASSWORD}, committed=token_committed
    )
    assert response.status_code == 200, response.text
    assert committed, "the refresh token was not committed when the tokens were sent"
