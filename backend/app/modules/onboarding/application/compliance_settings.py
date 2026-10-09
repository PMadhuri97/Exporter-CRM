"""The compliance engine's settings, read at call time.

Three settings in ``platform.configuration.Settings``:

* ``CRM_BACKGROUND_CHECK_MAKER_CHECKER`` — whether a ``CLEAR``, ``FLAGGED`` or
  ``ON_HOLD`` needs a second person. **On by default.** Decided
  1 October 2026: "always on; a switch may turn it off only in
  local/test; the server refuses 'off' elsewhere". :func:`enforce_compliance_settings`
  runs at start-up and refuses to start the application with it off in any other
  environment.
* ``CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS`` — how long a new ``CLEAR`` stays
  current (default 365 days). Each ``CLEAR`` stores its own
  ``expires_at``, so a change applies to Clears recorded after it, never to existing
  ones.
* ``CRM_REKYC_DUE_WINDOW_DAYS`` — how far ahead "Re-KYC due" looks (default 30).

And the service levels of compliance work (configurable; the defaults are the brief's
targets): ``CRM_SLA_REVIEW`` (1 business day), ``CRM_SLA_APPROVAL`` (4 business hours),
``CRM_SLA_INFO`` (1 business day), ``CRM_SLA_DUE_SOON_PERCENT`` (75), measured in the
calendar ``CRM_BUSINESS_HOURS`` / ``CRM_BUSINESS_TIMEZONE`` / ``CRM_HOLIDAYS``
(``domain/business_time.py``). Computed on read; there is no scheduler.

Read on every call, not at import, so a test can ``monkeypatch.setattr(settings, …)``
and the next call sees it.
"""

from __future__ import annotations

from datetime import timedelta

from app.modules.onboarding.domain.approval_mode import (
    APPROVAL_OFF_ALLOWED_ENVIRONMENTS,
    ApprovalMode,
    parse_approval_mode,
)
from app.modules.onboarding.domain.business_time import (
    BusinessCalendar,
    parse_duration,
    parse_hours,
)
from app.modules.onboarding.domain.sanctions import (
    TrueMatchApproval,
    parse_true_match_approval,
)
from app.platform.configuration.config import Settings, settings

#: Where maker-checker may be switched off ("local/test", taken literally).
#: ``development`` is deliberately absent: it is ``Settings.ENVIRONMENT``'s default and
#: what ``.env.example`` — and so the docker-compose stack a UAT runs on — sets, so
#: allowing it would leave the start-up guard inert on any server nobody remembered to
#: rename. A developer who wants the switch off sets ``ENVIRONMENT=local``.
MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test", "testing"})


def _settings(override: Settings | None) -> Settings:
    return override if override is not None else settings


def maker_checker_enabled(override: Settings | None = None) -> bool:
    """Whether CLEAR, FLAGGED and ON_HOLD need a second approver right now."""
    return bool(_settings(override).CRM_BACKGROUND_CHECK_MAKER_CHECKER)


def clear_validity(override: Settings | None = None) -> timedelta:
    """How long a new CLEAR stays current.

    Raises:
        ValueError: the setting is below one day — a Clear that is never current would
            refuse every promotion and handover without saying why.
    """
    days = int(_settings(override).CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS)
    if days < 1:
        raise ValueError(
            f"CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS must be at least 1, not {days}"
        )
    return timedelta(days=days)


def rekyc_due_window(override: Settings | None = None) -> timedelta:
    """How far ahead of its expiry a Clear counts as "Re-KYC due"."""
    days = int(_settings(override).CRM_REKYC_DUE_WINDOW_DAYS)
    if days < 0:
        raise ValueError(f"CRM_REKYC_DUE_WINDOW_DAYS must be at least 0, not {days}")
    return timedelta(days=days)


def business_calendar(override: Settings | None = None) -> BusinessCalendar:
    """The working calendar every service level is measured in.

    Raises:
        ValueError: unreadable hours, time zone or holidays.
    """
    current = _settings(override)
    return parse_hours(
        current.CRM_BUSINESS_HOURS, current.CRM_BUSINESS_TIMEZONE, current.CRM_HOLIDAYS
    )


