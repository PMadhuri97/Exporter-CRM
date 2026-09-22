from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Service health status")
    version: str = Field(description="Application version")
    environment: str = Field(description="Deployment environment")


class ReadinessResponse(BaseModel):
    status: str = Field(description="Overall readiness status")
    version: str
    environment: str
    checks: dict[str, str] = Field(description="Individual dependency check results")
    observability: dict[str, str | bool] = Field(
        default_factory=dict,
        description="Observability posture: tracing/metrics enabled and export endpoint",
    )
