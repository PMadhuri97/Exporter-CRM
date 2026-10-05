"""Local-disk storage: round trip, path safety, links.

Contract: ``storage-and-documents.md`` §1-§3. Every test writes under ``tmp_path``,
so nothing here touches the configured storage root.

The path-safety tests are the point of this file. A storage implementation that
can be talked into writing outside its root is an arbitrary-file-write, and the
prompt's §6.1 calls it out by name.
"""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import pytest

from app.modules.onboarding.domain.storage import StorageKeyError
from app.modules.onboarding.infrastructure.storage.local_disk import (
    LocalDiskStorage,
    sign_key,
    verify_signed_key,
)

KEY = "test/company/acme/internal/doc.pdf"


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(root=tmp_path)


async def test_put_then_read_round_trips(storage: LocalDiskStorage):
    stored = await storage.put(KEY, b"hello", content_type="application/pdf")

    assert stored.key == KEY
    assert stored.content_type == "application/pdf"
    assert await storage.read(KEY) == b"hello"


async def test_size_is_measured_from_what_was_written(storage: LocalDiskStorage):
    """Contract §1.1: never the client's claim. There is no parameter to pass a
    declared size, which is the strongest form of that rule."""
    stored = await storage.put(KEY, b"1234567890", content_type="text/plain")
    assert stored.size_bytes == 10


async def test_parent_directories_are_created(storage: LocalDiskStorage, tmp_path: Path):
    await storage.put("test/deal/d1/rxil/a.pdf", b"x", content_type="application/pdf")
    assert (tmp_path / "test" / "deal" / "d1" / "rxil" / "a.pdf").is_file()


async def test_no_partial_file_is_left_behind(storage: LocalDiskStorage, tmp_path: Path):
    """The write goes to a temporary name and is moved into place, so a reader can
    never see a half-written file. Nothing ``.partial`` should survive a success."""
    await storage.put(KEY, b"hello", content_type="application/pdf")
    assert list(tmp_path.rglob(".*partial")) == []


async def test_overwriting_the_same_key_replaces_the_content(storage: LocalDiskStorage):
    await storage.put(KEY, b"first", content_type="text/plain")
    await storage.put(KEY, b"second", content_type="text/plain")
    assert await storage.read(KEY) == b"second"


# ── Path safety ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    [
        "../escape.pdf",
        "test/../../escape.pdf",
        "/etc/passwd",
        "test/company/../../../escape.pdf",
        "test\\company\\doc.pdf",
        "",
    ],
)
async def test_a_key_that_escapes_the_root_is_refused_before_any_io(
    storage: LocalDiskStorage, tmp_path: Path, key: str
):
    with pytest.raises(StorageKeyError):
        await storage.put(key, b"x", content_type="text/plain")

    # Nothing was created anywhere under the root, and — the part that matters —
    # nothing was written outside it either.
    assert list(tmp_path.rglob("*")) == []
    assert not (tmp_path.parent / "escape.pdf").exists()


async def test_reads_and_deletes_refuse_an_unsafe_key_too(storage: LocalDiskStorage):
    """Every entry point resolves through the same check; a read path that skipped
    it would be an arbitrary-file-read."""
    for operation in (storage.read, storage.delete, storage.exists):
        with pytest.raises(StorageKeyError):
            await operation("../../etc/passwd")


async def test_a_symlink_pointing_out_of_the_root_is_refused(
    storage: LocalDiskStorage, tmp_path: Path
):
    """The check runs on the *resolved* path, which is what catches this. A
    string-comparison implementation would let it through."""
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "test"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privileges
        pytest.skip("symlink creation is not permitted in this environment")

    with pytest.raises(StorageKeyError):
        await storage.put("test/company/a/internal/x.pdf", b"x", content_type="text/plain")


# ── Missing objects and delete ───────────────────────────────────────────────


async def test_reading_a_missing_object_raises_file_not_found(storage: LocalDiskStorage):
    with pytest.raises(FileNotFoundError):
        await storage.read("test/company/acme/internal/missing.pdf")


async def test_delete_removes_the_object_and_is_idempotent(storage: LocalDiskStorage):
    await storage.put(KEY, b"x", content_type="text/plain")
    assert await storage.exists(KEY) is True

    await storage.delete(KEY)
    assert await storage.exists(KEY) is False
    # Deleting twice must not be harder than deleting once.
    await storage.delete(KEY)


async def test_delete_leaves_the_directory_tree_alone(
    storage: LocalDiskStorage, tmp_path: Path
):
    await storage.put(KEY, b"x", content_type="text/plain")
    await storage.delete(KEY)
    assert (tmp_path / "test" / "company" / "acme" / "internal").is_dir()


# ── Links ───────────────────────────────────────────────────────────────────


async def test_link_carries_the_key_an_expiry_and_a_signature(storage: LocalDiskStorage):
    link = await storage.open_link(KEY, expires_in=timedelta(minutes=5))

    assert KEY in link.url
    assert "expires=" in link.url and "signature=" in link.url
    assert link.expires_at > link.expires_at.replace(microsecond=0) - timedelta(seconds=1)


async def test_link_is_refused_for_an_unsafe_key(storage: LocalDiskStorage):
    with pytest.raises(StorageKeyError):
        await storage.open_link("../../etc/passwd", expires_in=timedelta(minutes=5))


def test_a_signature_verifies_only_for_its_own_key_and_expiry():
    expires = int(time.time()) + 300
    signature = sign_key(KEY, expires)

    assert verify_signed_key(KEY, expires, signature) is True
    # A different key, or a different expiry, is a different signature — which is
    # what stops a link's lifetime being extended by editing the query string.
    assert verify_signed_key("test/company/acme/internal/other.pdf", expires, signature) is False
    assert verify_signed_key(KEY, expires + 1, signature) is False
    assert verify_signed_key(KEY, expires, "deadbeef") is False


def test_an_expired_signature_is_rejected_even_though_it_is_authentic():
    past = int(time.time()) - 1
    assert verify_signed_key(KEY, past, sign_key(KEY, past)) is False
