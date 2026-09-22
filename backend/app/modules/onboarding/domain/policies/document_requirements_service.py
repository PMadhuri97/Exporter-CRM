"""Document Requirements Policy & Service.

Evaluates customer onboarding document requirements based on GitOps-managed configuration.
Checks profile requirements, conditional document triggers, and document validity/expiration.

This module is pure: the service receives an already-parsed configuration mapping and
never touches the filesystem. Reading and locating the YAML is the responsibility of
``app.modules.onboarding.infrastructure.document_requirements_loader``.
"""

from datetime import date, datetime
from typing import Any

from app.modules.onboarding.exceptions import DocumentRequirementsConfigurationError

#: Context fields a conditional rule is permitted to test. A rule naming anything
#: else is a configuration error rather than a rule that silently never fires.
_RULE_CONTEXT_FIELDS = frozenset(
    {
        "entity_type",
        "registration_country",
        "sector_code",
        "corridor_intent",
        "declared_monthly_volume_usd",
    }
)

#: Operators ``_evaluate_rule`` knows how to apply.
_RULE_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq", "in"})

#: Profile keys used for matching. Each is optional; an absent field is a
#: deliberate wildcard. A *typo'd* field, however, must not be silently ignored.
_PROFILE_MATCH_FIELDS = frozenset(
    {"entity_type", "registration_country", "sector_code", "corridor_intent"}
)
_PROFILE_REQUIRED_FIELDS = frozenset({"profile_id", "required_documents"})
_PROFILE_ALLOWED_FIELDS = _PROFILE_REQUIRED_FIELDS | _PROFILE_MATCH_FIELDS

_RULE_REQUIRED_FIELDS = frozenset(
    {"rule_id", "field", "operator", "value", "additional_documents"}
)
_RULE_OPTIONAL_FIELDS = frozenset({"description"})
_RULE_ALLOWED_FIELDS = _RULE_REQUIRED_FIELDS | _RULE_OPTIONAL_FIELDS


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


