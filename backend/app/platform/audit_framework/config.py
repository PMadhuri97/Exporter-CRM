import json
import os

from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Fail fast at startup if required configuration variables are missing
GCP_PROJECT_ID: str = os.environ["GCP_PROJECT_ID"]
AUDIT_BUCKET_NAME: str = os.environ["AUDIT_BUCKET_NAME"]
LOG_SINK_LOGGER_NAME: str = os.environ["LOG_SINK_LOGGER_NAME"]

# Try to resolve SERVICE_ACCOUNT_EMAIL from environment, or parse it from key JSON file if available
_email: str | None = os.environ.get("SERVICE_ACCOUNT_EMAIL")

if not _email:
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GCP_SERVICE_ACCOUNT_KEY")
    if key_path and os.path.exists(key_path):
        try:
            with open(key_path) as f:
                data = json.load(f)
                _email = data.get("client_email")
        except Exception:
            pass

# Fail fast if SERVICE_ACCOUNT_EMAIL cannot be resolved
if not _email:
    raise KeyError("SERVICE_ACCOUNT_EMAIL must be set in the environment or available in the GCP service account key file")

SERVICE_ACCOUNT_EMAIL: str = _email

# Set GOOGLE_APPLICATION_CREDENTIALS for the GCP SDK if not already set,
# using the path from GCP_SERVICE_ACCOUNT_KEY.
if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and "GCP_SERVICE_ACCOUNT_KEY" in os.environ:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.environ["GCP_SERVICE_ACCOUNT_KEY"]

# The compliance retention period for audit logs (defaults to 7 years / 2555 days)
AUDIT_BUCKET_RETENTION_DAYS: int = int(os.environ.get("AUDIT_BUCKET_RETENTION_DAYS", "2555"))

# The retention period for Cloud Logging buckets (defaults to 30 days)
CLOUD_LOGGING_RETENTION_DAYS: int = int(os.environ.get("CLOUD_LOGGING_RETENTION_DAYS", "30"))


