"""Load the GitOps-managed document-type settings — **owner: Developer 3B**
(L3-09).

Architecture §3.4: categories are fixed and server-checked, **types are settings**
— a new type needs no code change and no migration. This is the file I/O for that
vocabulary, kept out of the domain the same way
``document_requirements_loader.py`` keeps it out of
``document_requirements_service.py``.

Read once and cached: the file is GitOps-managed, so it changes on deploy, not
during a request. ``reset_cache`` exists for tests that write their own file.
"""

from __future__ import annotations

import functools
from pathlib import Path

import structlog
import yaml  # type: ignore[import-untyped]

from app.modules.onboarding.config import DEFAULT_DOCUMENT_TYPES_PATH
from app.modules.onboarding.domain.entities.document_enums import DocumentCategory

logger = structlog.get_logger(__name__)


class DocumentTypeConfigurationError(RuntimeError):
    """The document-type settings are missing, unreadable or malformed.

    A startup-shaped failure, not a request-shaped one: a deployment whose type
    vocabulary will not parse should be loud, and every upload would otherwise
    fail one at a time with a confusing 422.
    """


@functools.lru_cache(maxsize=1)
def load_document_types(
    config_path: Path | str | None = None,
) -> dict[DocumentCategory, tuple[tuple[str, str], ...]]:
    """``{category: ((key, label), ...)}`` for every category in the file.

    Raises:
        DocumentTypeConfigurationError: the file is missing, is not valid YAML,
            does not parse to a mapping, names a category that is not one of the
            ten, or gives an entry without a key.
    """
    path = Path(config_path) if config_path else DEFAULT_DOCUMENT_TYPES_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DocumentTypeConfigurationError(
            f"document-type settings not found at {path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise DocumentTypeConfigurationError(
            f"document-type settings at {path} are not valid YAML"
        ) from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("categories"), dict):
        raise DocumentTypeConfigurationError(
            f"document-type settings at {path} need a top-level `categories` mapping"
        )

    types: dict[DocumentCategory, tuple[tuple[str, str], ...]] = {}
    for name, entries in raw["categories"].items():
        try:
            category = DocumentCategory(name)
        except ValueError as exc:
            # A category is a rule about which owner it may be filed against, so an
            # unknown one cannot be honoured by settings alone.
            raise DocumentTypeConfigurationError(
                f"{name!r} in {path} is not one of the ten document categories"
            ) from exc
        parsed: list[tuple[str, str]] = []
        for entry in entries or ():
            if not isinstance(entry, dict) or not entry.get("key"):
                raise DocumentTypeConfigurationError(
                    f"every document type under {name} in {path} needs a `key`"
                )
            key = str(entry["key"]).strip()
            parsed.append((key, str(entry.get("label") or key)))
        types[category] = tuple(parsed)

    logger.info(
        "document_types.loaded",
        path=str(path),
        category_count=len(types),
        type_count=sum(len(v) for v in types.values()),
    )
    return types


def reset_cache() -> None:
    """Forget the cached settings. For tests that point at their own file."""
    load_document_types.cache_clear()


def types_for(category: DocumentCategory) -> tuple[tuple[str, str], ...]:
    """The (key, label) pairs configured for one category — empty if none are."""
    return load_document_types().get(category, ())


def is_valid_type(category: DocumentCategory, document_type: str) -> bool:
    """Whether ``document_type`` is configured under ``category``.

    A type from a *different* category is not valid here: filing a bill of lading
    under `ENTITY_KYC` would put it where nobody looks for it.
    """
    return any(key == document_type for key, _ in types_for(category))


__all__ = [
    "DocumentTypeConfigurationError",
    "is_valid_type",
    "load_document_types",
    "reset_cache",
    "types_for",
]
