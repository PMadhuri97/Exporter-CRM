"""What a document looks like on screen.

People read documents in the CRM; saving a copy is a separate permission
(``documents:download``). So every servable document needs an on-screen form:

* **As it is** — a PDF, an image or a plain-text file, which a browser renders and
  the screen draws without its own save controls.
* **Converted** — a Word, Excel, PowerPoint or CSV file, turned into a PDF by
  LibreOffice running headless (``CRM_DOCUMENT_CONVERTER``), with a time limit
  (``CRM_DOCUMENT_CONVERTER_TIMEOUT_SECONDS``). Converted once, on first view, and kept.
* **None** — anything else (a zip). The original stays downloadable for those who
  may download.

A conversion never touches the original. A failure — no converter installed, a
timeout, a file LibreOffice cannot read — is reported as "no preview", never as an
error the reader has to understand.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import structlog

from app.platform.configuration.config import settings

logger = structlog.get_logger(__name__)

#: Shown as they are.
AS_IS_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "text/plain",
    }
)

#: Converted to PDF, with the extension LibreOffice reads the file by.
CONVERTIBLE_TYPES: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
    "text/csv": ".csv",
}

READY = "READY"
UNAVAILABLE = "UNAVAILABLE"


def base_type(content_type: str) -> str:
    return content_type.split(";")[0].strip().lower()


def is_shown_as_is(content_type: str) -> bool:
    return base_type(content_type) in AS_IS_TYPES


def is_convertible(content_type: str) -> bool:
    return base_type(content_type) in CONVERTIBLE_TYPES


def preview_key(storage_key: str) -> str:
    """Where a document's PDF preview is kept: beside the original."""
    stem = storage_key.rsplit(".", 1)[0]
    return f"{stem}-preview.pdf"


async def convert_to_pdf(content: bytes, content_type: str) -> bytes | None:
    """The document as a PDF, or ``None`` when it cannot be converted.

    Runs the converter in a private temporary directory (its own profile, so two
    conversions never share LibreOffice state) and kills it at the time limit."""
    extension = CONVERTIBLE_TYPES.get(base_type(content_type))
    if extension is None:
        return None
    converter = shutil.which(settings.CRM_DOCUMENT_CONVERTER)
    if converter is None:
        logger.warning("document_preview.no_converter", converter=settings.CRM_DOCUMENT_CONVERTER)
        return None
    with tempfile.TemporaryDirectory(prefix="crm-preview-") as workdir:
        work = Path(workdir)
        source = work / f"document{extension}"
        source.write_bytes(content)
        process = await asyncio.create_subprocess_exec(
            converter,
            f"-env:UserInstallation=file:///{(work / 'profile').as_posix().lstrip('/')}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work),
            str(source),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=settings.CRM_DOCUMENT_CONVERTER_TIMEOUT_SECONDS
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("document_preview.conversion_timed_out", content_type=content_type)
            return None
        output = work / "document.pdf"
        if process.returncode != 0 or not output.is_file():
            logger.warning(
                "document_preview.conversion_failed",
                content_type=content_type,
                returncode=process.returncode,
                stderr=(stderr or b"")[:500].decode("utf-8", "replace"),
            )
            return None
        return output.read_bytes()


__all__ = [
    "AS_IS_TYPES",
    "CONVERTIBLE_TYPES",
    "READY",
    "UNAVAILABLE",
    "convert_to_pdf",
    "is_convertible",
    "is_shown_as_is",
    "preview_key",
]
