"""The GitOps key-expiry configuration: parsing, validation, and the no-hardcoding rule.

These are unit tests — no database. What they pin is that the window is *data*: it comes
from a file, every key type must be declared, a malformed duration is fatal rather than
guessed at, and no expiry literal survives anywhere in the capability's application code.
"""

import pathlib
import re
import tokenize
from datetime import datetime, timedelta

import pytest
import yaml

from app.platform.configuration.config import settings
from app.platform.idempotency.config import (
    CONFIG_DIR,
    KEY_EXPIRY_FILENAME,
    compute_expires_at,
    expiry_window_for,
    get_key_expiry_windows,
    get_sweep_interval,
    key_name_for,
    load_key_expiry_windows,
    load_sweep_interval,
    parse_seconds,
    reset_key_expiry_windows_cache,
)
from app.platform.idempotency.exceptions import KeyExpiryConfigurationError
from app.platform.idempotency.models import IdempotencyKeyType

CAPABILITY_DIR = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """The loader caches deliberately; tests that swap directories must not leak into each other."""
    reset_key_expiry_windows_cache()
    yield
    reset_key_expiry_windows_cache()


def _write_config(directory: pathlib.Path, body: str) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / KEY_EXPIRY_FILENAME).write_text(body, encoding="utf-8")
    return directory


# ── The deployed configuration ────────────────────────────────────────────────────────


def test_deployed_configuration_file_exists():
    """The application refuses to start without it, so its absence should fail loudly here."""
    assert (CONFIG_DIR / KEY_EXPIRY_FILENAME).is_file(), (
        f"expected GitOps configuration at {CONFIG_DIR / KEY_EXPIRY_FILENAME}"
    )


def test_deployed_configuration_sets_customer_key_to_24_hours():
    """The current business requirement, asserted against the deployed file."""
    windows = load_key_expiry_windows(CONFIG_DIR)
    assert windows[IdempotencyKeyType.CUSTOMER_KEY] == timedelta(hours=24)


@pytest.mark.parametrize(
    "key_type",
    [IdempotencyKeyType.INTERNAL_DERIVED_KEY, IdempotencyKeyType.RAIL_REFERENCE],
)
def test_deployed_configuration_gives_idk_and_rr_no_clock_window(key_type):
    """IDK and RR are lifecycle-expired by S3T2, never by time."""
    assert load_key_expiry_windows(CONFIG_DIR)[key_type] is None


def test_every_known_key_type_is_configured():
    """A key type missing from the file must not silently become 'never expires'."""
    windows = load_key_expiry_windows(CONFIG_DIR)
    assert set(windows) == set(IdempotencyKeyType)


# ── Seconds parsing ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (90, timedelta(seconds=90)),
        (300, timedelta(minutes=5)),
        (1800, timedelta(minutes=30)),
        (86400, timedelta(hours=24)),
        (172800, timedelta(hours=48)),
        (604800, timedelta(days=7)),
    ],
)
def test_parse_seconds_accepts_whole_seconds(raw, expected):
    assert parse_seconds(raw, field="test") == expected


def test_parse_seconds_treats_null_as_no_clock_window():
    assert parse_seconds(None, field="test") is None


@pytest.mark.parametrize("raw", ["86400", "24h", "", "5m", [], {}, 1.5])
def test_parse_seconds_rejects_anything_that_is_not_an_integer(raw):
    """A string is rejected even when it would parse.

    '86400' and '24h' both mean somebody is writing this file to a different convention
    than it declares, and accepting either is how two conventions end up coexisting.
    """
    with pytest.raises(KeyExpiryConfigurationError):
        parse_seconds(raw, field="test")


def test_parse_seconds_rejects_a_boolean():
    """bool is an int subclass; `customer_key_seconds: true` must not become 1 second."""
    with pytest.raises(KeyExpiryConfigurationError, match="bool"):
        parse_seconds(True, field="test")


@pytest.mark.parametrize("raw", [0, -1, -86400])
def test_parse_seconds_rejects_a_non_positive_window(raw):
    """A zero or negative window expires a key the instant it is registered."""
    with pytest.raises(KeyExpiryConfigurationError, match="not a positive"):
        parse_seconds(raw, field="test")


def test_parse_seconds_error_names_the_offending_field():
    with pytest.raises(KeyExpiryConfigurationError, match="key_expiry.customer_key_seconds"):
        parse_seconds("nope", field="key-expiry.yaml:key_expiry.customer_key_seconds")


def test_key_names_carry_the_seconds_suffix():
    """The unit lives in the key name, which is what makes a bare integer unambiguous."""
    assert key_name_for(IdempotencyKeyType.CUSTOMER_KEY) == "customer_key_seconds"
    assert all(
        key_name_for(member).endswith("_seconds") for member in IdempotencyKeyType
    )


