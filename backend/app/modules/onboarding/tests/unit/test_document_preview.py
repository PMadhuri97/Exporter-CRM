"""What a document looks like on screen, and how a conversion fails safely.

The real conversion needs LibreOffice, which the backend image installs; here the
rules around it are checked: which types are shown as they are, which are converted,
where the PDF is kept, and that a missing converter means "no preview", never an error.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.modules.onboarding.application import document_preview
from app.modules.onboarding.application.document_preview import (
    convert_to_pdf,
    external_reference,
    is_convertible,
    is_shown_as_is,
    preview_key,
    preview_media_type,
)
from app.modules.onboarding.domain.storage import is_safe_key

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.parametrize(
    "content_type",
    [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/plain; charset=utf-8",
        "image/tiff",
        "text/csv",
    ],
)
def test_pdfs_images_and_text_are_shown_as_they_are(content_type):
    assert is_shown_as_is(content_type)
    assert not is_convertible(content_type)


def test_a_csv_is_served_as_plain_text_and_never_converted():
    assert preview_media_type("text/csv; charset=utf-8") == "text/plain"
    assert preview_media_type("application/pdf") == "application/pdf"


@pytest.mark.parametrize(
    "content_type",
    [DOCX, "application/msword", "application/vnd.ms-excel",
     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
)
def test_office_files_are_converted(content_type):
    assert is_convertible(content_type)
    assert not is_shown_as_is(content_type)


@pytest.mark.parametrize("content_type", ["application/zip", "image/svg+xml", "text/html"])
def test_anything_else_has_no_preview_and_markup_is_never_shown(content_type):
    assert not is_shown_as_is(content_type)
    assert not is_convertible(content_type)


def test_the_pdf_is_kept_beside_the_original_under_a_safe_key():
    key = "prod/company/0b9f3c2e-1111-4222-8333-444455556666/staff/9d8e7f6a-aaaa-4bbb-8ccc-dddd00001111.docx"
    kept = preview_key(key)
    assert kept == (
        "prod/company/0b9f3c2e-1111-4222-8333-444455556666/staff/"
        "9d8e7f6a-aaaa-4bbb-8ccc-dddd00001111-preview.pdf"
    )
    assert is_safe_key(kept)


async def test_no_converter_installed_means_no_preview(monkeypatch):
    monkeypatch.setattr(
        document_preview.settings, "CRM_DOCUMENT_CONVERTER", "no-such-converter-anywhere"
    )
    assert await convert_to_pdf(b"PK\x03\x04", DOCX) is None


async def test_a_type_that_is_not_converted_is_not_attempted():
    assert await convert_to_pdf(b"PK\x03\x04", "application/zip") is None


# ── A document that links outside itself is never converted ──────────────────

_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _package(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, text in parts.items():
            package.writestr(name, text)
    return buffer.getvalue()


def _rels(*relationships: str) -> str:
    return "<Relationships>" + "".join(relationships) + "</Relationships>"


def test_a_word_file_with_only_web_links_may_be_converted():
    content = _package(
        {
            "word/document.xml": '<w:document><w:instrText> HYPERLINK "https://x.example" </w:instrText></w:document>',
            "word/_rels/document.xml.rels": _rels(
                f'<Relationship Id="r1" Type="{_HYPERLINK}" Target="https://x.example" TargetMode="External"/>',
                f'<Relationship Id="r2" Type="{_IMAGE}" Target="media/image1.png"/>',
            ),
        }
    )
    assert external_reference(content, ".docx") is None


@pytest.mark.parametrize(
    "relationship",
    [
        f'<Relationship Id="r1" Type="{_IMAGE}" Target="file:///etc/passwd" TargetMode="External"/>',
        f'<Relationship Id="r1" Type="{_IMAGE}" Target="/proc/self/environ" TargetMode="External"/>',
        f'<Relationship Id="r1" Type="{_IMAGE}" Target="file:///app/.env"/>',
        f'<Relationship Id="r1" Type="{_IMAGE}" Target="\\\\server\\share\\a.png"/>',
    ],
)
def test_a_linked_image_or_object_stops_the_conversion(relationship):
    content = _package({"word/_rels/document.xml.rels": _rels(relationship)})
    assert external_reference(content, ".docx") is not None


@pytest.mark.parametrize(
    "instruction",
    [
        '<w:instrText xml:space="preserve"> INCLUDETEXT "/etc/passwd" </w:instrText>',
        '<w:fldSimple w:instr=" INCLUDEPICTURE &quot;file:///x.png&quot; "/>',
        '<w:instrText> DDEAUTO c:\\windows\\cmd.exe </w:instrText>',
    ],
)
def test_a_field_that_includes_another_file_stops_the_conversion(instruction):
    content = _package({"word/document.xml": f"<w:document>{instruction}</w:document>"})
    assert external_reference(content, ".docx") is not None


@pytest.mark.parametrize(
    "formula",
    ['WEBSERVICE("http://x")', "cmd|' /C calc'!A0", "[1]Sheet1!A1", 'HYPERLINK("file:///etc")'],
)
def test_a_formula_that_reaches_outside_the_workbook_stops_the_conversion(formula):
    content = _package({"xl/worksheets/sheet1.xml": f"<sheetData><c><f>{formula}</f></c></sheetData>"})
    assert external_reference(content, ".xlsx") is not None


def test_an_ordinary_formula_and_an_external_link_part():
    plain = _package({"xl/worksheets/sheet1.xml": "<sheetData><c><f>SUM(A1:A3)</f></c></sheetData>"})
    assert external_reference(plain, ".xlsx") is None
    linked = _package({"xl/externalLinks/externalLink1.xml": "<externalLink/>"})
    assert external_reference(linked, ".xlsx") is not None


def test_a_package_that_cannot_be_read_is_not_converted():
    assert external_reference(b"PK\x03\x04 not really", ".docx") is not None


def test_an_old_binary_file_with_a_file_link_is_not_converted():
    assert external_reference(b"\xd0\xcf\x11\xe0 plain text Profile: fine", ".doc") is None
    assert external_reference(b"\xd0\xcf\x11\xe0 INCLUDETEXT x", ".doc") is not None
    assert external_reference("file:///etc/passwd".encode("utf-16-le"), ".xls") is not None


async def test_a_linking_document_is_refused_before_the_converter_runs(monkeypatch):
    called = []
    monkeypatch.setattr(document_preview.shutil, "which", lambda name: called.append(name))
    content = _package(
        {"word/_rels/document.xml.rels": _rels(
            f'<Relationship Id="r1" Type="{_IMAGE}" Target="file:///etc/passwd" TargetMode="External"/>'
        )}
    )
    assert await convert_to_pdf(content, DOCX) is None
    assert called == []


def test_the_converter_gets_none_of_the_servers_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEYS", "k:secret")
    environment = document_preview._converter_environment(tmp_path)
    assert "DATABASE_URL" not in environment
    assert "FIELD_ENCRYPTION_KEYS" not in environment
    assert environment["HOME"] == str(tmp_path)
