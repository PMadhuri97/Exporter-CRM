"""Configuration for idempotency platform capability.

Key expiry windows are GitOps-managed data, not application constants. They live in
deployments/gitops/reference-data/idempotency/key-expiry.yaml so that changing how long a
customer key stays claimed is a reviewed configuration commit rather than a code change and
a redeploy — an expiry duration written into application logic is an S3T1 defect.

This module reads that file and hands the registration service a mapping of key type to
window. It is the only place in the capability that knows a duration at all.

The file is read once and cached: it is deployment-time data, and re-reading it per
registration would put a filesystem stat on the hot path for a value that cannot change
without a redeploy. Tests that need a different window call load_key_expiry_windows()
directly with their own directory, which is uncached, or reset the cache explicitly.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import structlog
import yaml

from app.platform.configuration.config import settings
from app.platform.idempotency.exceptions import KeyExpiryConfigurationError
from app.platform.idempotency.models import IdempotencyKeyType

logger = structlog.get_logger(__name__)

#: GitOps-managed configuration directory. Resolved here once so the startup path and the
#: tests that point at a fixture directory share one definition rather than rebuilding it
#: from ``__file__`` offsets in two places.
CONFIG_DIR = (
    # <repo>/backend/app/platform/idempotency/<this file>
    Path(__file__).resolve().parents[4]
    / "deployments"
    / "gitops"
    / "reference-data"
    / "idempotency"
)

KEY_EXPIRY_FILENAME = "key-expiry.yaml"

#: Top-level key in the document. Named rather than inlined so a typo in the file produces
#: "missing key_expiry section" instead of an empty mapping that silently expires nothing.
KEY_EXPIRY_SECTION = "key_expiry"

#: Top-level key holding how often the expiry sweep runs.
SWEEP_INTERVAL_KEY = "sweep_interval_seconds"

#: Suffix every window key carries.
#:
#: Every duration in this file is a plain integer count of seconds. The unit therefore has
#: to live somewhere, and it lives in the key name: `customer_key_seconds: 86400` cannot be
#: misread, where a bare `customer_key: 86400` invites the next person to write `24` and
#: mean hours. This also matches how the rest of the platform names durations —
#: INTEGRITY_CHECK_INTERVAL_SECONDS, ACCESS_TOKEN_EXPIRE_MINUTES.
SECONDS_SUFFIX = "_seconds"


def key_name_for(key_type: IdempotencyKeyType) -> str:
    """The configuration key holding a key type's window."""
    return f"{key_type.value}{SECONDS_SUFFIX}"


def parse_seconds(raw: Any, *, field: str) -> timedelta | None:
    """Parse a whole number of seconds, or None for "does not expire on a clock".

    Strings are rejected even when they would parse: '86400' and '24h' both mean somebody
    is writing this file to a different convention than it declares, and quietly accepting
    either is how the two conventions end up coexisting.
    """
    if raw is None:
        return None

    # bool is an int subclass, and `customer_key_seconds: true` should not become 1 second.
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise KeyExpiryConfigurationError(
            f"{field}: expected a whole number of seconds or null, got "
            f"{type(raw).__name__} {raw!r}. Durations in this file are plain integers; the "
            f"unit is carried by the key name."
        )

    if raw <= 0:
        raise KeyExpiryConfigurationError(
            f"{field}: {raw} is not a positive number of seconds. A key whose window closes "
            f"at or before it opens would expire the instant it was registered."
        )

    return timedelta(seconds=raw)


