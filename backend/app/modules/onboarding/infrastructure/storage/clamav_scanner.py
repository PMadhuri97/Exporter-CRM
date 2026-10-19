"""A real scanner: ClamAV, through a clamd daemon's ``INSTREAM`` command.

Satisfies ``ScannerPort`` the way ``PassThroughScanner`` does, and is chosen by
``CRM_DOCUMENT_SCANNER=clamav``. The bytes are streamed to clamd over TCP
(``CLAMAV_HOST``:``CLAMAV_PORT``) — typically a ``clamav/clamav`` sidecar container — so
nothing is written to a shared disk and the daemon needs no access to the bucket.

**It fails closed.** Only clamd's ``OK`` makes a document ``AVAILABLE``. A signature
match is ``QUARANTINED``; anything else — the daemon unreachable, a timeout, a size
limit, an answer this code does not recognise — is ``SCAN_FAILED``, which is never
served. "We could not check" must not become "it is clean".
"""

from __future__ import annotations

import asyncio
import struct

import structlog

from app.modules.onboarding.domain.storage import DocumentScanStatus, ScanOutcome

logger = structlog.get_logger(__name__)

CLAMAV_SCANNER_NAME = "clamav"

#: clamd reads a stream in chunks no larger than its StreamMaxLength allows; 64 KiB
#: keeps each write small without a round trip per byte.
_CHUNK_BYTES = 64 * 1024


class ClamAvScanner:
    """Asks clamd whether stored bytes are clean."""

    name = CLAMAV_SCANNER_NAME

    def __init__(self, host: str, port: int, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout_seconds

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        try:
            reply = await asyncio.wait_for(self._instream(content), timeout=self._timeout)
        except (
            TimeoutError,
            OSError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as exc:
            logger.error(
                "document_scan_failed",
                scanner=self.name,
                key=key,
                error=type(exc).__name__,
                detail=str(exc),
            )
            return ScanOutcome(
                status=DocumentScanStatus.SCAN_FAILED,
                scanner_name=self.name,
                detail=f"the scanner could not be reached ({type(exc).__name__})",
            )
        return self._outcome(key, reply)

    async def _instream(self, content: bytes) -> str:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            # `z` prefix: commands and replies are NUL-terminated.
            writer.write(b"zINSTREAM\0")
            for start in range(0, len(content), _CHUNK_BYTES):
                chunk = content[start : start + _CHUNK_BYTES]
                writer.write(struct.pack("!L", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack("!L", 0))
            await writer.drain()
            raw = await reader.readuntil(b"\0")
            return raw.rstrip(b"\0").decode("utf-8", "replace").strip()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def _outcome(self, key: str, reply: str) -> ScanOutcome:
        # "stream: OK" | "stream: <signature> FOUND" | "<message> ERROR"
        verdict = reply.split(":", 1)[1].strip() if ":" in reply else reply
        if verdict == "OK":
            return ScanOutcome(status=DocumentScanStatus.AVAILABLE, scanner_name=self.name)
        if verdict.endswith(" FOUND"):
            signature = verdict[: -len(" FOUND")].strip()
            logger.warning("document_scan_infected", scanner=self.name, key=key, signature=signature)
            return ScanOutcome(
                status=DocumentScanStatus.QUARANTINED,
                scanner_name=self.name,
                detail=f"malware detected: {signature}",
            )
        logger.error("document_scan_failed", scanner=self.name, key=key, reply=reply)
        return ScanOutcome(
            status=DocumentScanStatus.SCAN_FAILED,
            scanner_name=self.name,
            detail=f"the scanner did not give a verdict: {reply[:200]}",
        )
