import enum


class RequiredAction(str, enum.Enum):
    EDD_REQUIRED = "edd_required"
    ENHANCED_MONITORING = "enhanced_monitoring"
    ENHANCED_LIMITS_CHECK = "enhanced_limits_check"
    MANUAL_REVIEW = "manual_review"