# ── Loader validation ─────────────────────────────────────────────────────────────────


def test_missing_file_raises_a_named_error(tmp_path):
    with pytest.raises(KeyExpiryConfigurationError, match="not found"):
        load_key_expiry_windows(tmp_path)


def test_missing_section_raises(tmp_path):
    _write_config(tmp_path, "something_else:\n  customer_key_seconds: 86400\n")
    with pytest.raises(KeyExpiryConfigurationError, match="key_expiry"):
        load_key_expiry_windows(tmp_path)


def test_missing_key_type_raises_rather_than_defaulting(tmp_path):
    """The whole point: no implicit default, because an implicit default is a hidden constant."""
    _write_config(tmp_path, "key_expiry:\n  customer_key_seconds: 86400\n")
    with pytest.raises(KeyExpiryConfigurationError, match="no window configured"):
        load_key_expiry_windows(tmp_path)


def test_unknown_key_type_raises(tmp_path):
    """A typo must fail at load, not disarm a window that looks configured."""
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 86400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n"
        "  custmoer_key: 1h\n",
    )
    with pytest.raises(KeyExpiryConfigurationError, match="unknown key"):
        load_key_expiry_windows(tmp_path)


def test_malformed_yaml_raises(tmp_path):
    _write_config(tmp_path, "key_expiry:\n  customer_key: [unclosed\n")
    with pytest.raises(KeyExpiryConfigurationError, match="not valid YAML"):
        load_key_expiry_windows(tmp_path)


# ── Configuration drives behaviour ────────────────────────────────────────────────────


def test_a_different_configured_window_changes_the_computed_expiry(tmp_path, monkeypatch):
    """Same code, different file, different window — requirement 3 in one assertion."""
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 3600\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n",
    )
    monkeypatch.setattr(settings, "IDEMPOTENCY_CONFIG_DIR", str(tmp_path))
    reset_key_expiry_windows_cache()

    assert expiry_window_for(IdempotencyKeyType.CUSTOMER_KEY) == timedelta(hours=1)

    first_seen = datetime(2026, 1, 1, 12, 0, 0)
    assert compute_expires_at(IdempotencyKeyType.CUSTOMER_KEY, first_seen) == datetime(
        2026, 1, 1, 13, 0, 0
    )


def test_compute_expires_at_is_anchored_on_first_seen_at(tmp_path, monkeypatch):
    """Never 'now' — an old first_seen_at must yield an old expires_at."""
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 86400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n",
    )
    monkeypatch.setattr(settings, "IDEMPOTENCY_CONFIG_DIR", str(tmp_path))
    reset_key_expiry_windows_cache()

    long_ago = datetime(2020, 3, 1, 8, 30, 0)
    assert compute_expires_at(IdempotencyKeyType.CUSTOMER_KEY, long_ago) == datetime(
        2020, 3, 2, 8, 30, 0
    )


@pytest.mark.parametrize(
    "key_type",
    [IdempotencyKeyType.INTERNAL_DERIVED_KEY, IdempotencyKeyType.RAIL_REFERENCE],
)
def test_compute_expires_at_returns_none_for_non_clock_key_types(key_type):
    assert compute_expires_at(key_type, datetime(2026, 1, 1)) is None


def test_windows_are_cached_and_the_cache_can_be_reset(tmp_path, monkeypatch):
    """Cached because it is deployment-time data; resettable because tests swap it."""
    assert get_key_expiry_windows() is get_key_expiry_windows()

    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 10800\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n",
    )
    monkeypatch.setattr(settings, "IDEMPOTENCY_CONFIG_DIR", str(tmp_path))

    assert get_key_expiry_windows()[IdempotencyKeyType.CUSTOMER_KEY] == timedelta(hours=24)

    reset_key_expiry_windows_cache()
    assert get_key_expiry_windows()[IdempotencyKeyType.CUSTOMER_KEY] == timedelta(hours=3)


def test_returned_mapping_is_read_only():
    """A caller mutating the cache would change the window for every later registration."""
    with pytest.raises(TypeError):
        get_key_expiry_windows()[IdempotencyKeyType.CUSTOMER_KEY] = timedelta(hours=99)


# ── No hardcoded expiry survives ──────────────────────────────────────────────────────

#: timedelta built from a literal amount, e.g. timedelta(hours=24). config.py builds its
#: windows from the parsed file (timedelta(**{unit: int(amount)})), so it does not match.
_LITERAL_DURATION = re.compile(
    r"timedelta\(\s*(?:hours|days|minutes|seconds|weeks)\s*=\s*\d"
)

