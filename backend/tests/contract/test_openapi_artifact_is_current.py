"""The committed frontend API contract matches the backend that serves it.

`frontend/openapi.json` and `frontend/src/lib/api/schema.ts` are generated from
this application and **are checked in**, so a fresh clone can type-check and
build the frontend without a Python environment. The cost of committing
generated output is that it can go stale; this test is what stops it.

It fails when someone changes a route, a schema or a response and does not run
`pnpm generate:api`. That failure is the point: without it the frontend would
keep compiling against an API that no longer exists, and the mismatch would
surface at runtime in a browser instead of in CI.

Lives in the backend suite because that is where a Python environment exists.
The frontend build never runs this and never needs to.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPO_ROOT / "frontend" / "openapi.json"
SCHEMA_TS_PATH = REPO_ROOT / "frontend" / "src" / "lib" / "api" / "schema.ts"

REGENERATE = "cd frontend && pnpm generate:api"


def _served_document() -> dict:
    from app.main import app

    return app.openapi()


def _committed_document() -> dict:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_the_generated_artifacts_are_committed():
    """A fresh clone must be able to build the frontend on its own.

    `src/lib/api/types.ts` imports `./schema`, so without these two files
    `tsc` fails before it reaches a single line of application code.
    """
    assert OPENAPI_PATH.is_file(), f"{OPENAPI_PATH} is missing — run `{REGENERATE}`"
    assert SCHEMA_TS_PATH.is_file(), f"{SCHEMA_TS_PATH} is missing — run `{REGENERATE}`"


def test_the_committed_openapi_matches_the_served_api():
    """The drift check.

    Compared as parsed JSON, not as text, so formatting differences between
    generators never produce a false failure — only a genuine difference in
    what the API offers does.
    """
    served = _served_document()
    committed = _committed_document()

    if served == committed:
        return

    served_ops = _operations(served)
    committed_ops = _operations(committed)
    added = sorted(served_ops - committed_ops)
    removed = sorted(committed_ops - served_ops)

    served_schemas = set(served.get("components", {}).get("schemas", {}))
    committed_schemas = set(committed.get("components", {}).get("schemas", {}))

    detail = []
    if added:
        detail.append("  routes the backend now serves, missing from the committed copy:")
        detail += [f"    + {m} {p}" for m, p in added]
    if removed:
        detail.append("  routes in the committed copy that the backend no longer serves:")
        detail += [f"    - {m} {p}" for m, p in removed]
    if served_schemas - committed_schemas:
        detail.append(f"  new schemas: {sorted(served_schemas - committed_schemas)}")
    if committed_schemas - served_schemas:
        detail.append(f"  removed schemas: {sorted(committed_schemas - served_schemas)}")
    if not detail:
        detail.append(
            "  the route and schema names match, so the difference is inside an "
            "operation or a schema body (a response, a description, a field)."
        )

    pytest.fail(
        "frontend/openapi.json is out of date with the API this backend serves.\n"
        + "\n".join(detail)
        + f"\n\n  Regenerate it and the TypeScript types:  {REGENERATE}"
    )


def test_the_typescript_schema_covers_every_component():
    """Catches regenerating the JSON but not the types.

    `pnpm generate:api` runs both steps, but the two are separate scripts and
    can be run apart. Checking that every schema name in the committed document
    appears in `schema.ts` is a content check rather than a timestamp one —
    git does not preserve mtimes, so a freshness comparison would be
    meaningless in a clone.
    """
    schema_source = SCHEMA_TS_PATH.read_text(encoding="utf-8")
    names = set(_committed_document().get("components", {}).get("schemas", {}))

    missing = sorted(name for name in names if name not in schema_source)
    assert not missing, (
        "frontend/src/lib/api/schema.ts does not mention these schemas from "
        f"frontend/openapi.json: {missing}\n"
        f"  The two artifacts are out of step. Regenerate both:  {REGENERATE}"
    )


def _operations(document: dict) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in document.get("paths", {}).items()
        for method in operations
        if method in ("get", "post", "put", "patch", "delete")
    }