def sla_review(override: Settings | None = None) -> timedelta:
    """Business time a reviewer has, from assignment (paused during an information
    request)."""
    return parse_duration(_settings(override).CRM_SLA_REVIEW, business_calendar(override))


def sla_approval(override: Settings | None = None) -> timedelta:
    """Business time a proposal may wait for its checker."""
    return parse_duration(_settings(override).CRM_SLA_APPROVAL, business_calendar(override))


def sla_info(override: Settings | None = None) -> timedelta:
    """Business time an information request may wait for its answer."""
    return parse_duration(_settings(override).CRM_SLA_INFO, business_calendar(override))


def due_soon_fraction(override: Settings | None = None) -> float:
    """The share of an allowance after which an item is "due soon"."""
    percent = int(_settings(override).CRM_SLA_DUE_SOON_PERCENT)
    if not 1 <= percent <= 99:
        raise ValueError(f"CRM_SLA_DUE_SOON_PERCENT must be 1–99, not {percent}")
    return percent / 100


def bank_change_approval_mode(override: Settings | None = None) -> ApprovalMode:
    """Who approves a bank-account proposal (``CRM_BANK_CHANGE_APPROVAL_MODE``)."""
    return parse_approval_mode(
        _settings(override).CRM_BANK_CHANGE_APPROVAL_MODE,
        setting="CRM_BANK_CHANGE_APPROVAL_MODE",
    )


def true_match_approval(override: Settings | None = None) -> TrueMatchApproval:
    """Who confirms a sanctions true match (``CRM_SANCTIONS_TRUE_MATCH_APPROVAL``)."""
    return parse_true_match_approval(_settings(override).CRM_SANCTIONS_TRUE_MATCH_APPROVAL)


def enforce_compliance_settings(override: Settings | None = None) -> None:
    """Refuse to start with settings the compliance rules forbid.

    Called from the application's start-up (``app/main.py``). Raising there aborts the
    start, which is the point: a UAT or production server that would let one person
    clear a company must not serve a single request.

    Raises:
        RuntimeError: maker-checker is off outside local/test, or a
            duration setting is out of range.
    """
    current = _settings(override)
    environment = current.ENVIRONMENT.strip().lower()
    if (
        not maker_checker_enabled(current)
        and environment not in MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS
    ):
        raise RuntimeError(
            "CRM_BACKGROUND_CHECK_MAKER_CHECKER is off in the "
            f"{current.ENVIRONMENT!r} environment. It may be turned off only in "
            f"{', '.join(sorted(MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS))}: every "
            "other environment requires a second approver for CLEAR, FLAGGED and ON_HOLD."
        )
    try:
        if (
            bank_change_approval_mode(current) is ApprovalMode.OFF
            and environment not in APPROVAL_OFF_ALLOWED_ENVIRONMENTS
        ):
            raise ValueError(
                "CRM_BANK_CHANGE_APPROVAL_MODE is OFF in the "
                f"{current.ENVIRONMENT!r} environment; bank-detail changes need an "
                "approver everywhere but local and test."
            )
        if (
            true_match_approval(current) is TrueMatchApproval.SINGLE
            and environment not in APPROVAL_OFF_ALLOWED_ENVIRONMENTS
        ):
            raise ValueError(
                "CRM_SANCTIONS_TRUE_MATCH_APPROVAL is SINGLE in the "
                f"{current.ENVIRONMENT!r} environment; a true match needs a second "
                "officer everywhere but local and test."
            )
        clear_validity(current)
        rekyc_due_window(current)
        sla_review(current)
        sla_approval(current)
        sla_info(current)
        due_soon_fraction(current)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


__all__ = [
    "MAKER_CHECKER_OFF_ALLOWED_ENVIRONMENTS",
    "bank_change_approval_mode",
    "true_match_approval",
    "business_calendar",
    "clear_validity",
    "due_soon_fraction",
    "enforce_compliance_settings",
    "maker_checker_enabled",
    "rekyc_due_window",
    "sla_approval",
    "sla_info",
    "sla_review",
]
