import enum


class NormalisedResult(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    REJECTED = "REJECTED"
    REQUIRES_MANUAL_REVIEW = "REQUIRES_MANUAL_REVIEW"
    PENDING = "PENDING"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class KYBVendorProcessingMode(str, enum.Enum):
    SYNCHRONOUS = "SYNCHRONOUS"
    ASYNCHRONOUS = "ASYNCHRONOUS"


class VendorHealthStatusEnum(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
