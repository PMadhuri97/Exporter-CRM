"""No unresolved merge conflict markers reach a commit.

A conflict marker in a Python file is a ``SyntaxError``, and a ``SyntaxError``
in a package's ``__init__.py`` takes the whole module down — every import of it,
every test that touches it, and the application at startup. That is not a
hypothetical: merging ``develop`` into feature/AL-444 left markers in
``compliance/domain/ports.py`` and ``compliance/__init__.py``, and the entire
compliance module stopped importing.

The failure is loud once anything runs, but it is easy to commit: ``git status``
reports the conflict, and a resolution that fixes one of several marked regions
looks finished. Scanning is cheap and catches it before review.

YAML, INI and Markdown are included as well. A marker in the GitOps seed data
would not raise a SyntaxError — it would either fail to parse at boot or, worse,
load a rule set nobody wrote.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Scanned extensions. Anything whose corruption is silent or fatal.
_SUFFIXES = {".py", ".yaml", ".yml", ".ini", ".toml", ".json", ".md", ".cfg", ".sql"}

#: Vendored and generated trees. Third-party sources legitimately contain lines
#: that look like markers -- pytest's ``_argcomplete`` has a ``=======``
#: docstring underline, and js-tokens' README has another.
_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
    "site-packages",
    "dist",
    "build",
}

#: Matched at the start of a line. ``=======`` is required to be exactly seven
#: characters so that a reStructuredText table border or a Markdown heading
#: underline -- both longer -- does not read as a conflict.
_MARKERS = ("<<<<<<< ", ">>>>>>> ")
_DIVIDER = "======="


def _candidate_files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for path in REPO_ROOT.rglob("*"):
        if path.suffix not in _SUFFIXES or not path.is_file():
            continue
        if _EXCLUDED_DIRS.intersection(path.parts):
            continue
        found.append(path)
    return found


def _conflicted_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # Not a text file we can judge; nothing to assert about it.
        return []

    hits: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(_MARKERS) or line.rstrip() == _DIVIDER:
            hits.append((number, line[:60]))
    return hits


def test_no_file_contains_an_unresolved_conflict_marker() -> None:
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): hits
        for path in _candidate_files()
        if (hits := _conflicted_lines(path))
    }

    assert not offenders, (
        "unresolved merge conflict markers found:\n"
        + "\n".join(
            f"  {name}: " + ", ".join(f"line {n} ({text!r})" for n, text in hits)
            for name, hits in sorted(offenders.items())
        )
    )


def test_the_scan_actually_reaches_source_files() -> None:
    """A guard that silently matches nothing protects nothing.

    If the exclusion list or the suffix set is ever widened past the point of
    usefulness, this fails rather than leaving the suite green over an empty
    scan.
    """
    scanned = _candidate_files()

    assert len(scanned) > 100, f"only {len(scanned)} files scanned — the filter is too narrow"
    assert any(
        p.as_posix().endswith("app/modules/compliance/__init__.py") for p in scanned
    ), "the compliance facade, which the original conflict broke, is not being scanned"
