import json
import os

from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Fail fast at startup if required configuration variables are missing, or provide defaults
GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "dev-aner-project")
AUDIT_BUCKET_NAME: str = os.environ.get("AUDIT_BUCKET_NAME", "dev-audit-bucket")
LOG_SINK_LOGGER_NAME: str = os.environ.get("LOG_SINK_LOGGER_NAME", "posting-service-audit-sink")

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

SERVICE_ACCOUNT_EMAIL: str = _email or os.environ.get(
    "SERVICE_ACCOUNT_EMAIL", "dev-service-account@project.iam.gserviceaccount.com"
)

# Set GOOGLE_APPLICATION_CREDENTIALS for the GCP SDK if not already set,
# using the path from GCP_SERVICE_ACCOUNT_KEY.
if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and "GCP_SERVICE_ACCOUNT_KEY" in os.environ:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.environ["GCP_SERVICE_ACCOUNT_KEY"]

# The compliance retention period for audit logs (defaults to 7 years / 2555 days)
AUDIT_BUCKET_RETENTION_DAYS: int = int(os.environ.get("AUDIT_BUCKET_RETENTION_DAYS", "2555"))

# The retention period for Cloud Logging buckets (defaults to 30 days)
CLOUD_LOGGING_RETENTION_DAYS: int = int(os.environ.get("CLOUD_LOGGING_RETENTION_DAYS", "30"))

# ── AWS Audit & Storage Configuration ─────────────────────────────────────────
AWS_DEFAULT_REGION: str = (
    os.environ.get("AWS_DEFAULT_REGION")
    or os.environ.get("AWS_REGION")
    or "ap-south-1"
).strip()
AWS_REGION: str = AWS_DEFAULT_REGION
AWS_AUDIT_BUCKET_NAME: str = (
    os.environ.get("AWS_AUDIT_BUCKET_NAME")
    or os.environ.get("S3_DOCUMENT_BUCKET")
    or "aner-crm-documents"
).strip()
AWS_AUDIT_LOG_GROUP: str = os.environ.get(
    "AWS_AUDIT_LOG_GROUP", "/ecs/aner-crm-backend"
).strip()



