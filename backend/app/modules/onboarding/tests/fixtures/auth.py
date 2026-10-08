"""Re-export of the shared role-granting test helpers — see
`app.platform.authentication.testing` — plus custom-role users for the "lead"
permissions.

A lead is not an enum value: it is a custom role that holds a built-in role's grants
and one more (`compliance:assign`, `exporters:assign_rm`,
`compliance:approve_high_risk`). `user_with_permissions` builds exactly that, the way
role management would, so a test exercises the real permission path
(`resolve_permissions` through `users.role_id`).
"""

from __future__ import annotations

import uuid

import psycopg2
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import (
    PASSWORD,
    _sync_dsn,
    auth_header,
    create_user_direct,
    token_with_role,
    user_with_role,
)


def _custom_role(base: UserRole, extra: tuple[tuple[str, str], ...]) -> str:
    """A custom role with `base`'s seeded grants plus `extra`. Returns its id."""
    role_id = str(uuid.uuid4())
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth.role (id, slug, name, description, builtin_role, is_assignable) "
                "VALUES (%s, %s, %s, %s, NULL, TRUE)",
                (role_id, f"lead-{role_id[:8]}", f"Lead {role_id[:8]}", "test lead role"),
            )
            cur.execute(
                "INSERT INTO auth.role_permission (id, role_id, module, action) "
                "SELECT gen_random_uuid(), %s, rp.module, rp.action "
                "FROM auth.role_permission rp JOIN auth.role r ON r.id = rp.role_id "
                "WHERE r.builtin_role = %s",
                (role_id, base.value),
            )
            for module, action in extra:
                cur.execute(
                    "INSERT INTO auth.role_permission (id, role_id, module, action) "
                    "VALUES (gen_random_uuid(), %s, %s, %s) ON CONFLICT DO NOTHING",
                    (role_id, module, action),
                )
        conn.commit()
    finally:
        conn.close()
    return role_id


async def user_with_permissions(
    client: AsyncClient,
    role: UserRole,
    *permissions: tuple[str, str],
    email_prefix: str | None = None,
    full_name: str | None = None,
) -> tuple[str, str]:
    """A user whose enum role is `role` and whose assigned custom role adds
    `permissions`. Returns (user_id, access_token)."""
    prefix = email_prefix or f"{role.value.lower()}-lead"
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@aner-test.com"
    user_id = create_user_direct(email, role, full_name=full_name)
    role_id = _custom_role(role, permissions)
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE auth.users SET role_id = %s WHERE id = %s", (role_id, user_id))
        conn.commit()
    finally:
        conn.close()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return user_id, login.json()["access_token"]


def deactivate(user_id: str) -> None:
    """Deactivate an account directly, as an administrator would."""
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE auth.users SET is_active = FALSE, deactivated_at = now() WHERE id = %s",
                (user_id,),
            )
        conn.commit()
    finally:
        conn.close()


__all__ = [
    "auth_header",
    "deactivate",
    "token_with_role",
    "user_with_permissions",
    "user_with_role",
]
