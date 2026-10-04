"""The one rule for a stored link (``domain/web_links.py``), without a database.

``test_l4b_verification_integrity_rules.py`` covers the same rule applied to a
verification result's ``url`` evidence, which is its one caller since the company
website retired in R11 (decision IQ-16). ``test_company_website.py`` proves the
field is gone from every write path.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain.web_links import is_web_link

#: The first four run script in the reader's session; the last two are not
#: absolute http(s) links with a host, so a browser would not open another site.
REFUSED = [
    "javascript:alert(document.cookie)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "//evil.example",
    "www.example.com",
]

ALLOWED = [
    "https://acme.example/about",
    "http://acme.example",
    "https://acme.example:8443/a?b=c#d",
]


@pytest.mark.parametrize("value", REFUSED)
def test_the_rule_refuses_anything_but_an_http_link(value: str):
    assert not is_web_link(value)


@pytest.mark.parametrize("value", ALLOWED)
def test_the_rule_allows_an_absolute_http_link_with_a_host(value: str):
    assert is_web_link(value)


def test_surrounding_whitespace_is_ignored_the_way_a_browser_ignores_it():
    """``urlsplit`` strips surrounding whitespace, and so does the browser that
    would render the value, so this rule sees the same URL the reader's browser
    would. That is the point of checking with ``urlsplit`` rather than a regular
    expression, and it cuts both ways: it is why ``" javascript:alert(1)"`` in
    ``REFUSED`` is still recognised as the ``javascript:`` URL it is, instead of
    passing as some harmless string beginning with a space."""
    assert is_web_link("  https://acme.example  ")
    assert not is_web_link("  javascript:alert(1)  ")