def _read_document(config_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    """Read and parse key-expiry.yaml, or raise a KeyExpiryConfigurationError saying why."""
    path = Path(config_dir) / KEY_EXPIRY_FILENAME

    try:
        with open(path, encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise KeyExpiryConfigurationError(
            f"Key expiry configuration not found at {path}. This file is GitOps-managed "
            f"and must be deployed with the application."
        ) from exc
    except yaml.YAMLError as exc:
        raise KeyExpiryConfigurationError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise KeyExpiryConfigurationError(
            f"{path} must contain a mapping, got {type(document).__name__}."
        )

    return path, document


def load_sweep_interval(config_dir: str | Path) -> timedelta:
    """How often the expiry sweep runs. Uncached — see get_sweep_interval.

    Required rather than defaulted: a sweep silently falling back to some built-in cadence
    is the same class of hidden constant as a built-in expiry window.
    """
    path, document = _read_document(config_dir)

    if SWEEP_INTERVAL_KEY not in document:
        raise KeyExpiryConfigurationError(
            f"{path} has no '{SWEEP_INTERVAL_KEY}'. The sweep cadence must be declared."
        )

    interval = parse_seconds(
        document[SWEEP_INTERVAL_KEY], field=f"{path.name}:{SWEEP_INTERVAL_KEY}"
    )
    if interval is None:
        raise KeyExpiryConfigurationError(
            f"{path}: '{SWEEP_INTERVAL_KEY}' must be a number of seconds, not null. A null cadence "
            f"would mean the sweep never runs, which is a decision for "
            f"IDEMPOTENCY_EXPIRY_SWEEP_ENABLED rather than for this file."
        )

    return interval


def load_key_expiry_windows(
    config_dir: str | Path,
) -> Mapping[IdempotencyKeyType, timedelta | None]:
    """Read key-expiry.yaml from ``config_dir``. Uncached — see get_key_expiry_windows.

    Every key type the platform defines must be present. A missing entry raises rather than
    defaulting: a key type that quietly defaults to "no expiry" is invisible until an audit
    asks why none of its records ever expired.
    """
    path, document = _read_document(config_dir)

    if KEY_EXPIRY_SECTION not in document:
        raise KeyExpiryConfigurationError(
            f"{path} has no '{KEY_EXPIRY_SECTION}' section."
        )

    section = document[KEY_EXPIRY_SECTION]
    if not isinstance(section, dict):
        raise KeyExpiryConfigurationError(
            f"{path}: '{KEY_EXPIRY_SECTION}' must be a mapping of key type to duration, "
            f"got {type(section).__name__}."
        )

    known = {key_name_for(member) for member in IdempotencyKeyType}

    unknown = sorted(set(section) - known)
    if unknown:
        raise KeyExpiryConfigurationError(
            f"{path}: unknown key(s) {unknown}. Expected exactly {sorted(known)}."
        )

    missing = sorted(known - set(section))
    if missing:
        raise KeyExpiryConfigurationError(
            f"{path}: no window configured for {missing}. Every key type must be listed "
            f"explicitly — write null for types that do not expire on a clock."
        )

    windows = {
        key_type: parse_seconds(
            section[key_name_for(key_type)],
            field=f"{path.name}:{KEY_EXPIRY_SECTION}.{key_name_for(key_type)}",
        )
        for key_type in IdempotencyKeyType
    }

    logger.info(
        "key_expiry_configuration_loaded",
        path=str(path),
        windows={k.value: (str(v) if v else None) for k, v in windows.items()},
    )

    return MappingProxyType(windows)


@lru_cache(maxsize=1)
def get_key_expiry_windows() -> Mapping[IdempotencyKeyType, timedelta | None]:
    """The configured windows, read once from the deployed configuration directory.

    IDEMPOTENCY_CONFIG_DIR overrides the location. It exists so tests and local runs can
    point at a fixture directory; the deployed path is the default and needs no setting.
    """
    return load_key_expiry_windows(settings.IDEMPOTENCY_CONFIG_DIR or CONFIG_DIR)


@lru_cache(maxsize=1)
def get_sweep_interval() -> timedelta:
    """The configured sweep cadence, read once from the deployed configuration directory."""
    return load_sweep_interval(settings.IDEMPOTENCY_CONFIG_DIR or CONFIG_DIR)


def reset_key_expiry_windows_cache() -> None:
    """Drop the cached configuration. For tests that swap the configuration directory."""
    get_key_expiry_windows.cache_clear()
    get_sweep_interval.cache_clear()


def expiry_window_for(key_type: IdempotencyKeyType) -> timedelta | None:
    """The configured window for a key type, or None when it does not expire on a clock."""
    return get_key_expiry_windows()[key_type]


def compute_expires_at(
    key_type: IdempotencyKeyType, first_seen_at: datetime
) -> datetime | None:
    """When a key registered at ``first_seen_at`` stops being claimed.

    Anchored on first_seen_at rather than the current time so the window a record carries is
    a property of when the key was first seen, and stays reproducible if the value is ever
    recomputed. Returns None for key types configured with no clock-based window, which
    leaves their expires_at NULL and keeps them out of the time-based sweep entirely.
    """
    window = expiry_window_for(key_type)
    if window is None:
        return None
    return first_seen_at + window
