"""Links a person typed, and the one rule for when a stored value may be shown as one.

Pure: no I/O. A value stored as a URL is later rendered to other staff as
``<a href>``, and React 18 renders a ``javascript:`` or ``data:`` href as written —
script run in the reader's session, where the refresh token lives. So only an
absolute ``http`` or ``https`` link with a host counts as a web link.

The rule was first written for a verification result's ``url`` evidence (Dev4B PR
audit, 28 Sep 2026). It lives here, outside any one owner's module, because the
company's ``website`` needs exactly the same rule and two copies would drift:

* ``domain/verification_evidence.py`` (Developer 4B) — ``url`` evidence references;
* ``application/exporter_profile_service.py`` (Developer 2) — the company website,
  on every path that writes it (manual create and edit, CSV import, RXIL intake).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.shared.exceptions import ValidationError

#: The only schemes a stored link may use (module docstring).
URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def is_web_link(value: str) -> bool:
    """An absolute http(s) link with a host. The stored value is checked as given:
    ``urlsplit``, like the browser that later renders it, ignores leading spaces and
    embedded tabs or newlines, so ``" javascript:…"`` and ``"java\\tscript:…"`` are
    seen as the ``javascript:`` URLs they are."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme.lower() in URL_SCHEMES and bool(parts.netloc)


def normalise_website(value: str | None) -> str | None:
    """A company website as stored: stripped, and ``None`` when blank.

    Raises:
        ValidationError: the value is not an absolute ``http``/``https`` link with a
            host — ``www.example.com`` included, since a browser would treat it as a
            path on this application rather than as another site.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if not is_web_link(cleaned):
        raise ValidationError(
            "website must be an absolute http:// or https:// link, for example "
            "https://www.example.com"
        )
    return cleaned


__all__ = ["URL_SCHEMES", "is_web_link", "normalise_website"]
