"""Idempotency metrics and instrumentation tests (S4T1).

Tests every metric defined by S4T1 and verifies that the helper functions
record observations correctly.  All tests are independent of the database
and use prometheus_client's in-process registry.

Acceptance criteria covered:
  AC-1: All seven metrics appear in Prometheus (TestMetricDefinitions)
  AC-3: Artificially injected duplicate → increment (TestDuplicateMetrics)
  AC-4: Artificially injected violation → increment (TestViolationMetrics)
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import REGISTRY

from app.platform.observability.metrics import (
    IDEMPOTENCY_ARCHIVAL_JOB_LAST_RUN,
    IDEMPOTENCY_DUPLICATES,
    IDEMPOTENCY_EXPIRY_JOB_LAST_RUN,
    IDEMPOTENCY_REGISTRATION_LATENCY,
    IDEMPOTENCY_REGISTRATIONS,
    IDEMPOTENCY_REGISTRY_SIZE,
    IDEMPOTENCY_VIOLATIONS,
    observe_idempotency_registration_latency,
    record_idempotency_duplicate,
    record_idempotency_registration,
    record_idempotency_violation,
)

# ── Metric definitions ──────────────────────────────────────────────────────


class TestMetricDefinitions:
    """AC-1: All seven S4T1 metrics must be registered with the Prometheus client."""

    def test_registrations_counter_exists(self) -> None:
        assert IDEMPOTENCY_REGISTRATIONS is not None
        assert IDEMPOTENCY_REGISTRATIONS._name == "aner_idempotency_registrations"

    def test_duplicates_counter_exists(self) -> None:
        assert IDEMPOTENCY_DUPLICATES is not None
        assert IDEMPOTENCY_DUPLICATES._name == "aner_idempotency_duplicates"

    def test_violations_counter_exists(self) -> None:
        assert IDEMPOTENCY_VIOLATIONS is not None
        assert IDEMPOTENCY_VIOLATIONS._name == "aner_idempotency_violations"

    def test_registration_latency_histogram_exists(self) -> None:
        assert IDEMPOTENCY_REGISTRATION_LATENCY is not None
        assert IDEMPOTENCY_REGISTRATION_LATENCY._name == "aner_idempotency_key_registration_latency_seconds"

    def test_registry_size_gauge_exists(self) -> None:
        assert IDEMPOTENCY_REGISTRY_SIZE is not None
        assert IDEMPOTENCY_REGISTRY_SIZE._name == "aner_idempotency_registry_size"

    def test_expiry_job_timestamp_gauge_exists(self) -> None:
        assert IDEMPOTENCY_EXPIRY_JOB_LAST_RUN is not None
        assert IDEMPOTENCY_EXPIRY_JOB_LAST_RUN._name == "aner_idempotency_expiry_job_last_run_timestamp"

    def test_archival_job_timestamp_gauge_exists(self) -> None:
        assert IDEMPOTENCY_ARCHIVAL_JOB_LAST_RUN is not None
        assert IDEMPOTENCY_ARCHIVAL_JOB_LAST_RUN._name == "aner_idempotency_archival_job_last_run_timestamp"

    def test_registrations_has_expected_labels(self) -> None:
        assert IDEMPOTENCY_REGISTRATIONS._labelnames == ("key_type", "operation_type")

    def test_duplicates_has_expected_labels(self) -> None:
        assert IDEMPOTENCY_DUPLICATES._labelnames == ("key_type", "operation_type", "duplicate_status")

    def test_registry_size_has_expected_labels(self) -> None:
        assert IDEMPOTENCY_REGISTRY_SIZE._labelnames == ("status",)


# ── Registration counter ────────────────────────────────────────────────────


class TestRegistrationMetrics:
    """record_idempotency_registration increments the counter."""

    def test_registration_increments_counter(self) -> None:
        labels = {"key_type": "customer_key", "operation_type": "POST /test-reg"}
        before = REGISTRY.get_sample_value(
            "aner_idempotency_registrations_total", labels,
        ) or 0.0

        record_idempotency_registration("customer_key", "POST /test-reg")

        after = REGISTRY.get_sample_value(
            "aner_idempotency_registrations_total", labels,
        )
        assert after == before + 1

    def test_registration_with_different_key_types(self) -> None:
        for key_type in ("customer_key", "internal_derived_key", "rail_reference"):
            labels = {"key_type": key_type, "operation_type": "POST /multi-type"}
            before = REGISTRY.get_sample_value(
                "aner_idempotency_registrations_total", labels,
            ) or 0.0

            record_idempotency_registration(key_type, "POST /multi-type")

            after = REGISTRY.get_sample_value(
                "aner_idempotency_registrations_total", labels,
            )
            assert after == before + 1


# ── Duplicate counter ───────────────────────────────────────────────────────


class TestDuplicateMetrics:
    """record_idempotency_duplicate increments the counter with status labels."""

    def test_duplicate_increments_counter(self) -> None:
        labels = {
            "key_type": "customer_key",
            "operation_type": "POST /test-dup",
            "duplicate_status": "active",
        }
        before = REGISTRY.get_sample_value(
            "aner_idempotency_duplicates_total", labels,
        ) or 0.0

        record_idempotency_duplicate("customer_key", "POST /test-dup", "active")

        after = REGISTRY.get_sample_value(
            "aner_idempotency_duplicates_total", labels,
        )
        assert after == before + 1

    def test_duplicate_with_all_statuses(self) -> None:
        """Every status label must be individually trackable."""
        for status in ("active", "completed", "failed", "expired"):
            labels = {
                "key_type": "customer_key",
                "operation_type": "POST /dup-status",
                "duplicate_status": status,
            }
            before = REGISTRY.get_sample_value(
                "aner_idempotency_duplicates_total", labels,
            ) or 0.0

            record_idempotency_duplicate("customer_key", "POST /dup-status", status)

            after = REGISTRY.get_sample_value(
                "aner_idempotency_duplicates_total", labels,
            )
            assert after == before + 1

    def test_artificially_injected_duplicate_increments(self) -> None:
        """AC-3: An artificially injected duplicate produces an increment."""
        labels = {
            "key_type": "customer_key",
            "operation_type": "POST /inject-dup",
            "duplicate_status": "completed",
        }
        before = REGISTRY.get_sample_value(
            "aner_idempotency_duplicates_total", labels,
        ) or 0.0

        # Simulate artificial injection — exactly what the acceptance criterion demands
        record_idempotency_duplicate("customer_key", "POST /inject-dup", "completed")

        after = REGISTRY.get_sample_value(
            "aner_idempotency_duplicates_total", labels,
        )
        assert after == before + 1, (
            "Artificially injected duplicate must produce exactly +1 increment"
        )


# ── Violation counter ───────────────────────────────────────────────────────


class TestViolationMetrics:
    """record_idempotency_violation increments the violations counter."""

    def test_violation_increments_counter(self) -> None:
        before = REGISTRY.get_sample_value(
            "aner_idempotency_violations_total",
        ) or 0.0

        record_idempotency_violation()

        after = REGISTRY.get_sample_value(
            "aner_idempotency_violations_total",
        )
        assert after == before + 1

    def test_artificially_injected_violation_increments(self) -> None:
        """AC-4: An artificially injected violation produces an increment."""
        before = REGISTRY.get_sample_value(
            "aner_idempotency_violations_total",
        ) or 0.0

        record_idempotency_violation()

        after = REGISTRY.get_sample_value(
            "aner_idempotency_violations_total",
        )
        assert after == before + 1, (
            "Artificially injected violation must produce exactly +1 increment"
        )


# ── Registration latency histogram ──────────────────────────────────────────


class TestLatencyMetrics:
    """observe_idempotency_registration_latency records histogram observations."""

    def test_latency_observation_recorded(self) -> None:
        before_count = REGISTRY.get_sample_value(
            "aner_idempotency_key_registration_latency_seconds_count",
        ) or 0.0

        observe_idempotency_registration_latency(0.015)

        after_count = REGISTRY.get_sample_value(
            "aner_idempotency_key_registration_latency_seconds_count",
        )
        assert after_count == before_count + 1

    def test_latency_sum_increases(self) -> None:
        before_sum = REGISTRY.get_sample_value(
            "aner_idempotency_key_registration_latency_seconds_sum",
        ) or 0.0

        observe_idempotency_registration_latency(0.042)

        after_sum = REGISTRY.get_sample_value(
            "aner_idempotency_key_registration_latency_seconds_sum",
        ) or 0.0
        assert after_sum >= before_sum + 0.042

    def test_latency_histogram_buckets_tuned_for_db(self) -> None:
        """Verify fine-grained buckets tuned for DB operations (1ms–1s)."""
        expected_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
        assert IDEMPOTENCY_REGISTRATION_LATENCY._upper_bounds == [
            *expected_buckets, float("inf"),
        ]


# ── Registry size gauge ─────────────────────────────────────────────────────


class TestRegistrySizeMetrics:
    """The registry size gauge can be set per status."""

    def test_gauge_can_be_set(self) -> None:
        IDEMPOTENCY_REGISTRY_SIZE.labels(status="active").set(42)
        value = REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "active"},
        )
        assert value == 42

    def test_gauge_per_status(self) -> None:
        for status, count in [("active", 10), ("completed", 50), ("failed", 3), ("expired", 7)]:
            IDEMPOTENCY_REGISTRY_SIZE.labels(status=status).set(count)

        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "active"},
        ) == 10
        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "completed"},
        ) == 50
        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "failed"},
        ) == 3
        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "expired"},
        ) == 7


# ── Job timestamp gauges ────────────────────────────────────────────────────


class TestJobTimestampMetrics:
    """Job last-run gauges record Unix timestamps."""

    def test_archival_timestamp_can_be_set(self) -> None:
        now = time.time()
        IDEMPOTENCY_ARCHIVAL_JOB_LAST_RUN.set(now)
        value = REGISTRY.get_sample_value(
            "aner_idempotency_archival_job_last_run_timestamp",
        )
        assert value == now

    def test_expiry_timestamp_can_be_set(self) -> None:
        now = time.time()
        IDEMPOTENCY_EXPIRY_JOB_LAST_RUN.set(now)
        value = REGISTRY.get_sample_value(
            "aner_idempotency_expiry_job_last_run_timestamp",
        )
        assert value == now

    @pytest.mark.asyncio
    async def test_expiry_sweep_task_sets_metric_on_success(self) -> None:
        """After a successful expiry sweep the last-run gauge must be updated."""
        # Reset the gauge so we can detect a change.
        IDEMPOTENCY_EXPIRY_JOB_LAST_RUN.set(0)

        mock_service = MagicMock()
        mock_service.run_expiry_sweep = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch(
                "app.platform.idempotency.tasks.AsyncSessionLocal",
            ) as mock_session_local,
            patch(
                "app.platform.idempotency.tasks.IdempotencyExpiryService",
                return_value=mock_service,
            ),
        ):
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.platform.idempotency.tasks import run_idempotency_expiry_sweep_task

            await run_idempotency_expiry_sweep_task()

        value = REGISTRY.get_sample_value(
            "aner_idempotency_expiry_job_last_run_timestamp",
        )
        assert value is not None
        assert value > 0, "Metric must be set to a positive timestamp after success"

    @pytest.mark.asyncio
    async def test_expiry_sweep_task_does_not_set_metric_on_failure(self) -> None:
        """When the sweep raises, the last-run gauge must NOT be updated."""
        sentinel = 12345.0
        IDEMPOTENCY_EXPIRY_JOB_LAST_RUN.set(sentinel)

        mock_service = MagicMock()
        mock_service.run_expiry_sweep = AsyncMock(side_effect=RuntimeError("db exploded"))

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch(
                "app.platform.idempotency.tasks.AsyncSessionLocal",
            ) as mock_session_local,
            patch(
                "app.platform.idempotency.tasks.IdempotencyExpiryService",
                return_value=mock_service,
            ),
        ):
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.platform.idempotency.tasks import run_idempotency_expiry_sweep_task

            with pytest.raises(RuntimeError, match="db exploded"):
                await run_idempotency_expiry_sweep_task()

        value = REGISTRY.get_sample_value(
            "aner_idempotency_expiry_job_last_run_timestamp",
        )
        assert value == sentinel, (
            "Metric must remain unchanged when the sweep fails"
        )


# ── Best-effort safety ──────────────────────────────────────────────────────


class TestBestEffortSafety:
    """Instrumentation must never break business operations."""

    def test_registration_swallows_errors(self) -> None:
        with patch.object(IDEMPOTENCY_REGISTRATIONS, "labels", side_effect=RuntimeError("boom")):
            record_idempotency_registration("customer_key", "POST /err")

    def test_duplicate_swallows_errors(self) -> None:
        with patch.object(IDEMPOTENCY_DUPLICATES, "labels", side_effect=RuntimeError("boom")):
            record_idempotency_duplicate("customer_key", "POST /err", "active")

    def test_violation_swallows_errors(self) -> None:
        with patch.object(IDEMPOTENCY_VIOLATIONS, "inc", side_effect=RuntimeError("boom")):
            record_idempotency_violation()

    def test_latency_swallows_errors(self) -> None:
        with patch.object(IDEMPOTENCY_REGISTRATION_LATENCY, "observe", side_effect=RuntimeError("boom")):
            observe_idempotency_registration_latency(0.01)


# ── collect_registry_size_metrics ────────────────────────────────────────────


class TestCollectRegistrySizeMetrics:
    """collect_registry_size_metrics queries the DB and updates the gauge."""

    @pytest.mark.asyncio
    async def test_updates_gauge_from_db_counts(self) -> None:
        """Mocked DB returns counts; gauge is updated per status."""
        from app.platform.idempotency.models import IdempotencyStatus

        mock_rows = [
            (IdempotencyStatus.ACTIVE, 15),
            (IdempotencyStatus.COMPLETED, 200),
            (IdempotencyStatus.FAILED, 2),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.platform.idempotency.services.AsyncSessionLocal",
            return_value=mock_session,
        ):
            from app.platform.idempotency.services import collect_registry_size_metrics
            await collect_registry_size_metrics()

        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "active"},
        ) == 15
        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "completed"},
        ) == 200
        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "failed"},
        ) == 2
        # 'expired' not in mock_rows → must be reset to 0
        assert REGISTRY.get_sample_value(
            "aner_idempotency_registry_size", {"status": "expired"},
        ) == 0

    @pytest.mark.asyncio
    async def test_collection_error_does_not_raise(self) -> None:
        """Best-effort: DB errors are swallowed."""
        with patch(
            "app.platform.idempotency.services.AsyncSessionLocal",
            side_effect=RuntimeError("db down"),
        ):
            from app.platform.idempotency.services import collect_registry_size_metrics
            # Must not raise
            await collect_registry_size_metrics()
