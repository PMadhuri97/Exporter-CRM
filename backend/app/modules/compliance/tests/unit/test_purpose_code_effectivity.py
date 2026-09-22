"""Effectivity window policy — pure domain, no database.

The window is half-open: ``effective_from`` is inclusive, ``effective_to`` is
exclusive. Every date comparison in the purpose-code registry rests on this, so
the boundaries are asserted directly rather than inferred from a lookup result.
"""
from datetime import date

from app.modules.compliance.domain.policies.effectivity import is_effective_at


def test_before_effective_from_is_not_effective():
    assert not is_effective_at(date(2024, 1, 1), date(2025, 1, 1), date(2023, 12, 31))


def test_effective_from_is_inclusive():
    assert is_effective_at(date(2024, 1, 1), date(2025, 1, 1), date(2024, 1, 1))


def test_inside_the_window_is_effective():
    assert is_effective_at(date(2024, 1, 1), date(2025, 1, 1), date(2024, 6, 1))


def test_effective_to_is_exclusive():
    """The row is already retired on its own effective_to. This is what lets a
    replacement mapping start on exactly the date the old one ends without the
    two overlapping and tripping the ambiguity check."""
    assert not is_effective_at(date(2024, 1, 1), date(2025, 1, 1), date(2025, 1, 1))


def test_open_ended_window_never_expires():
    assert is_effective_at(date(2024, 1, 1), None, date(2030, 1, 1))
