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

from app.middleware import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

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
        "version": "0.1.0"
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
app.include_router(plaid_router)
app.include_router(bookkeeping_router)
app.include_router(financial_reports_router)
app.include_router(tax_intelligence_router)
app.include_router(claude.router)
app.include_router(health_router)


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
    set_startup_time()
    print(">> Sentry initialized" if os.getenv("SENTRY_DSN") else ">> WARNING: Sentry not configured")


@app.on_event("shutdown")
async def shutdown_event():
    print("ReconAI Backend shutting down...")


