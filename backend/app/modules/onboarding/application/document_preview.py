"""What a document looks like on screen.

People read documents in the CRM; saving a copy is a separate permission
(``documents:download``). So every servable document needs an on-screen form:

* **As it is** — a PDF, an image or a plain-text file, which a browser renders and
  the screen draws without its own save controls. A CSV is served as the plain text
  it is.
* **Converted** — a Word, Excel or PowerPoint file, turned into a PDF by LibreOffice
  running headless (``CRM_DOCUMENT_CONVERTER``), with a time limit
  (``CRM_DOCUMENT_CONVERTER_TIMEOUT_SECONDS``). Converted once, on first view, and kept.
* **None** — anything else (a zip). The original stays downloadable for those who
  may download.

**The files converted come from outside the company**, and LibreOffice follows what a
document links to while it lays it out: a linked image, an INCLUDETEXT field or an
external workbook can pull a local file — the server's configuration, a secret — into
the PDF everyone may read. So a document is converted only when it links to nothing
but web pages (:func:`external_reference` says what it found otherwise), and the
converter runs with an empty environment in a private directory. The converter should
still run where the server's secrets are not (``docs/remaining-work.md``).

A conversion never touches the original. A failure — no converter installed, a
timeout, a file LibreOffice cannot read, a document that links outside itself — is
reported as "no preview", never as an error the reader has to understand.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import zipfile
from io import BytesIO
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
        "text/csv",
    }
)

#: What a type shown as it is goes out as, where that differs: a CSV is read as text.
_SERVED_AS: dict[str, str] = {"text/csv": "text/plain"}

#: Converted to PDF, with the extension LibreOffice reads the file by.
CONVERTIBLE_TYPES: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
}

READY = "READY"
UNAVAILABLE = "UNAVAILABLE"


def base_type(content_type: str) -> str:
    return content_type.split(";")[0].strip().lower()


def is_shown_as_is(content_type: str) -> bool:
    return base_type(content_type) in AS_IS_TYPES


def is_convertible(content_type: str) -> bool:
    return base_type(content_type) in CONVERTIBLE_TYPES


def preview_media_type(content_type: str) -> str:
    """The type a document shown as it is goes out as."""
    kind = base_type(content_type)
    return _SERVED_AS.get(kind, kind)


# ── What a document links to ─────────────────────────────────────────────────

_OOXML = frozenset({".docx", ".xlsx", ".pptx"})
#: Relationships LibreOffice does not fetch while converting: a link a reader may click,
#: and the template a Word file was made from (recorded, never loaded).
_HARMLESS_RELATIONSHIPS = ("/hyperlink", "/attachedTemplate")
#: Word fields that bring another file's content in.
_INCLUDING_FIELDS = re.compile(
    r"\b(INCLUDETEXT|INCLUDEPICTURE|INCLUDE|LINK|DDE|DDEAUTO|IMPORT)\b", re.IGNORECASE
)
#: Spreadsheet formulas that reach outside the workbook: a web service, a local file,
#: a DDE link (``app|topic!item``) or another workbook (``[1]Sheet1!A1``).
_REACHING_FORMULA = re.compile(r"WEBSERVICE\s*\(|FILTERXML\s*\(|file:|\||\[\d+\]", re.IGNORECASE)
#: In an old binary Office file, the marks of the same things (ASCII and UTF-16).
_LEGACY_MARKERS = (b"file:/", b"includetext", b"includepicture", b"ddeauto", b"webservice")
#: A package bigger than this unpacked is not inspected, so not converted.
_MAX_UNPACKED_BYTES = 100 * 1024 * 1024

_RELATIONSHIP = re.compile(r"<Relationship\b[^>]*>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_INSTRUCTION = re.compile(r'<w:instrText\b[^>]*>([^<]*)</w:instrText>|w:instr="([^"]*)"')
_FORMULA = re.compile(r"<f\b[^>]*>([^<]*)</f>")


def external_reference(content: bytes, extension: str) -> str | None:
    """What in this document reaches outside it, or ``None`` when nothing does (links a
    reader may click aside). A package that cannot be inspected counts as reaching out."""
    if extension in _OOXML:
        return _ooxml_reference(content)
    lowered = content.lower()
    for marker in _LEGACY_MARKERS:
        if marker in lowered or marker.decode().encode("utf-16-le") in lowered:
            return f"it contains {marker.decode()!r}"
    return None


def _ooxml_reference(content: bytes) -> str | None:
    try:
        package = zipfile.ZipFile(BytesIO(content))
        parts = package.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return "it is not a readable Office package"
    if sum(part.file_size for part in parts) > _MAX_UNPACKED_BYTES:
        return "it is too large unpacked to inspect"
    for part in parts:
        name = part.filename
        lowered = name.lower()
        if lowered.startswith("xl/externallinks/") or lowered == "xl/connections.xml":
            return f"it links to another workbook or a data source ({name})"
        relationships = lowered.endswith(".rels")
        fields = lowered.startswith("word/") and lowered.endswith(".xml")
        formulas = lowered.startswith("xl/worksheets/") and lowered.endswith(".xml")
        if not (relationships or fields or formulas):
            continue
        try:
            text = package.read(part).decode("utf-8", "replace")
        except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
            return f"part {name} cannot be read"
        if relationships:
            for tag in _RELATIONSHIP.findall(text):
                attributes = dict(_ATTRIBUTE.findall(tag))
                if attributes.get("Type", "").endswith(_HARMLESS_RELATIONSHIPS):
                    continue
                target = attributes.get("Target", "")
                if (
                    attributes.get("TargetMode", "").lower() == "external"
                    or ":" in target
                    or target.startswith(("//", "\\\\"))
                ):
                    return f"it links to {target!r} ({name})"
        if fields:
            instructions = " ".join(a or b for a, b in _INSTRUCTION.findall(text))
            found = _INCLUDING_FIELDS.search(instructions)
            if found:
                return f"it has a {found.group(1).upper()} field ({name})"
        if formulas:
            for formula in _FORMULA.findall(text):
                if _REACHING_FORMULA.search(formula):
                    return f"a formula reaches outside the workbook ({name})"
    return None


def _converter_environment(work: Path) -> dict[str, str]:
    """An environment with nothing of the server's in it — no database URL, no keys:
    only what a process needs to start, and a home inside the private directory."""
    kept = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
    }
    return {**kept, "HOME": str(work), "TMPDIR": str(work), "TEMP": str(work), "TMP": str(work)}


def preview_key(storage_key: str) -> str:
    """Where a document's PDF preview is kept: beside the original."""
    stem = storage_key.rsplit(".", 1)[0]
    return f"{stem}-preview.pdf"


async def convert_to_pdf(content: bytes, content_type: str) -> bytes | None:
    """The document as a PDF, or ``None`` when it cannot be converted.

    Refuses a document that links outside itself (:func:`external_reference`). Runs the
    converter with an empty environment in a private temporary directory (its own
    profile, so two conversions never share LibreOffice state) and kills it at the time
    limit."""
    extension = CONVERTIBLE_TYPES.get(base_type(content_type))
    if extension is None:
        return None
    reaches_out = external_reference(content, extension)
    if reaches_out is not None:
        logger.warning(
            "document_preview.refused_external_reference",
            content_type=content_type,
            reason=reaches_out,
        )
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
            env=_converter_environment(work),
            cwd=str(work),
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
    "external_reference",
    "is_convertible",
    "is_shown_as_is",
    "preview_key",
    "preview_media_type",
]
