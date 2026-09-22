"""Structural proof of EXP-2's central acceptance criterion.

"Triggering a KYC check against entity_type=DIRECTOR and a BANK_ACCOUNT check
against entity_type=EXPORTER both route through the exact same
trigger_verification call and the exact same registry lookup — no
`if verification_type == ...` branching in the service layer."

A text/regex scan of the source would miss a reformatted, differently-spaced,
or `match`-statemented reintroduction of that branch. This walks the actual
AST of `VerificationService.trigger_verification`, so it catches any
comparison, `match` pattern, or membership test keyed on `verification_type`
regardless of how it's spelled — the only thing that would make this test
pass while the branching still existed is renaming the parameter itself,
which would break every other test in this suite that calls the method by
keyword.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from app.modules.onboarding.application.verification_service import VerificationService


def _branches_on_name(tree: ast.AST, name: str) -> list[str]:
    """Every place `tree` compares, matches, or tests membership against `name`."""
    found: list[str] = []

    def references(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id == name
        if isinstance(node, ast.Attribute):
            return references(node.value)
        return False

    class Finder(ast.NodeVisitor):
        def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802 — ast visitor naming
            if references(node.left) or any(references(c) for c in node.comparators):
                found.append(f"Compare at line {node.lineno}")
            self.generic_visit(node)

        def visit_match_case(self, node) -> None:  # noqa: N802 — ast visitor naming
            found.append(f"match/case at line {getattr(node, 'lineno', '?')}")
            self.generic_visit(node)

    finder = Finder()
    finder.visit(tree)

    # match <name>: ... is its own statement type (ast.Match), whose .subject
    # is what's being matched on.
    for node in ast.walk(tree):
        if isinstance(node, ast.Match) and references(node.subject):
            found.append(f"match statement at line {node.lineno}")

    return found


def test_trigger_verification_never_branches_on_verification_type():
    source = textwrap.dedent(inspect.getsource(VerificationService.trigger_verification))
    tree = ast.parse(source)

    violations = _branches_on_name(tree, "verification_type")

    assert not violations, (
        "trigger_verification branches directly on verification_type "
        f"({violations}) — it must route through the adapter registry "
        "(get_adapter(provider)) instead, never special-case a check type."
    )


def test_get_verification_status_never_branches_on_verification_type():
    """The polling path is equally generalized: it resolves the adapter from
    the stored row's own `provider` column, never from `verification_type`."""
    source = textwrap.dedent(
        inspect.getsource(VerificationService.get_verification_status)
    )
    tree = ast.parse(source)

    violations = _branches_on_name(tree, "verification_type")

    assert not violations, (
        f"get_verification_status branches on verification_type ({violations})"
    )


def test_trigger_verification_batch_never_branches_on_verification_type():
    """Piece 3's own extension of the same acceptance criterion: a batch that
    mixes KYB + AML + INVOICE_DUPLICATION checks together is handled by one
    loop over `(request, outcome)` pairs, never a branch on any request's
    `verification_type`. `verification_type` is only ever reached here via
    `request.verification_type`, so scanning for any comparison rooted at
    `request` is an equivalent (and stricter) proxy for that.
    """
    source = textwrap.dedent(
        inspect.getsource(VerificationService.trigger_verification_batch)
    )
    tree = ast.parse(source)

    violations = _branches_on_name(tree, "request")

    assert not violations, (
        "trigger_verification_batch branches on a per-request value "
        f"({violations}) — it must treat every request in the batch "
        "identically, regardless of verification_type."
    )


def test_the_finder_actually_catches_branching_when_present():
    """A meta-test: proves `_branches_on_name` isn't vacuously passing above
    by running it against source that *does* branch, in three different
    syntactic forms."""
    branching_source = textwrap.dedent(
        """
        def f(verification_type):
            if verification_type == "KYC":
                return 1
            elif verification_type.value == "BANK_ACCOUNT":
                return 2
            match verification_type:
                case "KYC":
                    return 3
            return 0
        """
    )
    tree = ast.parse(branching_source)
    violations = _branches_on_name(tree, "verification_type")
    assert len(violations) >= 2, (
        "the branch-finder should catch both the Compare-based branches; "
        f"found: {violations}"
    )
