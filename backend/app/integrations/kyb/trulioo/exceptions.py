"""Trulioo adapter exceptions — Epic 4.1 / S2T2."""
from __future__ import annotations


class TruliooApiError(Exception):
    """Base exception for Trulioo API communication failures."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class TruliooRateLimitError(TruliooApiError):
    """Raised when the Trulioo API returns HTTP 429.

    ``retry_after_seconds`` carries the server-specified back-off when the
    ``Retry-After`` header is present; ``None`` otherwise.
    """

    def __init__(
        self, detail: str = "Trulioo rate limit exceeded", *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(detail, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class TruliooSchemaChangeError(TruliooApiError):
    """Raised when the Trulioo API response does not match the expected schema.

    This is logged as an operational alert so that the team can update the
    adapter mapping before it causes silent verification failures.
    """

    def __init__(self, detail: str = "Trulioo response schema mismatch") -> None:
        super().__init__(detail, status_code=None)
