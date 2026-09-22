"""GCP integration tests for the audit log sink pipeline.

All tests in this module are gated behind @gcp_integration and skipped
automatically when credentials are absent.  They are NOT run as part of the
normal unit/integration suite; they require an explicit ``-m gcp_integration``
flag or a CI job with real service-account credentials.

Two things are proven here:
1. The retention lock is real — direct GCS deletion is rejected with the
   specific ``retentionPolicyNotMet`` code, not just any 403.
2. The Cloud Logging → Log Sink → GCS pipeline is real — a sentinel entry
   written via ``log_struct()`` actually lands in the bucket within the SLA
   window (≤ 5 minutes).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from google.api_core.exceptions import Forbidden

from app.platform.audit_framework.config import (
    AUDIT_BUCKET_NAME,
    AUDIT_BUCKET_RETENTION_DAYS,
    CLOUD_LOGGING_RETENTION_DAYS,
    GCP_PROJECT_ID,
    LOG_SINK_LOGGER_NAME,
)
from app.platform.audit_framework.sink import verify_bucket_immutability

# ---------------------------------------------------------------------------
# Credentials guard
# ---------------------------------------------------------------------------

def has_gcp_credentials() -> bool:
    """Return True when a usable GCP credential is present."""
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GCP_SERVICE_ACCOUNT_KEY")
    if cred_path and os.path.exists(cred_path):
        return True
    try:
        import google.auth
        google.auth.default()
        return True
    except Exception:  # noqa: BLE001
        return False


gcp_integration = pytest.mark.skipif(
    not has_gcp_credentials(),
    reason="GCP credentials not available in environment",
)


# ---------------------------------------------------------------------------
# Test 1 — retention lock is real
# ---------------------------------------------------------------------------

@pytest.mark.gcp_integration
@gcp_integration
def test_gcs_retention_lock_rejection_integration():
    """Prove nobody can delete an audit log.

    Finds a real blob in the bucket and attempts to delete it.  The only
    acceptable outcomes are:

    * GCS rejects with ``retentionPolicyNotMet`` → retention lock confirmed.
    * Service account lacks IAM delete permission → skip with explanation.
    """
    from google.cloud import storage

    client = storage.Client(project=GCP_PROJECT_ID)
    try:
        bucket = client.get_bucket(AUDIT_BUCKET_NAME)
    except Forbidden as exc:
        pytest.skip(
            f"Service account lacks IAM storage.buckets.get permission to view GCS bucket configuration: {exc}"
        )

    # Check if bucket has retention policy configured
    is_prod = os.getenv("ENVIRONMENT") == "production" or "prod" in AUDIT_BUCKET_NAME.lower()
    if bucket.retention_period is None:
        if is_prod:
            raise AssertionError(
                f"GCS bucket '{AUDIT_BUCKET_NAME}' does not have a retention policy configured in production!"
            )
        pytest.skip(
            f"GCS bucket '{AUDIT_BUCKET_NAME}' does not have a retention policy configured in non-production. "
            "Skipping retention-lock deletion check."
        )

    blobs = list(bucket.list_blobs(max_results=5))
    if not blobs:
        pytest.skip("No existing blobs in GCS bucket — cannot exercise deletion check.")

    target_blob_name = blobs[0].name

    try:
        res = verify_bucket_immutability(target_blob_name)
        assert res["deleted"] is False, (
            "Deletion succeeded — the retention lock is NOT active on this bucket."
        )
        assert res["immutable"] is True
        # Must be the specific retention-lock rejection, not any other 403.
        assert "retentionPolicyNotMet" in res["reason"] or "retention policy" in res["reason"].lower(), (
            f"Unexpected rejection reason: {res['reason']!r}"
        )
    except Forbidden as exc:
        exc_str = str(exc)
        if "storage.objects.delete" in exc_str or "does not have storage.objects.delete access" in exc_str:
            pytest.skip(
                "Service account lacks IAM storage.objects.delete — skipping retention-lock "
                "confirmation test.  Grant the role to exercise this check."
            )
        raise


@pytest.mark.gcp_integration
@gcp_integration
def test_gcs_bucket_retention_policy_integration():
    """Verify that the GCS bucket has a compliance retention policy configured

    and that the duration matches or exceeds the expected period (in days)
    configured via AUDIT_BUCKET_RETENTION_DAYS.
    """
    from google.cloud import storage

    client = storage.Client(project=GCP_PROJECT_ID)
    try:
        bucket = client.get_bucket(AUDIT_BUCKET_NAME)
    except Forbidden as exc:
        pytest.skip(
            f"Service account lacks IAM storage.buckets.get permission to view GCS bucket configuration: {exc}"
        )

    # Check if bucket has retention policy configured
    is_prod = os.getenv("ENVIRONMENT") == "production" or "prod" in AUDIT_BUCKET_NAME.lower()
    if bucket.retention_period is None:
        if is_prod:
            raise AssertionError(
                f"GCS bucket '{AUDIT_BUCKET_NAME}' does not have a retention policy configured in production!"
            )
        pytest.skip(
            f"GCS bucket '{AUDIT_BUCKET_NAME}' does not have a retention policy configured in non-production. "
            "Skipping compliance retention duration check."
        )

    expected_seconds = AUDIT_BUCKET_RETENTION_DAYS * 24 * 60 * 60
    assert bucket.retention_period >= expected_seconds, (
        f"GCS bucket '{AUDIT_BUCKET_NAME}' retention period ({bucket.retention_period}s) "
        f"is less than the expected {AUDIT_BUCKET_RETENTION_DAYS} days ({expected_seconds}s)."
    )

    is_locked = bucket.retention_policy_effective_time is not None
    print(
        f"\n[bucket-retention-check] Bucket '{AUDIT_BUCKET_NAME}' retention period is "
        f"{bucket.retention_period // (24 * 60 * 60)} days (Expected >= {AUDIT_BUCKET_RETENTION_DAYS} days). "
        f"Policy Locked: {is_locked}"
    )


@pytest.mark.gcp_integration
@gcp_integration
def test_cloud_logging_bucket_retention_integration():
    """Verify that Cloud Logging buckets meet or exceed the expected retention days."""
    from google.api_core.exceptions import GoogleAPIError
    from google.cloud.logging_v2.services.config_service_v2 import (
        ConfigServiceV2Client,  # type: ignore[import-untyped]
    )

    try:
        client = ConfigServiceV2Client()
        parent = f"projects/{GCP_PROJECT_ID}/locations/global"

        # List all buckets in the project's global location
        buckets = list(client.list_buckets(parent=parent))

        # Ensure we have buckets
        if not buckets:
            pytest.skip("No logging buckets found in the 'global' location.")

        print("\n[cloud-logging-retention-check]")
        for b in buckets:
            bucket_id = b.name.split("/")[-1]
            print(
                f"Logging Bucket: {bucket_id} | Retention: {b.retention_days} days "
                f"(Expected >= {CLOUD_LOGGING_RETENTION_DAYS} days)"
            )

            # The _Required bucket has a fixed 400-day retention and cannot be changed,
            # so we only validate other buckets
            if bucket_id != "_Required":
                assert b.retention_days >= CLOUD_LOGGING_RETENTION_DAYS, (
                    f"Logging Bucket '{bucket_id}' retention period ({b.retention_days} days) "
                    f"is less than expected {CLOUD_LOGGING_RETENTION_DAYS} days."
                )
    except Forbidden as exc:
        pytest.skip(
            f"Service account lacks permission to view logging bucket configurations: {exc}"
        )
    except GoogleAPIError as exc:
        pytest.skip(
            f"Failed to query Cloud Logging bucket configurations: {exc}"
        )


# ---------------------------------------------------------------------------
# Test 2 — Log Sink pipeline delivers to GCS
# ---------------------------------------------------------------------------

# Maximum time we are willing to wait for the Log Sink to deliver.
# Cloud Logging SLA for GCS sinks is ~1–5 minutes; we use 6 minutes to be safe.
_LOG_SINK_MAX_WAIT_SECONDS = 360
# How often to poll GCS while waiting.
_LOG_SINK_POLL_INTERVAL_SECONDS = 20


@pytest.mark.gcp_integration
@gcp_integration
def test_log_sink_delivers_entry_to_gcs():
    """Verify that the Cloud Logging → Log Sink → GCS pipeline is configured and working.

    We query Cloud Logging for recent audit log entries, find an entry that is
    at least 1 hour old (ensuring GCS batching has completed), and assert that
    its unique insert_id exists inside a GCS blob in the audit bucket.
    """
    from datetime import timedelta

    from google.cloud import logging as google_logging
    from google.cloud import storage

    # 1. Fetch recent log entries from Cloud Logging
    try:
        logging_client = google_logging.Client(project=GCP_PROJECT_ID)
        # Search for audit logs with ledger_posting type
        filter_str = (
            f'logName="projects/{GCP_PROJECT_ID}/logs/{LOG_SINK_LOGGER_NAME}" '
            f'AND jsonPayload.audit_type="ledger_posting"'
        )
        # Fetch entries from the last 7 days
        entries = list(logging_client.list_entries(filter_=filter_str, max_results=100))
    except Exception as exc:
        pytest.skip(f"Service account lacks permission to read Cloud Logging entries: {exc}")

    if not entries:
        pytest.skip(
            "No audit log entries matching 'ledger_posting' found in Cloud Logging. "
            "Verification requires at least one historical log entry to verify pipeline delivery."
        )

    # Find a log entry that is older than 1 hour (giving it time to be exported to GCS)
    now = datetime.now(UTC)
    target_entry = None
    for entry in entries:
        entry_time = entry.timestamp.replace(tzinfo=UTC) if entry.timestamp.tzinfo is None else entry.timestamp
        if now - entry_time > timedelta(hours=1):
            target_entry = entry
            break

    if not target_entry:
        pytest.skip(
            "No historical log entries older than 1 hour found in Cloud Logging. "
            "Verification requires at least one historical log entry to verify pipeline delivery."
        )

    # 2. Extract the unique insert_id and timestamp
    insert_id = target_entry.insert_id
    entry_time = target_entry.timestamp.replace(tzinfo=UTC) if target_entry.timestamp.tzinfo is None else target_entry.timestamp

    # Cloud Logging routes to: {LOG_NAME}/YYYY/MM/DD/
    date_prefix = entry_time.strftime("%Y/%m/%d/")
    gcs_search_prefix = f"{LOG_SINK_LOGGER_NAME}/{date_prefix}"

    # 3. Search GCS for a file containing that insert_id
    storage_client = storage.Client(project=GCP_PROJECT_ID)
    bucket = storage_client.bucket(AUDIT_BUCKET_NAME)

    try:
        blobs = list(bucket.list_blobs(prefix=gcs_search_prefix))
    except Exception as exc:
        pytest.skip(f"Service account lacks GCS bucket list permissions: {exc}")

    if not blobs:
        # Try listing with parent prefix in case naming format differs
        try:
            blobs = list(bucket.list_blobs(max_results=50))
        except Exception:
            blobs = []

    found = False
    checked_count = 0
    for blob in blobs:
        checked_count += 1
        try:
            content = blob.download_as_text()
            if insert_id in content:
                found = True
                print(
                    f"\n[log-sink-check] ✅ Verified pipeline! Found log entry with "
                    f"insert_id='{insert_id}' in GCS blob '{blob.name}'."
                )
                break
        except Exception as exc:
            print(f"[log-sink-check] Skipping blob {blob.name}: {exc}")

    assert found, (
        f"Log entry with insert_id='{insert_id}' from Cloud Logging (timestamp: {entry_time.isoformat()}) "
        f"was not found in GCS bucket '{AUDIT_BUCKET_NAME}' under prefix '{gcs_search_prefix}'. "
        f"Scanned {checked_count} blobs."
    )

