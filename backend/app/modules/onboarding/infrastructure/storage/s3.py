"""AWS S3 storage adapter — **owner: Developer 3B** (L3-07, L3-08, decision D8, gate §7.6).

Implementation of ``StoragePort`` (contract §1) backing document persistence
with a private Amazon S3 bucket.

Every key is validated against safe relative path segments before any S3 call.
All S3 operations are dispatched via ``asyncio.to_thread`` to keep the FastAPI
event loop non-blocking.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import structlog

from app.modules.onboarding.domain.storage import (
    DownloadLink,
    StorageKeyError,
    StoredObject,
    is_safe_key,
)
from app.modules.onboarding.infrastructure.storage.config import (
    s3_document_bucket,
    s3_region_name,
)
from app.modules.onboarding.infrastructure.storage.local_disk import sign_key
from app.platform.configuration.config import settings

logger = structlog.get_logger(__name__)


class S3Storage:
    """``StoragePort`` backed by an Amazon S3 bucket."""

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket or s3_document_bucket()
        if not self._bucket:
            raise ValueError(
                "S3_DOCUMENT_BUCKET must be set to use S3Storage (e.g. 'aner-crm-documents')"
            )
        self._region = region or s3_region_name()

        if client is not None:
            self._client = client
        else:
            access_key = (
                os.environ.get("AWS_ACCESS_KEY_ID")
                or os.environ.get("aws_access_key_id")
            )
            secret_key = (
                os.environ.get("AWS_SECRET_ACCESS_KEY")
                or os.environ.get("aws_secret_access_key")
            )
            session_token = (
                os.environ.get("AWS_SESSION_TOKEN")
                or os.environ.get("aws_session_token")
            )

            client_kwargs: dict[str, Any] = {
                "region_name": self._region,
                "config": Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            }
            if access_key and secret_key:
                client_kwargs["aws_access_key_id"] = access_key.strip()
                client_kwargs["aws_secret_access_key"] = secret_key.strip()
                if session_token:
                    client_kwargs["aws_session_token"] = session_token.strip()

            self._client = boto3.client("s3", **client_kwargs)

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def region(self) -> str:
        return self._region

    # ── Key validation ───────────────────────────────────────────────────────

    def _validate_key(self, key: str) -> None:
        """Refuse any key with invalid segments or traversal attempts."""
        if not is_safe_key(key):
            raise StorageKeyError(f"storage key {key!r} is not a safe relative key")

    # ── StoragePort ──────────────────────────────────────────────────────────

    async def put(self, key: str, content: bytes, *, content_type: str) -> StoredObject:
        """Store bytes in S3 with server-side encryption (AES256)."""
        self._validate_key(key)

        def _put() -> int:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
            return len(content)

        size_bytes = await asyncio.to_thread(_put)
        logger.info(
            "s3_object_written",
            bucket=self._bucket,
            key=key,
            size_bytes=size_bytes,
            content_type=content_type,
        )
        return StoredObject(key=key, size_bytes=size_bytes, content_type=content_type)

    async def read(self, key: str) -> bytes:
        """Download bytes from S3."""
        self._validate_key(key)

        def _read() -> bytes:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
                return response["Body"].read()
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("NoSuchKey", "404"):
                    raise FileNotFoundError(key) from exc
                raise

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        """Check whether an object exists in S3."""
        self._validate_key(key)

        def _exists() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey"):
                    return False
                raise

        return await asyncio.to_thread(_exists)

    async def open_link(self, key: str, *, expires_in: timedelta) -> DownloadLink:
        """A signed, expiring path that this application will serve.

        Contract §6.1: download routes are role-gated as well as signed. The URL
        scopes access to the single key and its expiry, while keeping the bucket
        fully private without exposing AWS endpoints to the client.
        """
        self._validate_key(key)
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

    async def generate_presigned_url(self, key: str, *, expires_in: timedelta) -> DownloadLink:
        """Generate a direct S3 presigned GET URL (alternative direct download)."""
        self._validate_key(key)
        expires_at = datetime.now(tz=UTC) + expires_in
        expires_seconds = int(expires_in.total_seconds())

        def _sign() -> str:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_seconds,
            )

        url = await asyncio.to_thread(_sign)
        return DownloadLink(url=url, expires_at=expires_at)

    async def delete(self, key: str) -> None:
        """Remove an object from S3. Deleting a non-existent object succeeds silently."""
        self._validate_key(key)

        def _delete() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        await asyncio.to_thread(_delete)
        logger.info("s3_object_deleted", bucket=self._bucket, key=key)
