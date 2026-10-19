"""Security settings checked once at start-up.

:func:`enforce_security_settings` runs in the application's lifespan, beside
``enforce_compliance_settings``, and follows the same rule: a setting that would leave
the server open to anyone stops it from starting, outside local and test, rather than
being logged and ignored.
"""

from __future__ import annotations

import structlog

from app.platform.configuration.config import Settings, get_settings

logger = structlog.get_logger(__name__)

#: The checked-in default. Public, so a server signing with it accepts a token anyone
#: can mint for any user id.
DEFAULT_JWT_SECRET_KEY = Settings.model_fields["JWT_SECRET_KEY"].default
#: HS256 is only as strong as its key; RFC 7518 §3.2 asks for at least 256 bits.
MIN_JWT_SECRET_LENGTH = 32


class InsecureConfigurationError(RuntimeError):
    """A setting that would leave the server open; raised before it serves anything."""


def jwt_secret_problem(secret: str) -> str | None:
    """Why ``secret`` must not sign tokens, or ``None`` when it may."""
    if not secret or secret == DEFAULT_JWT_SECRET_KEY:
        return "is unset, so the public default from config.py is in force"
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        return f"is shorter than {MIN_JWT_SECRET_LENGTH} characters"
    return None


def enforce_security_settings(settings: Settings | None = None) -> None:
    """Refuse to start with a forgeable JWT key outside local and test.

    Raises:
        InsecureConfigurationError: JWT_SECRET_KEY is the default or too short, and
            ENVIRONMENT is not local or test.
    """
    settings = settings or get_settings()

    problem = jwt_secret_problem(settings.JWT_SECRET_KEY)
    if problem is not None:
        if not settings.is_local_or_test:
            raise InsecureConfigurationError(
                f"JWT_SECRET_KEY {problem}. Anyone who knows the key can sign a token "
                f"for any user. Set a random value of at least {MIN_JWT_SECRET_LENGTH} "
                "characters in the environment (for example "
                "`python -c \"import secrets;print(secrets.token_urlsafe(48))\"`). "
                f"ENVIRONMENT is {settings.ENVIRONMENT!r}; only local and test may run "
                "without one."
            )
        logger.warning("security.jwt_secret_insecure", reason=problem, environment=settings.ENVIRONMENT)

    if settings.CRM_DOCUMENT_SCANNER.strip().lower() == "pass-through" and not settings.is_local_or_test:
        # Not fatal: refusing to start would take document upload down on every
        # deployment that has no scanner yet. Loud instead, and the scanner's name is
        # stored on every document so the gap stays visible.
        logger.error(
            "security.document_scanner_pass_through",
            environment=settings.ENVIRONMENT,
            detail=(
                "Uploaded documents are not checked for malware. Run a clamd daemon and "
                "set CRM_DOCUMENT_SCANNER=clamav."
            ),
        )
