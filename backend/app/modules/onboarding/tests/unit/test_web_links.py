"""The one rule for a stored link (``domain/web_links.py``), without a database.

The integration suite (``test_company_website.py``) proves every write path of the
company website applies it; ``test_l4b_verification_integrity_rules.py`` covers the
same rule on a verification result's ``url`` evidence.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain.web_links import is_web_link, normalise_website
from app.shared.exceptions import ValidationError

#: The first three run script in the reader's session; the last two are not
#: absolute http(s) links with a host, so a browser would not open another site.
REFUSED = [
    "javascript:alert(document.cookie)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "//evil.example",
    "www.example.com",
]


@pytest.mark.parametrize("value", REFUSED)
def test_the_rule_refuses_anything_but_an_http_link(value: str):
    assert not is_web_link(value)
    with pytest.raises(ValidationError):
        normalise_website(value)


def test_the_rule_keeps_an_http_link_and_blanks_become_nothing():
    assert normalise_website("  https://acme.example/about ") == "https://acme.example/about"
    assert normalise_website("http://acme.example") == "http://acme.example"
    assert normalise_website("") is None
    assert normalise_website("   ") is None
    assert normalise_website(None) is None
