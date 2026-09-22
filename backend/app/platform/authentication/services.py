from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.platform.configuration.config import settings
from app.shared.exceptions import UnauthorizedError

# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: uuid.UUID, email: str, role: str) -> str:
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),   # unique per token — prevents same-second collisions
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type")
        return payload
    except ExpiredSignatureError:
        raise UnauthorizedError("Token has expired")
    except InvalidTokenError:
        raise UnauthorizedError("Invalid token")


# ── Refresh tokens ────────────────────────────────────────────────────────────

def generate_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hex_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(48)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
