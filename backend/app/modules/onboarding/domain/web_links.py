"""Links a person typed, and the one rule for when a stored value may be shown as one.

Pure: no I/O. A value stored as a URL is later rendered to other staff as
``<a href>``, and React 18 renders a ``javascript:`` or ``data:`` href as written —
script run in the reader's session, where the refresh token lives. So only an
absolute ``http`` or ``https`` link with a host counts as a web link.

The rule was first written for a verification result's ``url`` evidence (28 Sep
2026), and was shared with the company's ``website`` so the two
would not drift. The website field is retired, so today the only
caller is ``domain/verification_evidence.py`` — ``url`` evidence
references. The rule stays here rather than moving into that module: it is a
property of a stored link, not of verification, and the next feature that
renders staff-entered text as an ``<a href>`` needs it unchanged.

``normalise_website`` went with the field. Nothing stores a website any more, so
there is no normaliser for one; the column and its values are left untouched.
"""

from __future__ import annotations

from urllib.parse import urlsplit

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


__all__ = ["URL_SCHEMES", "is_web_link"]
