"""Local-disk storage — **owner: Developer 3B** (L3-07).

One implementation of ``StoragePort`` (contract §1). S3 with Object Lock and KMS
is a second implementation of the same port, later (decision D8, gate §7.6);
local disk stays for development and tests either way.

**Every key is validated against the real root before any I/O** (contract §2.1).
The domain's ``build_storage_key`` already refuses an unsafe segment, but a key
can also arrive from a database row or a request, and only this class knows where
the root is — so it checks again, with ``Path.resolve()`` and
``is_relative_to``, never string comparison.

Files are written with ``asyncio.to_thread``: the port is async because S3 will
be, and blocking the event loop on disk I/O in the meantime would make the
prototype's timings lie about the shape of the real thing.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from app.modules.onboarding.domain.storage import (
    DownloadLink,
    StorageKeyError,
    StoredObject,
    is_safe_key,
)
from app.modules.onboarding.infrastructure.storage.config import local_storage_root
from app.platform.configuration.config import settings

logger = structlog.get_logger(__name__)


class LocalDiskStorage:
    """``StoragePort`` over a directory tree.

    Satisfies the port structurally; it does not import it as a base class.
    """

    def __init__(self, root: Path | None = None) -> None:
        #: Resolved once per instance. A caller may pass a root (tests do); the
        #: default comes from the environment at construction time, not at
        #: import time, so a test that sets the variable then builds the storage
        #: gets its own directory.
        self._root = (root or local_storage_root()).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ── Path safety ─────────────────────────────────────────────────────────

    def _resolve(self, key: str) -> Path:
        """The absolute path for a key, or refuse.

        Two checks, in this order:

        1. every segment is a safe path segment (``is_safe_key``), which makes
           ``..``, an absolute key, a backslash and a drive letter unexpressible
           rather than merely filtered;
        2. the resolved path is inside the root.

        The second is the one that matters — it catches whatever the first
        missed — and it runs on the *resolved* path, so a symlink pointing out of
        the tree is caught too.
        """
        if not is_safe_key(key):
            raise StorageKeyError(f"storage key {key!r} is not a safe relative key")

        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageKeyError(
                f"storage key {key!r} resolves outside the storage root"
            )
        return candidate

    # ── StoragePort ─────────────────────────────────────────────────────────

    async def put(self, key: str, content: bytes, *, content_type: str) -> StoredObject:
        """Write bytes at a key, creating the key's parent directories.

        Written to a temporary name in the same directory and then moved into
        place, so a crash mid-write cannot leave a truncated file that looks
        complete. ``size_bytes`` is measured from what was written.
        """
        path = self._resolve(key)

        def _write() -> int:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.partial")
            temporary.write_bytes(content)
            temporary.replace(path)
            return path.stat().st_size

        size_bytes = await asyncio.to_thread(_write)
        logger.info("storage_object_written", key=key, size_bytes=size_bytes)
        return StoredObject(key=key, size_bytes=size_bytes, content_type=content_type)

    async def read(self, key: str) -> bytes:
        path = self._resolve(key)

        def _read() -> bytes:
            if not path.is_file():
                raise FileNotFoundError(key)
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        """Not part of the port — a convenience for tests and for Phase 3's
        delete path, which should not have to read a whole object to find out
        whether it is there."""
        path = self._resolve(key)
        return await asyncio.to_thread(path.is_file)

    async def open_link(self, key: str, *, expires_in: timedelta) -> DownloadLink:
        """A signed, expiring path this application will serve itself.

        Local disk has no presigned URLs, so the link is an API path plus an
        expiry and a signature over both. The signature is keyed on
        ``SECRET_KEY``, so a link cannot be forged by anyone who cannot already
        mint tokens, and the expiry is *inside* the signed material, so it
        cannot be extended by editing the query string.

        The URL stays opaque to callers (contract §1.1): S3 will return
        something entirely different from the same method.
        """
        self._resolve(key)  # refuse an unsafe key before handing out a link
        expires_at = datetime.now(tz=UTC) + expires_in
        expires_ts = int(expires_at.timestamp())
        return DownloadLink(
            url=(
                f"{settings.API_V1_PREFIX}/onboarding/documents/content"
                f"?key={key}&expires={expires_ts}"
                f"&signature={sign_key(key, expires_ts)}"
            ),
            expires_at=expires_at,
        )

    async def delete(self, key: str) -> None:
        """Remove one object. Missing is not an error — deleting twice should
        not be harder than deleting once. Only the file goes; no directory in
        the tree is ever removed."""
        path = self._resolve(key)
        await asyncio.to_thread(path.unlink, True)
        logger.info("storage_object_deleted", key=key)


# ── Link signing ────────────────────────────────────────────────────────────
#
# Module-level so Phase 3's download route can verify what this class issued
# without holding a storage instance.


def sign_key(key: str, expires_ts: int) -> str:
    """HMAC over the key *and* its expiry, hex-encoded.

    Both are signed together: signing only the key would make every link
    permanent, and signing them separately would let one link's expiry be
    swapped for another's.
    """
    message = f"{key}:{expires_ts}".encode()
    return hmac.new(
        settings.SECRET_KEY.encode(), message, hashlib.sha256
    ).hexdigest()


def verify_signed_key(key: str, expires_ts: int, signature: str) -> bool:
    """Whether a signature matches and has not expired.

    ``hmac.compare_digest`` rather than ``==``: a timing-safe comparison, since
    this is a signature check reachable by anyone with the URL.
    """
    if not hmac.compare_digest(sign_key(key, expires_ts), signature):
        return False
    return expires_ts > int(time.time())
