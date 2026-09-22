class AnerBaseException(Exception):  # noqa: N818
    detail: str
    error_code: str | None
    status_code: int
    extensions: dict

    def __init__(
        self,
        detail: str,
        error_code: str | None = None,
        status_code: int = 400,
        extensions: dict | None = None,
    ):
        self.detail = detail
        self.error_code = error_code
        self.status_code = status_code
        self.extensions = extensions or {}
        super().__init__(detail)


class NotFoundError(AnerBaseException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail=detail, error_code="NOT_FOUND", status_code=404)


class ValidationError(AnerBaseException):
    def __init__(self, detail: str):
        super().__init__(detail=detail, error_code="VALIDATION_ERROR", status_code=422)


class UnauthorizedError(AnerBaseException):
    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(detail=detail, error_code="UNAUTHORIZED", status_code=401)


class ProviderNotEnabledError(AnerBaseException):
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        super().__init__(
            detail=f"Provider '{provider_name}' is not enabled in this environment",
            error_code="PROVIDER_NOT_ENABLED",
            status_code=422,
        )


class UnsupportedCountryError(AnerBaseException):
    def __init__(self, detail: str, *, provider_name: str = "unknown"):
        self.provider_name = provider_name
        super().__init__(
            detail=detail,
            error_code="PROVIDER_UNSUPPORTED_COUNTRY",
            status_code=422,
        )

