"""When two company names are the same company.

Pure: no I/O. Used by ``CompanyDirectoryService.match`` to answer
``POSSIBLE_DUPLICATE``, which is the only answer in the matcher that rests on a
name rather than on an identifier.

Why not trigram similarity
--------------------------
The plan proposes ``pg_trgm`` and records its availability as UNKNOWN / NEEDS
VERIFICATION, with the fallback being "normalised-name equality plus legal-suffix
stripping". This module is that fallback, and it is deliberate rather than
temporary. A similarity *score* needs a threshold, and a threshold on company
names is a bad trade in both directions: loose enough to catch "Rotterdam Trading"
against "Rotterdam Trading BV" also catches "Gupta Exports" against "Gupta
Imports", which are different companies with the same family name — and the person
reading the result cannot tell which kind of near-match they are being shown.

Equality after normalisation says something a person can check: *these two names
differ only in punctuation, spacing, case, or the legal form at the end*. That is
a claim worth putting in front of someone. "These names are 0.83 similar" is not.

``POSSIBLE_DUPLICATE`` is never acted on automatically, so the cost of
missing a near-duplicate is that a person compares two companies; the cost of a
false one is that a deal is attached to the wrong company. The asymmetry is the
argument for the stricter rule.

What normalising does
---------------------
Case folded, punctuation and extra spacing removed, and a trailing legal form
dropped — ``Pvt Ltd``, ``BV``, ``GmbH`` and the rest. The suffix comes off only at
the **end** of the name, and only when something is left: ``Limited Stationers``
keeps its first word, and a company actually called ``BV`` is left alone.
"""

from __future__ import annotations

import re

#: Legal forms, as single normalised tokens, stripped from the end of a name.
#: Multi-word forms are listed as the tokens they normalise to (``PVT LTD`` →
#: ``PVT``, ``LTD``), and removal repeats, so ``Pvt. Ltd.`` comes off in two
#: passes. Chosen for the markets this CRM actually sees — India and the
#: countries its exporters sell into — rather than attempting to be exhaustive;
#: an unlisted form simply means two names must match including it, which is the
#: safe direction.
LEGAL_SUFFIXES: frozenset[str] = frozenset(
    {
        # India
        "PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "PLC", "COMPANY", "CO",
        # Europe
        "BV", "NV", "GMBH", "AG", "SA", "SARL", "SAS", "SRL", "SPA", "AB", "AS",
        "OY", "APS", "KG", "OHG", "UG", "SE", "LDA",
        # English-speaking and Gulf
        "INC", "INCORPORATED", "CORP", "CORPORATION", "LLC", "LC", "PC",
        "FZE", "FZCO", "DMCC", "WLL", "PJSC", "PSC",
        # Asia-Pacific
        "PTE", "SDN", "BHD", "PT", "TBK", "KK", "YK",
    }
)

_PUNCTUATION = re.compile(r"[^0-9A-Za-z]+")


def _tokens(name: str) -> list[str]:
    """The name's words, upper-cased.

    Full stops are **deleted** rather than treated as separators, because in a
    company name a full stop marks an abbreviation: ``B.V.`` is one token, ``BV``,
    and splitting on it would give ``B`` and ``V`` — so the legal form would never
    be recognised and ``Rotterdam Trading B.V.`` would not match ``Rotterdam
    Trading BV``, which is the case this whole module exists for. Spaces still
    separate, so ``Pvt. Ltd.`` is two tokens.
    """
    return [token for token in _PUNCTUATION.split(name.upper().replace(".", "")) if token]


def normalise_company_name(name: str | None) -> str:
    """A company name reduced to what it has in common with the same company
    written differently: upper case, single-spaced, no punctuation.

    ``""`` for a name that has no letters or digits at all, which never matches
    anything — an empty normalised form must not make two nameless rows equal.
    """
    return " ".join(_tokens(name or ""))


def strip_legal_suffix(name: str | None) -> str:
    """The normalised name with any trailing legal form removed, repeatedly.

    Stops while one token remains, so a company whose whole name is a legal form
    keeps it, and ``Limited Stationers`` is untouched because ``Limited`` is not
    at the end.
    """
    tokens = _tokens(name or "")
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_key(name: str | None) -> str:
    """The form two names are compared by: normalised, legal form stripped.

    This is the whole similarity rule. Two companies in the same country whose
    names share a ``name_key`` are a ``POSSIBLE_DUPLICATE``; anything else is not
    a name match at all.
    """
    return strip_legal_suffix(name)


def looks_like_the_same_company(left: str | None, right: str | None) -> bool:
    """Whether two names differ only in case, punctuation, spacing or legal form.

    ``False`` when either name is empty after normalising: two companies with no
    usable name are not evidence of anything.
    """
    key = name_key(left)
    return bool(key) and key == name_key(right)


__all__ = [
    "LEGAL_SUFFIXES",
    "looks_like_the_same_company",
    "name_key",
    "normalise_company_name",
    "strip_legal_suffix",
]
