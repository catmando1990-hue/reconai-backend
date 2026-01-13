# app/main.py
from __future__ import annotations
import os
import sentry_sdk

# Initialize Sentry for error tracking
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        send_default_pii=True,
        traces_sample_rate=1.0,
        environment=os.getenv("ENVIRONMENT", "development"),
    )

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Import all routers that exist
from app.routers.files import router as files_router
from app.routers.exports import router as exports_router
from app.routers.reconai import router as reconai_router
from app.routers.transactions import router as transactions_router
from app.routers.accounting import router as accounting_router
from app.routers.tax import router as tax_router
from app.routers.credit import router as credit_router
from app.routers.feedback import router as feedback_router
from app.routers.plaid import router as plaid_router
from app.routers.bookkeeping import router as bookkeeping_router
from app.routers.auth import router as auth_router
from app.routers.me import router as me_router
from app.routers.readonly import router as readonly_router
from app.routers.signals import router as signals_router
from app.routers.users import router as users_router
from app.routers.vendors import router as vendors_router
from app.routers.bills import router as bills_router
from app.routers.receipts import router as receipts_router
from app.routers.organizations import router as organizations_router
from app.routers.entities import router as entities_router
from app.routers.contact import router as contact_router
from app.routers.newsletter import router as newsletter_router
from app.routers.customers import router as customers_router
from app.routers.invoices import router as invoices_router
from app.routers.reports import router as reports_router
from app.routers.invoicing import router as invoicing_router
from app.routers.bills_ap import router as bills_ap_router
from app.routers.stripe_webhooks import router as stripe_webhooks_router
from app.routers.compliance import router as compliance_router
from app.routers import claude
from app.routers.health import router as health_router, set_startup_time
from app.routers.financial_reports import router as financial_reports_router
from app.routers.tax_intelligence import router as tax_intelligence_router
from app.routers.mvp import router as mvp_router
from app.routers.intelligence import router as intelligence_router
from app.routers.cfo import router as cfo_router
from app.routers.audit import router as audit_router
from app.routers.policy import router as policy_router
from app.routers.evidence import router as evidence_router
from app.routers.onboarding import router as onboarding_router
from app.routers.rbac import router as rbac_router
from app.routers.retention import router as retention_router
from app.routers.export_pack import router as export_pack_router
from app.routers.status import router as status_router
from app.routers.support import router as support_router
from app.routers.deploy_runs import router as deploy_runs_router
from app.routers.system_state import router as system_state_router
from app.routers.governance import router as governance_router
from app.routers.plaid_hardening import router as plaid_hardening_router
from app.routers.transaction_overrides import router as transaction_overrides_router
from app.routers.audit_api import router as audit_api_router
from app.routers.policy_api import router as policy_api_router
from app.routers.maintenance_api import router as maintenance_api_router
from app.routers.system_status_api import router as system_status_api_router
from app.routers.release_hardening_api import router as release_hardening_api_router
from app.routers.intelligence_guardrails_api import router as intelligence_guardrails_api_router
from app.routers.me_claims import router as me_claims_router


def get_allowed_origins() -> list[str]:
    env = os.getenv("CORS_ORIGINS", "").strip()
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "https://tauri.localhost",
        "https://reconai-frontend.onrender.com",
        "https://reconai-frontend.vercel.app",
        "https://reconaitechnology.com",
        "https://www.reconaitechnology.com",
    ]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if os.getenv("ENVIRONMENT") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app = FastAPI(
    title="ReconAI Backend",
    version="0.1.0",
    description="Financial Intelligence API for ReconAI"
)

# BUILD 14 — Register structured error handlers BEFORE router mounts
from app.middleware.error_envelope import register_error_handlers
register_error_handlers(app)

from app.middleware import AuthContextMiddleware, RateLimitMiddleware
from app.middleware.body_size_limit import BodySizeLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.incident_guard import IncidentGuardMiddleware

# BUILD 14 — RequestIdMiddleware must be early to propagate x-request-id
app.add_middleware(RequestIdMiddleware)
app.add_middleware(AuthContextMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(IncidentGuardMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# BUILD 14 — Request body size limit (1MB default, includes request_id in errors)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=1_000_000)

if os.getenv("ENVIRONMENT") == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "reconai-backend.onrender.com",
            "api.reconai.com",
            "*.vercel.app"
        ]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=[],
    max_age=3600,
)


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {
        "status": "ok",
        "service": "reconai-backend",
        "version": "1.0.0"
    }


# Health endpoint moved to health_router


from app.routers.plaid import classify_transactions

app.add_api_route(
    "/classify-transactions",
    classify_transactions,
    methods=["POST"],
    tags=["classification"]
)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(readonly_router)
app.include_router(signals_router)
app.include_router(users_router)
app.include_router(vendors_router)
app.include_router(bills_router)
app.include_router(receipts_router)
app.include_router(organizations_router)
app.include_router(entities_router)
app.include_router(contact_router)
app.include_router(newsletter_router)
app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(invoicing_router)
app.include_router(bills_ap_router)
app.include_router(reports_router)
app.include_router(stripe_webhooks_router)
app.include_router(compliance_router)
app.include_router(files_router)
app.include_router(exports_router)
app.include_router(reconai_router)
app.include_router(transactions_router)
app.include_router(accounting_router)
app.include_router(tax_router)
app.include_router(credit_router)
app.include_router(feedback_router)
app.include_router(mvp_router)  # Load before plaid_router to avoid /transactions route conflict
app.include_router(plaid_router)
app.include_router(bookkeeping_router)
app.include_router(financial_reports_router)
app.include_router(tax_intelligence_router)
app.include_router(claude.router)
app.include_router(health_router, prefix="/health")
app.include_router(intelligence_router, prefix="/intelligence")
app.include_router(cfo_router, prefix="/cfo")
app.include_router(audit_router)
app.include_router(policy_router)
app.include_router(evidence_router)
app.include_router(onboarding_router)
app.include_router(rbac_router)
app.include_router(retention_router)
app.include_router(export_pack_router)
app.include_router(status_router)
app.include_router(support_router)
app.include_router(deploy_runs_router)
app.include_router(system_state_router)
app.include_router(governance_router)