#: Seconds-in-a-day and friends, the other way an expiry gets written down.
_MAGIC_SECONDS = re.compile(r"\b(?:86400|3600\s*\*\s*24|1440)\b")


def _code_only(path: pathlib.Path) -> str:
    """Source with comments and string literals removed.

    The scans below are about executable code. Documentation is allowed — and required —
    to say "24h" while explaining the format, and matching prose would make these tests
    fail for writing a good docstring rather than for hardcoding a window.
    """
    kept: list[str] = []
    with tokenize.open(path) as handle:
        for token in tokenize.generate_tokens(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def _capability_modules():
    """Application modules of the capability: no tests, no migrations.

    Migrations are excluded deliberately. idem_0001 carries a literal INTERVAL '24 hours'
    to backfill pre-S3T1 rows, which is a historical record of the window in force when it
    ran — a migration that read live configuration would produce different data on replay.
    """
    for path in sorted(CAPABILITY_DIR.rglob("*.py")):
        parts = set(path.relative_to(CAPABILITY_DIR).parts)
        if parts & {"tests", "migrations", "__pycache__"}:
            continue
        yield path


def test_no_literal_duration_in_capability_code():
    """Requirement: a hardcoded 24h anywhere in application logic is a defect."""
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in _capability_modules()
        for match in _LITERAL_DURATION.finditer(_code_only(path))
    ]
    assert not offenders, (
        f"literal expiry duration(s) found in the idempotency capability: {offenders}. "
        f"The window must come from key-expiry.yaml."
    )


def test_no_magic_second_counts_in_capability_code():
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in _capability_modules()
        for match in _MAGIC_SECONDS.finditer(_code_only(path))
    ]
    assert not offenders, f"magic duration constant(s) found: {offenders}"


def test_registration_service_never_names_a_duration():
    """services.py is where an expiry default would most plausibly be reintroduced."""
    source = _code_only(CAPABILITY_DIR / "services.py")
    assert "timedelta" not in source, (
        "services.py must not construct durations — it delegates to config.compute_expires_at"
    )


def test_config_module_declares_no_default_window():
    """The loader must have no fallback: a default IS a hardcoded expiry, just quieter.

    The values checked are the ones currently deployed, read from the file rather than
    restated, so this keeps testing the real thing if the window is ever reconfigured.
    """
    source = _code_only(CAPABILITY_DIR / "config.py")
    assert not _LITERAL_DURATION.search(source)

    deployed = yaml.safe_load((CONFIG_DIR / KEY_EXPIRY_FILENAME).read_text(encoding="utf-8"))
    values = {
        deployed["key_expiry"][key_name_for(IdempotencyKeyType.CUSTOMER_KEY)],
        deployed["sweep_interval_seconds"],
    }

    for value in values:
        assert str(value) not in source, (
            f"config.py names {value}, which is a deployed configuration value — "
            f"the file is where it belongs, not the loader"
        )


# ── Sweep cadence ─────────────────────────────────────────────────────────────────────


def test_deployed_configuration_sets_a_five_minute_sweep_interval():
    """S3T1 requires the sweep to run every 5 minutes."""
    assert load_sweep_interval(CONFIG_DIR) == timedelta(minutes=5)


def test_sweep_interval_is_required(tmp_path):
    """No built-in cadence — the same hidden-constant problem as a default window."""
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 86400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n",
    )
    with pytest.raises(KeyExpiryConfigurationError, match="sweep_interval"):
        load_sweep_interval(tmp_path)


def test_null_sweep_interval_is_rejected(tmp_path):
    """Turning the sweep off is a deployment flag, not a null in the data file."""
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 86400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n"
        "sweep_interval_seconds: null\n",
    )
    with pytest.raises(KeyExpiryConfigurationError, match="must be a number of seconds, not null"):
        load_sweep_interval(tmp_path)


def test_sweep_interval_uses_the_same_duration_grammar(tmp_path):
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 86400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n"
        "sweep_interval_seconds: 90\n",
    )
    assert load_sweep_interval(tmp_path) == timedelta(seconds=90)


def test_a_reconfigured_sweep_interval_is_picked_up(tmp_path, monkeypatch):
    """Changing the cadence is a file change, not a code change."""
    _write_config(
        tmp_path,
        "key_expiry:\n"
        "  customer_key_seconds: 86400\n"
        "  internal_derived_key_seconds: null\n"
        "  rail_reference_seconds: null\n"
        "sweep_interval_seconds: 120\n",
    )
    monkeypatch.setattr(settings, "IDEMPOTENCY_CONFIG_DIR", str(tmp_path))
    reset_key_expiry_windows_cache()

    assert get_sweep_interval() == timedelta(minutes=2)
