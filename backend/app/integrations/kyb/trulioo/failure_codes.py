"""Trulioo failure-code translation table — Epic 4.1 / S2T2.

Maps Trulioo-specific ``Record.RecordStatus`` and ``DatasourceField.Status``
values to the platform's ``NormalisedResult`` enum.  Every vendor adapter must
ship with this mapping per the KYB interface specification v1.0 §3.

When the adapter encounters a Trulioo result code that is **not** in this table
it falls back to ``REQUIRES_MANUAL_REVIEW`` and logs an operational alert so
the team can update the mapping before it causes silent verification failures.

Reference: Trulioo GlobalGateway API — Record-level and field-level statuses.
"""
from __future__ import annotations

from app.shared.enums.kyb import NormalisedResult

# ── Record-level status mapping ──────────────────────────────────────────────
#
# RecordStatus is the overall outcome of a verification record returned by the
# Trulioo API.  These are the documented values as of the adapter's initial
# implementation.

RECORD_STATUS_MAP: dict[str, NormalisedResult] = {
    # All data sources confirmed the entity.
    "match": NormalisedResult.VERIFIED,
    # At least one data source returned a definitive non-match.
    "nomatch": NormalisedResult.REJECTED,
    # The entity could not be found in any authoritative registry.
    "missing": NormalisedResult.NOT_FOUND,
    # A data source encountered an internal error; manual triage required.
    "datasourceerror": NormalisedResult.REQUIRES_MANUAL_REVIEW,
}

# ── Field-level status mapping ───────────────────────────────────────────────
#
# Individual fields inside a DatasourceResult carry their own Status.
# These are used when translating per-field outcomes into discrepancies.

FIELD_STATUS_MAP: dict[str, NormalisedResult] = {
    "match": NormalisedResult.VERIFIED,
    "nomatch": NormalisedResult.REJECTED,
    "missing": NormalisedResult.NOT_FOUND,
    "datasourceerror": NormalisedResult.REQUIRES_MANUAL_REVIEW,
}


def translate_record_status(record_status: str) -> NormalisedResult:
    """Map a Trulioo ``RecordStatus`` to a ``NormalisedResult``.

    Unknown codes are mapped to ``REQUIRES_MANUAL_REVIEW`` — the caller is
    responsible for logging the operational alert.
    """
    return RECORD_STATUS_MAP.get(
        record_status.lower().strip(),
        NormalisedResult.REQUIRES_MANUAL_REVIEW,
    )


def translate_field_status(field_status: str) -> NormalisedResult:
    """Map a Trulioo field-level ``Status`` to a ``NormalisedResult``.

    Unknown codes fall back to ``REQUIRES_MANUAL_REVIEW``.
    """
    return FIELD_STATUS_MAP.get(
        field_status.lower().strip(),
        NormalisedResult.REQUIRES_MANUAL_REVIEW,
    )


def is_known_record_status(record_status: str) -> bool:
    """Return ``True`` if *record_status* is a recognised Trulioo status code."""
    return record_status.lower().strip() in RECORD_STATUS_MAP


def is_known_field_status(field_status: str) -> bool:
    """Return ``True`` if *field_status* is a recognised Trulioo field status."""
    return field_status.lower().strip() in FIELD_STATUS_MAP
