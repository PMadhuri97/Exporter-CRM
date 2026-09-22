"""The delivery layer reaches a module only through its facade.

ARCHITECTURE.md §2: a module's ``__init__.py`` is its only import surface and
everything else in it is private. ``importlinter.ini`` enforces that between
modules, but its privacy contracts list only ``app.modules.*`` as sources, so an
import from ``app.api`` into a module's internals passes CI unchecked. This test
covers that gap.

Two shapes are allowed:

  ``app.modules.<m>``            the facade.
  ``app.modules.<m>.api...``     a module's own router package, which the
                                 delivery layer mounts. That is what the router
                                 package exists for.

Anything deeper — ``application``, ``infrastructure``, ``domain``, ``workflows`` —
is a module internal.

A RATCHET, NOT A CLEAN SLATE. Imports that predated this test are enumerated in
``_KNOWN_VIOLATIONS`` rather than fixed here, the same way the module-cycle test
treats the known SCC: a new violation fails the build, and so does a listed one
that has since been fixed, so the list only ever shrinks. Imports inside
functions count — they are how these slipped past a line-anchored grep.
"""

from __future__ import annotations

import ast
import pathlib

APP_API = pathlib.Path(__file__).resolve().parents[2] / "app" / "api"

#: (file relative to app/api, imported module) pairs that predate this rule.
#: Remove an entry when its import moves to the owning module's facade.
_KNOWN_VIOLATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("rest/workflows.py", "app.modules.orchestration.application.models"),
        ("rest/workflows.py", "app.modules.orchestration.workflows.settlement_workflow"),
        ("rest/workflows.py", "app.modules.payments.infrastructure.repository"),
    }
)


def _module_internal_imports() -> set[tuple[str, str]]:
    """Every import from app/api into a module's internals, nested ones included."""
    found: set[tuple[str, str]] = set()
    for path in APP_API.rglob("*.py"):
        relative = path.relative_to(APP_API).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            parts = node.module.split(".")
            if parts[:2] != ["app", "modules"] or len(parts) <= 3:
                continue  # not a module, or the facade itself
            if parts[3] == "api":
                continue  # the module's own router package
            found.add((relative, node.module))
    return found


def test_the_scan_sees_the_delivery_layer() -> None:
    """Guards the assertions below from passing because nothing was scanned."""
    assert (APP_API / "rest" / "router.py").exists()
    assert list(APP_API.rglob("*.py")), f"no Python files found under {APP_API}"


def test_no_new_import_bypasses_a_module_facade() -> None:
    new = _module_internal_imports() - _KNOWN_VIOLATIONS
    assert not new, (
        "app/api imports a module's internals instead of its facade "
        f"(ARCHITECTURE.md §2): {sorted(new)}. Export the name from the module's "
        "__init__.py and import it from there."
    )


def test_fixed_violations_are_removed_from_the_ratchet() -> None:
    """A stale entry would let the same bypass come back without failing."""
    fixed = _KNOWN_VIOLATIONS - _module_internal_imports()
    assert not fixed, (
        f"these imports no longer bypass a facade — remove them from _KNOWN_VIOLATIONS: "
        f"{sorted(fixed)}"
    )