# BUILD 3C/3D — Plaid Ingestion Hardening
app.include_router(plaid_hardening_router)
# BUILD 4 — Controlled Write Enablement
app.include_router(transaction_overrides_router)
# BUILD 5 — Audit Log + Compliance Surface (Read-Only)
app.include_router(audit_api_router)
# BUILD 6 — Policy & Disclaimer Enforcement
app.include_router(policy_api_router)
# BUILD 7 + BUILD 10 — Admin Maintenance Kill Switch + Extended Status
app.include_router(maintenance_api_router)
# BUILD 11 — System Health Status
app.include_router(system_status_api_router)
# BUILD 12 — Release Hardening (Structured Errors)
app.include_router(release_hardening_api_router)
# BUILD 13 — Intelligence Guardrails (Advisory Mode)
app.include_router(intelligence_guardrails_api_router)
# BUILD 15 — Claims debug endpoint
app.include_router(me_claims_router)


@app.on_event("startup")
async def startup_event():
    from app.db import init_db
    from app.bookkeeping.engine import BookkeeperEngine
    from app.invoicing.engine import InvoicingEngine
    from app.bills.engine import BillsEngine
    from app.financial_reports.engine import FinancialReportsEngine
    from app.tax_intelligence.engine import TaxIntelligenceEngine
    from app.routers.invoicing import set_invoicing_engine
    from app.routers.bills_ap import set_bills_engine
    from app.routers.financial_reports import set_reports_engine
    from app.routers.tax_intelligence import set_tax_engine
    from app.db import DB_PATH

    print(">> ReconAI Backend starting up...")
    print(">> Initializing database...")
    await run_in_threadpool(init_db)
    print(">> Database ready")

    # Step 15: Enforce approved run guardrail in production
    from app.guardrails import enforce_approved_run
    await run_in_threadpool(enforce_approved_run)

    print(">> Initializing bookkeeping engine...")
    bookkeeper = await run_in_threadpool(lambda: BookkeeperEngine(DB_PATH))
    print(">> Bookkeeping engine ready")

    print(">> Initializing invoicing engine...")
    invoicing = await run_in_threadpool(lambda: InvoicingEngine(DB_PATH, bookkeeper_engine=bookkeeper))
    set_invoicing_engine(invoicing)
    print(">> Invoicing engine ready")

    print(">> Initializing bills & AP engine...")
    bills = await run_in_threadpool(lambda: BillsEngine(DB_PATH, bookkeeper_engine=bookkeeper))
    set_bills_engine(bills)
    print(">> Bills & AP engine ready")

    print(">> Initializing financial reports engine...")
    reports = await run_in_threadpool(lambda: FinancialReportsEngine(bookkeeper_engine=bookkeeper))
    set_reports_engine(reports)
    print(">> Financial reports engine ready")

    print(">> Initializing tax intelligence engine...")
    tax = await run_in_threadpool(lambda: TaxIntelligenceEngine(reports_engine=reports))
    set_tax_engine(tax)
    print(">> Tax intelligence engine ready")

    print(f">> CORS enabled for: {get_allowed_origins()}")
    print(f">> CORS regex: ^https://.*\\.vercel\\.app$")
    print(">> Classify endpoint mounted at: /classify-transactions")
    print(">> Bookkeeping API mounted at: /api/bookkeeping")
    print(">> Invoicing API mounted at: /api/invoicing")
    print(">> Bills & AP API mounted at: /api/bills")
    print(">> Financial Reports API mounted at: /api/financial-reports")
    print(">> Tax Intelligence API mounted at: /api/tax-intelligence")
    print(">> Plaid Hardening API mounted at: /api/plaid (BUILD 3C/3D - sync disabled by default)")
    print(">> Transaction Overrides API mounted at: /api/transactions/:id/override (BUILD 4 - writes disabled by default)")
    print(">> Audit API mounted at: /api/audit (BUILD 5 - read-only)")
    print(">> Policy API mounted at: /api/policy (BUILD 6 - acknowledgements audit-logged)")
    print(">> Maintenance API mounted at: /api/admin/maintenance (BUILD 7+10 - admin-only, extended status)")
    print(">> System Status API mounted at: /api/system/status (BUILD 11 - read-only health)")
    print(">> Release Hardening API mounted at: /api/hardening/config (BUILD 12 - structured errors)")
    print(">> Intelligence Guardrails API mounted at: /api/intelligence/guardrails (BUILD 13 - advisory mode)")
    print(">> BUILD 14: Enforcement consistency (request_id in all errors, x-request-id header)")
    print(">> BUILD 15: Claims debug at /api/me/claims, require_admin helper available")
    print(">> BUILD 16: Plaid idempotency helpers ready (tx_identity_key)")
    set_startup_time()
    print(">> Sentry initialized" if os.getenv("SENTRY_DSN") else ">> WARNING: Sentry not configured")


@app.on_event("shutdown")
async def shutdown_event():
    print("ReconAI Backend shutting down...")


