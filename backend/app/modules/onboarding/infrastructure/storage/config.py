"""Where local-disk storage keeps its files — **owner: Developer 3B** (L3-07).

Read from the environment here rather than added to ``platform.configuration.Settings``:
that class is platform-wide and not this developer's to extend, and a storage
root is a module concern. ``Settings`` is still the source for ``ENVIRONMENT``,
which the key's first segment comes from — read, never written.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

#: Default root: inside the repository, and git-ignored. A developer losing
#: uploads on reboot is more surprising than a directory to ignore, so this is
#: not the OS temp dir.
#: `<repo>/backend/app/modules/onboarding/infrastructure/storage/config.py`
#: -> parents[5] is `<repo>/backend`.
DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parents[5] / ".local-storage"


def local_storage_root() -> Path:
    """The configured root, as an absolute path.

    Resolved on every call rather than cached at import: a test sets
    ``STORAGE_LOCAL_ROOT`` to a ``tmp_path`` and expects the next call to see it.
    """
    configured = os.environ.get("STORAGE_LOCAL_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_LOCAL_ROOT


def environment_segment() -> str:
    """The key's first segment: the deployment environment, lowercased.

    One bucket can then hold several environments without them colliding
    (contract §2).
    """
    from app.platform.configuration.config import settings

    return settings.ENVIRONMENT.strip().lower()


#: How long a download link lives. Short, because the link is the only thing
#: standing between a leaked URL and a document: long enough to click, not long
#: enough to pass around.
DOWNLOAD_LINK_TTL = timedelta(minutes=5)


def storage_backend() -> str:
    """Which storage backend to use: 's3' or 'local'.

    Defaults to 's3' if S3_DOCUMENT_BUCKET is set, otherwise 'local'.
    """
    configured = os.environ.get("STORAGE_BACKEND", "").strip().lower()
    if configured:
        return configured
    return "s3" if os.environ.get("S3_DOCUMENT_BUCKET", "").strip() else "local"


def s3_document_bucket() -> str:
    """The configured S3 bucket name for documents."""
    return os.environ.get("S3_DOCUMENT_BUCKET", "").strip()


def s3_region_name() -> str:
    """AWS Region for the S3 bucket."""
    return (
        os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("AWS_REGION")
        or "ap-south-1"
    ).strip()

