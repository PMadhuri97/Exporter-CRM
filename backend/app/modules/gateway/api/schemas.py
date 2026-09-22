"""Gateway API response DTOs."""
from pydantic import BaseModel, Field


class DependencyHealth(BaseModel):
    status: str = Field(description="'healthy' or 'unhealthy'")
    detail: str | None = Field(default=None, description="Present only when unhealthy")
    latency_ms: str | None = Field(default=None, description="Present only when healthy")


class GatewayHealthResponse(BaseModel):
    status: str = Field(description="'healthy' if every dependency is healthy, else 'degraded'")
    dependencies: dict[str, DependencyHealth] = Field(
        description=(
            "Per-dependency breakdown, keyed by dependency name. A future "
            "dependency appears as a new key — never a breaking shape change."
        )
    )