class DocumentRequirementsService:
    """Service to evaluate document requirements for onboarding requests.

    Construction takes an already-parsed configuration mapping (see the module
    docstring) and validates its structure eagerly: a malformed profile or
    conditional rule raises :class:`DocumentRequirementsConfigurationError` rather
    than being silently treated as a wildcard match.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = self._validate_config(config)

    # ── validation ───────────────────────────────────────────────────────────

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Check the parsed configuration structure, raising on any malformation."""
        if not isinstance(config, dict):
            raise DocumentRequirementsConfigurationError(
                "Invalid document requirements configuration: expected a mapping, "
                f"got {type(config).__name__}"
            )

        profiles = config.get("profiles", [])
        if not isinstance(profiles, list):
            raise DocumentRequirementsConfigurationError(
                "Invalid document requirements configuration: 'profiles' must be a list"
            )
        for index, profile in enumerate(profiles):
            self._validate_profile(profile, index)

        conditional_rules = config.get("conditional_rules", [])
        if not isinstance(conditional_rules, list):
            raise DocumentRequirementsConfigurationError(
                "Invalid document requirements configuration: 'conditional_rules' "
                "must be a list"
            )
        for index, rule in enumerate(conditional_rules):
            self._validate_rule_config(rule, index)

        validity_periods = config.get("validity_periods", {})
        if not isinstance(validity_periods, dict):
            raise DocumentRequirementsConfigurationError(
                "Invalid document requirements configuration: 'validity_periods' "
                "must be a mapping"
            )

        return config

    def _validate_profile(self, profile: Any, index: int) -> None:
        where = f"profiles[{index}]"
        if not isinstance(profile, dict):
            raise DocumentRequirementsConfigurationError(
                f"{where}: expected a mapping, got {type(profile).__name__}"
            )

        keys = set(profile)
        missing = _PROFILE_REQUIRED_FIELDS - keys
        if missing:
            raise DocumentRequirementsConfigurationError(
                f"{where}: missing required key(s) {sorted(missing)}"
            )
        unknown = keys - _PROFILE_ALLOWED_FIELDS
        if unknown:
            raise DocumentRequirementsConfigurationError(
                f"{where}: unknown key(s) {sorted(unknown)}; allowed keys are "
                f"{sorted(_PROFILE_ALLOWED_FIELDS)}"
            )

        if not _is_non_empty_str(profile["profile_id"]):
            raise DocumentRequirementsConfigurationError(
                f"{where}: 'profile_id' must be a non-empty string"
            )
        for field in _PROFILE_MATCH_FIELDS:
            if field in profile and not _is_non_empty_str(profile[field]):
                raise DocumentRequirementsConfigurationError(
                    f"{where}: '{field}' must be a non-empty string when present"
                )
        self._validate_document_list(
            profile["required_documents"], where=where, field="required_documents"
        )

    def _validate_rule_config(self, rule: Any, index: int) -> None:
        where = f"conditional_rules[{index}]"
        if not isinstance(rule, dict):
            raise DocumentRequirementsConfigurationError(
                f"{where}: expected a mapping, got {type(rule).__name__}"
            )

        keys = set(rule)
        missing = _RULE_REQUIRED_FIELDS - keys
        if missing:
            raise DocumentRequirementsConfigurationError(
                f"{where}: missing required key(s) {sorted(missing)}"
            )
        unknown = keys - _RULE_ALLOWED_FIELDS
        if unknown:
            raise DocumentRequirementsConfigurationError(
                f"{where}: unknown key(s) {sorted(unknown)}; allowed keys are "
                f"{sorted(_RULE_ALLOWED_FIELDS)}"
            )

        if not _is_non_empty_str(rule["rule_id"]):
            raise DocumentRequirementsConfigurationError(
                f"{where}: 'rule_id' must be a non-empty string"
            )
        if rule["field"] not in _RULE_CONTEXT_FIELDS:
            raise DocumentRequirementsConfigurationError(
                f"{where}: 'field' must be one of {sorted(_RULE_CONTEXT_FIELDS)}, "
                f"got {rule['field']!r}"
            )
        if rule["operator"] not in _RULE_OPERATORS:
            raise DocumentRequirementsConfigurationError(
                f"{where}: 'operator' must be one of {sorted(_RULE_OPERATORS)}, "
                f"got {rule['operator']!r}"
            )
        if rule["value"] is None:
            raise DocumentRequirementsConfigurationError(
                f"{where}: 'value' must not be null"
            )
        self._validate_document_list(
            rule["additional_documents"], where=where, field="additional_documents"
        )

    def _validate_document_list(self, value: Any, *, where: str, field: str) -> None:
        if not isinstance(value, list) or not value:
            raise DocumentRequirementsConfigurationError(
                f"{where}: '{field}' must be a non-empty list"
            )
        for item in value:
            if not _is_non_empty_str(item):
                raise DocumentRequirementsConfigurationError(
                    f"{where}: '{field}' entries must be non-empty strings, got {item!r}"
                )

    def get_required_documents(
        self,
        entity_type: str,
        registration_country: str,
        sector_code: str | None = None,
        corridor_intent: str | None = None,
        declared_monthly_volume_usd: int | float | None = None,
    ) -> list[str]:
        """
        Evaluate customer attributes against document requirements config.

        Returns a deduplicated list of required document types.
        """
        required_docs: list[str] = []

        # 1. Evaluate profiles
        profiles = self.config.get("profiles", [])
        for profile in profiles:
            if self._match_profile(
                profile=profile,
                entity_type=entity_type,
                registration_country=registration_country,
                sector_code=sector_code,
                corridor_intent=corridor_intent,
            ):
                for doc in profile.get("required_documents", []):
                    if doc not in required_docs:
                        required_docs.append(doc)

        # 2. Evaluate conditional rules
        context = {
            "entity_type": entity_type,
            "registration_country": registration_country,
            "sector_code": sector_code,
            "corridor_intent": corridor_intent,
            "declared_monthly_volume_usd": declared_monthly_volume_usd,
        }

        conditional_rules = self.config.get("conditional_rules", [])
        for rule in conditional_rules:
            if self._evaluate_rule(rule, context):
                for doc in rule.get("additional_documents", []):
                    if doc not in required_docs:
                        required_docs.append(doc)

        return required_docs

    def validate_document_age(
        self,
        document_type: str,
        issue_date: date | datetime,
        reference_date: date | datetime | None = None,
    ) -> bool:
        """
        Check if a document's issue date is within the configured validity period.

        Returns True if valid (not expired), False if expired.
        """
        validity_periods = self.config.get("validity_periods", {})
        doc_rule = validity_periods.get(document_type, {})

        if not doc_rule:
            # If no specific rule exists, assume unlimited validity
            return True

        max_age_days = doc_rule.get("max_age_days")

        if max_age_days is None:
            return True

        # Resolve issue_date to date object
        if isinstance(issue_date, datetime):
            issue_d = issue_date.date()
        else:
            issue_d = issue_date

        # Resolve reference_date to date object
        if reference_date is None:
            ref_d = date.today()
        elif isinstance(reference_date, datetime):
            ref_d = reference_date.date()
        else:
            ref_d = reference_date

        age_days = (ref_d - issue_d).days

        if age_days < 0:
            # Future issue date
            return False

        if age_days > max_age_days:
            return False

        return True

    def _match_profile(
        self,
        profile: dict[str, Any],
        entity_type: str,
        registration_country: str,
        sector_code: str | None,
        corridor_intent: str | None,
    ) -> bool:
        """Check if profile match conditions are satisfied."""
        if profile.get("entity_type") and profile["entity_type"].upper() != entity_type.upper():
            return False

        if (
            profile.get("registration_country")
            and profile["registration_country"].upper() != registration_country.upper()
        ):
            return False

        if profile.get("sector_code") and sector_code:
            if profile["sector_code"].upper() != sector_code.upper():
                return False
        elif profile.get("sector_code") and not sector_code:
            return False

        if profile.get("corridor_intent") and corridor_intent:
            if profile["corridor_intent"].upper() != corridor_intent.upper():
                return False
        elif profile.get("corridor_intent") and not corridor_intent:
            return False

        return True

    def _evaluate_rule(self, rule: dict[str, Any], context: dict[str, Any]) -> bool:
        """Evaluate a conditional rule against context variables."""
        field = rule.get("field")
        op = rule.get("operator")
        target_val = rule.get("value")

        if not field or not op:
            return False

        ctx_val = context.get(field)
        if ctx_val is None:
            return False

        if op == "gt":
            return ctx_val > target_val
        elif op == "gte":
            return ctx_val >= target_val
        elif op == "lt":
            return ctx_val < target_val
        elif op == "lte":
            return ctx_val <= target_val
        elif op == "eq":
            if isinstance(ctx_val, str) and isinstance(target_val, str):
                return ctx_val.upper() == target_val.upper()
            return ctx_val == target_val
        elif op == "in":
            return isinstance(target_val, list | tuple | set | dict | str) and ctx_val in target_val

        return False
