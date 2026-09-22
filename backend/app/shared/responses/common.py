from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="Human-readable error description")
    error_code: str | None = Field(default=None, description="Machine-readable error code")
    correlation_id: str | None = Field(default=None, description="Request correlation ID")
