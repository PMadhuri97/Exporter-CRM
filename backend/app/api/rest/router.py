from fastapi import APIRouter

from app.api.rest import health
from app.api.rest.auth.router import router as auth_router
from app.api.rest.workflows import router as workflow_router
from app.modules.audit.api.router import router as audit_router
from app.modules.compliance.api.router import router as compliance_router
from app.modules.customers.api.router import router as customers_router
from app.modules.notifications.api.router import router as notifications_router
from app.modules.onboarding.api import router as onboarding_router

# epic4-reference: routers for fx, ledger, payments, reconciliation and
# settlement (including the settlement rail-webhook router) are removed here.
# Those modules are out of scope for this checkout — only their migrations
# (and, where another in-scope module's ORM relationships need them, their
# entities) are present, not their api/ layer. See RUNNING.md.
#
# app.api.rest.idempotency_audit is also dropped: its router imports
# LedgerTransactionKeyResolver (app.modules.ledger) and
# SettlementCrossReference (app.modules.settlement) at module scope — a
# cross-module idempotency-audit feature that is inherently spread across
# ledger and settlement infrastructure, both out of scope. The file itself is
# left in place (unused) rather than deleted, since the underlying platform
# idempotency tables/services it queries are still present.
#
# cases and kyb have no api/router.py in the real platform either (confirmed
# against the source repo), so there was never anything to include for them.

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(customers_router, prefix="/customers", tags=["Customers"])
api_router.include_router(compliance_router, prefix="/compliance", tags=["Compliance"])
api_router.include_router(audit_router, prefix="/audit", tags=["Audit"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(workflow_router, prefix="/workflows", tags=["Workflows"])
api_router.include_router(onboarding_router, prefix="/onboarding", tags=["Onboarding"])
