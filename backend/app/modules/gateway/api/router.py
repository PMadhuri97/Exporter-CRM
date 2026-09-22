"""Gateway HTTP surface: the /health probe, the /v1 passthrough, and the
version-prefix fallback.

No business endpoints live here yet — ANER-4.4-S1T1 is the pipeline skeleton
only. Later Epic 4.4 stories add real routes to ``v1_router``.
"""
from typing import NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.gateway.api.schemas import DependencyHealth, GatewayHealthResponse
from app.modules.gateway.application.services import GatewayHealthService
from app.modules.gateway.config import VERSION_SEGMENT_PATTERN, is_supported_version
from app.platform.database.services import get_db
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)

#: Mounted at the application root (see app/main.py) — a gateway health probe
#: is infrastructure, not a versioned business capability, so it deliberately
#: sits outside /v1.
health_router = APIRouter()

#: Mounted at "/v1". Empty today; future Epic 4.4 stories register their
#: routers here. A request to an undefined path under this prefix falls
#: through to fallback_router below and gets an ordinary 404 — expected and
#: explicitly acceptable for this slice.
v1_router = APIRouter()

#: Mounted LAST, at the application root, after every other router (including
#: the platform's internal api_router) and after the static mount and
#: convenience redirects — see app/main.py. Only a path nothing else matched
#: ever reaches this one.
fallback_router = APIRouter()


@health_router.get(
    "/health",
    response_model=GatewayHealthResponse,
    summary="Gateway health",
    description=(
        "Overall gateway health plus a per-dependency breakdown. Today the "
        "only dependency is the database; later stories add the services the "
        "gateway routes to."
    ),
    tags=["Gateway"],
)
async def health(db: AsyncSession = Depends(get_db)) -> GatewayHealthResponse:
    overall_status, dependencies = await GatewayHealthService(db).check()
    return GatewayHealthResponse(
        status=overall_status,
        dependencies={name: DependencyHealth(**info) for name, info in dependencies.items()},
    )


def _reject_version_or_404(version: str) -> NoReturn:
    """The one piece of version-routing logic, shared by both fallback routes.

    A version-SHAPED segment ("v2", "v7") that is not in the supported set is
    a deliberate rejection — raised as NotFoundError so it comes back through
    the same normalized error handler as every other gateway-produced error
    (app.platform.middleware.handlers.aner_exception_handler, wired in
    app/main.py). Anything else reaching this fallback — including a
    version-shaped-but-SUPPORTED segment with no matching route underneath,
    i.e. an undefined /v1/... path — is an ordinary HTTPException(404),
    byte-for-byte what Starlette would have returned had this fallback route
    not existed. That keeps the fallback's blast radius to exactly the
    version-rejection case: every other unmatched path on the whole
    application (a typo'd internal path included) behaves exactly as it did
    before this module existed.
    """
    if VERSION_SEGMENT_PATTERN.match(version) and not is_supported_version(version):
        raise NotFoundError(f"API version '{version}' is not supported")
    raise HTTPException(status_code=404, detail="Not Found")


@fallback_router.api_route(
    "/{version}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def version_fallback_bare(version: str) -> None:
    _reject_version_or_404(version)


@fallback_router.api_route(
    "/{version}/{rest_of_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def version_fallback(version: str, rest_of_path: str) -> None:
    _reject_version_or_404(version)
