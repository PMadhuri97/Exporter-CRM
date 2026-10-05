"""The prototype's scanner, which is not a scanner.

Gate §7.6: the prototype ships a **clearly labelled
pass-through**. This file is that label. It returns clean for everything it is
given, and its name says so wherever the verdict is stored or shown.

Replacing it is the whole point of ``ScannerPort``: AWS GuardDuty Malware
Protection for S3, or a self-hosted ClamAV, becomes a second implementation and
nothing else changes. Gate §7.6 blocks real exporter documents until that
happens.
"""

from __future__ import annotations

import structlog

from app.modules.onboarding.domain.storage import DocumentScanStatus, ScanOutcome

logger = structlog.get_logger(__name__)

#: Stored lowercase on the document row, exactly as a verification provider is
#: stored ``"manual"`` (§7.5); screens display it uppercase.
PASS_THROUGH_SCANNER_NAME = "pass-through"


class PassThroughScanner:
    """Satisfies ``ScannerPort`` by declaring everything clean.

    It does **not** subclass the port — structural typing, like every other
    adapter here — and it deliberately has no configuration: a knob that made it
    sometimes quarantine something would make it look like a scanner.
    """

    name = PASS_THROUGH_SCANNER_NAME

    async def scan(self, key: str, content: bytes) -> ScanOutcome:
        """Return clean, and say in the log that nothing was actually checked.

        The log line is at ``info`` and names the scanner, so a production-shaped
        deployment running this by mistake leaves evidence rather than looking
        like a clean scan history.
        """
        logger.info(
            "document_scan_skipped",
            scanner=self.name,
            key=key,
            size_bytes=len(content),
            detail="pass-through placeholder: no malware check was performed",
        )
        return ScanOutcome(
            status=DocumentScanStatus.AVAILABLE,
            scanner_name=self.name,
            detail="pass-through placeholder: no malware check was performed",
        )
