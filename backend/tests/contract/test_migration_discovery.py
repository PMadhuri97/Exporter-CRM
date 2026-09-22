"""
Every module's migrations directory is registered with Alembic.

ARCHITECTURE.md §4 gives each domain ownership of its own schema
(`app/modules/<domain>/migrations/`) and makes top-level `migrations/` a runner. The
runner only runs what it is told about: a revision dropped into a directory that is not
listed in `alembic.ini`'s `version_locations` is **silently ignored** by
`alembic upgrade head`. Schema drift behind a green build. Five of the eleven module
migration directories were unlisted (VERIFICATION_REPORT.md, MED-4).

§4 describes `env.py` as discovering these directories. It cannot: Alembic resolves
`version_locations` in `ScriptDirectory.from_config()`, which runs before `env.py`, and
`alembic heads` / `history` / `current` never execute `env.py` at all. Globbing there
breaks head resolution outright. So the list stays explicit and this test is what makes
it complete — the same guarantee, enforced where it can be.
"""
from __future__ import annotations

import configparser
import pathlib
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULES_DIR = REPO_ROOT / "app" / "modules"
# authentication and messaging are first-class platform modules and own their
# migrations here rather than under app/modules or in the runner's versions/
# directory. They are subject to exactly the same registration guarantee.
PLATFORM_DIR = REPO_ROOT / "app" / "platform"


def _configured_locations() -> set[str]:
    cfg = configparser.ConfigParser()
    cfg.read(REPO_ROOT / "alembic.ini", encoding="utf-8")
    raw = cfg["alembic"]["version_locations"]
    return {p.strip().replace("\\", "/") for p in raw.split() if p.strip()}


def _migration_dirs_under(parent: pathlib.Path) -> set[str]:
    if not parent.is_dir():
        return set()
    return {
        (d / "migrations").relative_to(REPO_ROOT).as_posix()
        for d in parent.iterdir()
        if d.is_dir() and d.name != "__pycache__" and (d / "migrations").is_dir()
    }


def _module_migration_dirs() -> set[str]:
    return _migration_dirs_under(MODULES_DIR) | _migration_dirs_under(PLATFORM_DIR)


def test_every_module_migrations_dir_is_registered() -> None:
    unregistered = _module_migration_dirs() - _configured_locations()
    assert not unregistered, (
        f"these module migrations directories are not in alembic.ini version_locations: "
        f"{sorted(unregistered)}. Any revision placed in them is silently skipped by "
        f"'alembic upgrade head' — the schema drifts while the build stays green. "
        f"Register them."
    )


def test_no_configured_location_is_missing_from_disk() -> None:
    """A stale path is a typo waiting to hide a revision. Alembic skips it in silence."""
    missing = {
        loc for loc in _configured_locations()
        if not (REPO_ROOT / loc).is_dir()
    }
    assert not missing, (
        f"alembic.ini lists version_locations that do not exist on disk: "
        f"{sorted(missing)}. Alembic skips non-existent locations without complaining."
    )


def test_platform_runner_location_is_registered() -> None:
    assert "migrations/versions" in _configured_locations(), (
        "migrations/versions is not registered — the platform / cross-domain revisions "
        "would not be applied"
    )


def _script_directory() -> ScriptDirectory:
    """Resolve the revision graph. Reads scripts only — no database involved."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    raw_locs = cfg.get_main_option("version_locations")
    if raw_locs:
        abs_locs = " ".join(str(REPO_ROOT / loc) for loc in raw_locs.split())
        cfg.set_main_option("version_locations", abs_locs)
    return ScriptDirectory.from_config(cfg)


def test_the_revision_graph_has_exactly_one_head() -> None:
    """Two modules branching from one parent is a merge waiting to fail.

    ``alembic upgrade head`` refuses to run against multiple heads, so a fork
    does not degrade the schema — it stops every deployment and every
    integration test that builds a database from scratch. It is also invisible
    in ``git status``: two revisions in different module directories can each
    name the same ``down_revision`` and merge without a textual conflict, which
    is exactly how compliance_0002_sector_registry (AL-443) and
    rails_0001_baseline (AL-115) both came to sit on f3a1b2c3d4e5.

    Resolve a fork with a merge revision — never by re-parenting a revision that
    is already on develop, which may have been applied somewhere.
    """
    heads = _script_directory().get_heads()

    assert len(heads) == 1, (
        f"the migration graph has {len(heads)} heads: {sorted(heads)}. "
        f"'alembic upgrade head' cannot run. Join them with a merge revision "
        f"('alembic merge -m \"...\" <rev1> <rev2>')."
    )


#: ``alembic_version.version_num`` is VARCHAR(32). Alembic creates it at that
#: width and never widens it.
MAX_REVISION_ID_LENGTH = 32


def test_no_revision_id_exceeds_the_version_table_width() -> None:
    """A long revision id fails at the very end of an upgrade that worked.

    Every DDL statement in the migration applies, and then the stamp write into
    ``alembic_version`` raises StringDataRightTruncation and rolls the whole
    transaction back. The error names a varchar width and no table, so it reads
    as a defect in the migration's own columns rather than in its id, and the
    schema is left exactly as it was with nothing to show for the run.

    Descriptive module-scoped ids sit close to the limit — customers_0002_
    review_lifecycle is 31 characters — so this is a live constraint, not a
    theoretical one.
    """
    too_long = {
        script.revision: len(script.revision)
        for script in _script_directory().walk_revisions()
        if len(script.revision) > MAX_REVISION_ID_LENGTH
    }

    assert not too_long, (
        f"these revision ids exceed alembic_version.version_num's "
        f"VARCHAR({MAX_REVISION_ID_LENGTH}): {too_long}. Shorten them; the "
        f"upgrade applies every statement and then fails on the stamp."
    )
