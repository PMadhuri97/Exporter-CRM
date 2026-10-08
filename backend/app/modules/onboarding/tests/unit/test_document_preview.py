"""What a document looks like on screen, and how a conversion fails safely.

The real conversion needs LibreOffice, which the backend image installs; here the
rules around it are checked: which types are shown as they are, which are converted,
where the PDF is kept, and that a missing converter means "no preview", never an error.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.application import document_preview
from app.modules.onboarding.application.document_preview import (
    convert_to_pdf,
    is_convertible,
    is_shown_as_is,
    preview_key,
)
from app.modules.onboarding.domain.storage import is_safe_key

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.parametrize(
    "content_type",
    ["application/pdf", "image/png", "image/jpeg", "text/plain; charset=utf-8", "image/tiff"],
)
def test_pdfs_images_and_text_are_shown_as_they_are(content_type):
    assert is_shown_as_is(content_type)
    assert not is_convertible(content_type)


@pytest.mark.parametrize(
    "content_type",
    [DOCX, "application/msword", "application/vnd.ms-excel", "text/csv",
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
