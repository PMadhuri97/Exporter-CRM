"""Grant the first roles without editing the database by hand.

    python -m app.platform.authentication.cli bootstrap
    python -m app.platform.authentication.cli promote <email> <ROLE>

**Why this exists.** `POST /auth/register` is unauthenticated, so it can only
ever grant `API_USER` — a caller-supplied role on an open route is a privilege
escalation. Every other role therefore had to be granted with a hand-written
`UPDATE auth.users SET role = ...`, which is an unreviewable, untested,
easy-to-mistype operation against the table that decides who may approve a
compliance case. This is that operation, written down once.

**Idempotent by construction.** `bootstrap` creates a user only when no row
holds that email. An existing user is left exactly as it is — same role, same
password, same `updated_at`. It never repairs or overwrites: a second run that
found the ADMIN already at `OPERATIONS` would have to choose between silently
re-elevating it and silently accepting it, and re-elevating on a routine
re-run is how a demotion gets undone without anyone noticing. Changing an
existing user's role is `promote`, which says so in its name.

**Why not an async session.** `app.platform.database.services` builds its
engine from the same settings and would work, but this runs as a one-shot
process against a database that may be mid-migration, and `psycopg2` is what
every other out-of-band operation in this repository already uses
(`authentication.testing`, the migration runner). One connection, one
transaction, no event loop.
"""

from __future__ import annotations

import argparse
import sys
import uuid

import psycopg2

from app.platform.authentication.models import UserRole
from app.platform.authentication.services import hash_password
from app.platform.configuration.config import get_settings

#: Exit code for a refusal the operator has to fix (blank password, unknown
#: role, no such user). Distinct from an unexpected crash so a wrapper script
#: can tell "you configured it wrong" from "it broke".
EXIT_INVALID = 2


class BootstrapError(Exception):
    """A refusal the operator can act on. Printed without a traceback."""


def _dsn() -> str:
    return get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")


def _create_if_absent(cur, email: str, password: str, role: UserRole) -> tuple[str, bool]:
    """Insert an active user at `role` unless `email` already exists.

    Returns `(user_id, created)`. The lookup and the insert share the caller's
    transaction, and `ix_users_email` is unique, so two concurrent runs cannot
    both create the same account — the loser raises and the whole run rolls
    back rather than leaving one of the two accounts half-made.
    """
    cur.execute("SELECT id FROM auth.users WHERE email = %s", (email,))
    row = cur.fetchone()
    if row is not None:
        return str(row[0]), False

    user_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO auth.users (id, email, hashed_password, full_name, role, is_active) "
        "VALUES (%s, %s, %s, %s, %s, TRUE)",
        (str(user_id), email, hash_password(password), None, role.value),
    )
    return str(user_id), True


def _require_credentials(label: str, email: str, password: str) -> None:
    if not email.strip():
        raise BootstrapError(
            f"{label}_EMAIL is not set. Set it in the environment or backend/.env."
        )
    if not password:
        raise BootstrapError(
            f"{label}_PASSWORD is blank. Set it to a real password "
            f"(for example `openssl rand -base64 24`); this command will not "
            f"invent one."
        )


def bootstrap() -> int:
    """Create the first ADMIN and one COMPLIANCE user, if they do not exist."""
    settings = get_settings()

    _require_credentials(
        "FIRST_ADMIN", settings.FIRST_ADMIN_EMAIL, settings.FIRST_ADMIN_PASSWORD
    )
    _require_credentials(
        "FIRST_COMPLIANCE",
        settings.FIRST_COMPLIANCE_EMAIL,
        settings.FIRST_COMPLIANCE_PASSWORD,
    )

    wanted = [
        (settings.FIRST_ADMIN_EMAIL.strip(), settings.FIRST_ADMIN_PASSWORD, UserRole.ADMIN),
        (
            settings.FIRST_COMPLIANCE_EMAIL.strip(),
            settings.FIRST_COMPLIANCE_PASSWORD,
            UserRole.COMPLIANCE,
        ),
    ]
    if wanted[0][0].lower() == wanted[1][0].lower():
        raise BootstrapError(
            "FIRST_ADMIN_EMAIL and FIRST_COMPLIANCE_EMAIL are the same address; "
            "one account cannot hold both roles."
        )

    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            for email, password, role in wanted:
                user_id, created = _create_if_absent(cur, email, password, role)
                verb = "created" if created else "already exists, left unchanged"
                print(f"{role.value:<10} {email}  {verb}  ({user_id})")
        conn.commit()
    finally:
        conn.close()
    return 0


def promote(email: str, role_name: str) -> int:
    """Change an existing user's role (planning assumption A12).

    Separate from `bootstrap` because it is the destructive half: it overwrites
    a role someone may have deliberately set. It refuses an unknown email
    rather than creating one, so a typo cannot quietly mint a second ADMIN.
    """
    try:
        role = UserRole(role_name.upper())
    except ValueError:
        valid = ", ".join(r.value for r in UserRole)
        raise BootstrapError(f"Unknown role {role_name!r}. One of: {valid}") from None

    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, role FROM auth.users WHERE email = %s", (email,)
            )
            row = cur.fetchone()
            if row is None:
                raise BootstrapError(
                    f"No user {email!r}. `promote` changes an existing account; "
                    f"it does not create one."
                )
            user_id, current = row
            if current == role.value:
                print(f"{email} is already {role.value}; nothing to do  ({user_id})")
                return 0

            # `updated_at` moves here, and should: the role genuinely changed.
            cur.execute(
                "UPDATE auth.users SET role = %s, updated_at = now() WHERE id = %s",
                (role.value, user_id),
            )
            print(f"{email}  {current} -> {role.value}  ({user_id})")
        conn.commit()
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.platform.authentication.cli",
        description="Grant the first roles without editing the database by hand.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "bootstrap",
        help="Create the first ADMIN and one COMPLIANCE user from the environment.",
        description=(
            "Reads FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD and "
            "FIRST_COMPLIANCE_EMAIL / FIRST_COMPLIANCE_PASSWORD. Existing "
            "accounts are left untouched, so running it twice changes nothing."
        ),
    )

    promote_parser = sub.add_parser(
        "promote",
        help="Change an existing user's role.",
    )
    promote_parser.add_argument("email")
    promote_parser.add_argument(
        "role", help="One of: " + ", ".join(r.value for r in UserRole)
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            return bootstrap()
        return promote(args.email, args.role)
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
