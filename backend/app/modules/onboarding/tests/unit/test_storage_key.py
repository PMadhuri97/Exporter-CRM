"""The storage key shape, and what it refuses.

Contract: ``storage-and-documents.md`` §2. Architecture §3.4 fixes the shape:
``{env}/{owner_type}/{owner_id}/{source}/{document_id}{ext}``.

Pure: no disk, no settings, no database. The key builder takes ``env`` as an
argument precisely so this file can assert the shape without an environment.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.onboarding.domain.storage import (
    StorageKeyError,
    StorageOwnerType,
    build_storage_key,
    is_safe_key,
)

COMPANY_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def test_key_has_the_shape_the_architecture_fixes():
    key = build_storage_key(
        env="development",
        owner_type=StorageOwnerType.COMPANY,
        owner_id=COMPANY_ID,
        source="exporter_upload",
        document_id=DOCUMENT_ID,
        extension=".pdf",
    )
    assert key == (
        f"development/company/{COMPANY_ID}/exporter_upload/{DOCUMENT_ID}.pdf"
    )


def test_a_deal_owned_key_says_deal():
    key = build_storage_key(
        env="test",
        owner_type=StorageOwnerType.DEAL,
        owner_id=COMPANY_ID,
        source="internal",
        document_id=DOCUMENT_ID,
        extension=".png",
    )
    assert key.split("/")[1] == "deal"


@pytest.mark.parametrize("env", ["Development", "DEVELOPMENT", " development "])
def test_environment_is_normalised_rather_than_refused(env: str):
    """One bucket holds several environments (contract §2), so the segment has to
    be predictable — `Development` and `development` must not become two trees."""
    key = build_storage_key(
        env=env,
        owner_type=StorageOwnerType.COMPANY,
        owner_id=COMPANY_ID,
        source="RXIL",
        document_id=DOCUMENT_ID,
        extension=".PDF",
    )
    assert key.startswith("development/")
    # Source and extension are normalised the same way, for the same reason.
    assert "/rxil/" in key
    assert key.endswith(".pdf")


@pytest.mark.parametrize(
    "bad_env",
    ["", "..", "a/b", "prod uction", "prod/", "/prod", "-leading", "prod\\x"],
)
def test_an_unsafe_environment_segment_is_refused(bad_env: str):
    with pytest.raises(StorageKeyError):
        build_storage_key(
            env=bad_env,
            owner_type=StorageOwnerType.COMPANY,
            owner_id=COMPANY_ID,
            source="internal",
            document_id=DOCUMENT_ID,
            extension=".pdf",
        )


@pytest.mark.parametrize("bad_source", ["", "..", "a/b", "up load", "../../etc"])
def test_an_unsafe_source_segment_is_refused(bad_source: str):
    with pytest.raises(StorageKeyError):
        build_storage_key(
            env="test",
            owner_type=StorageOwnerType.COMPANY,
            owner_id=COMPANY_ID,
            source=bad_source,
            document_id=DOCUMENT_ID,
            extension=".pdf",
        )


@pytest.mark.parametrize(
    "bad_extension",
    ["", "pdf", ".", ".p df", "./x", ".pdf/../x", ".verylongextensionname", ".pd\\f"],
)
def test_an_unsafe_extension_is_refused(bad_extension: str):
    """The extension is the only part of the key that comes from the content, so
    it is the part most worth refusing hard. It never comes from the uploaded
    file name (§9.3's "Watch out for")."""
    with pytest.raises(StorageKeyError):
        build_storage_key(
            env="test",
            owner_type=StorageOwnerType.COMPANY,
            owner_id=COMPANY_ID,
            source="internal",
            document_id=DOCUMENT_ID,
            extension=bad_extension,
        )


def test_a_built_key_is_always_a_safe_key():
    """The two checks must agree: anything the builder produces must pass the
    validator an implementation runs before I/O, or a legitimate upload would be
    refused at the second gate."""
    key = build_storage_key(
        env="production",
        owner_type=StorageOwnerType.DEAL,
        owner_id=COMPANY_ID,
        source="system",
        document_id=DOCUMENT_ID,
        extension=".xlsx",
    )
    assert is_safe_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/absolute/key.pdf",
        "a/../../etc/passwd",
        "a/b/../c.pdf",
        "a/./b.pdf",
        "a//b.pdf",
        "a\\b.pdf",
        "a/b\0.pdf",
        "C:/windows/system32.pdf",
        "a/b/.hidden.pdf",
        "a/b/UPPER.pdf",
        "a/b/c.exe/../d.pdf",
    ],
)
def test_is_safe_key_refuses_traversal_and_oddities(key: str):
    assert is_safe_key(key) is False


@pytest.mark.parametrize(
    "key",
    [
        "development/company/abc/internal/doc.pdf",
        "test/deal/11111111-1111-4111-8111-111111111111/rxil/22222222.png",
        "a/b",
    ],
)
def test_is_safe_key_accepts_ordinary_keys(key: str):
    assert is_safe_key(key) is True
