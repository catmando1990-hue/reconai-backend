# app/main.py
from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

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
from app.routers.organizations import router as organizations_router
from app.routers.entities import router as entities_router
from app.routers.contact import router as contact_router
from app.routers.newsletter import router as newsletter_router
from app.routers.customers import router as customers_router
from app.routers.invoices import router as invoices_router
from app.routers.reports import router as reports_router
from app.routers.stripe_webhooks import router as stripe_webhooks_router
from app.routers.compliance import router as compliance_router
from app.routers import claude


def get_allowed_origins() -> list[str]:
    """
    Allow local dev frontend + production.
    Override with CORS_ORIGINS env var if needed.
    """
    env = os.getenv("CORS_ORIGINS", "").strip()
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    
    # Default: support both common dev ports + production
    # NOTE: Do NOT use wildcard "https://*.vercel.app" here - use allow_origin_regex instead
    return [
        "http://localhost:5173",      # Vite default
        "http://127.0.0.1:5173",
        "http://localhost:3000",      # Next.js default port
        "http://127.0.0.1:3000",
        "http://localhost:3001",      # Next.js alternate port (YOUR FRONTEND)
        "http://127.0.0.1:3001",
        "https://reconai-frontend.onrender.com",  # Production (Render)
        "https://reconai-frontend.vercel.app",     # Production (Vercel)
    ]


# Initialize FastAPI app
app = FastAPI(
    title="ReconAI Backend",
    version="0.1.0",
    description="Financial Intelligence API for ReconAI"
)

# ============================================================================
# CORS MIDDLEWARE - MUST BE CONFIGURED BEFORE ROUTES
# ============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=r"^https://.*\.vercel\.app$",  # ✅ Matches Vercel preview URLs
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=[],  # ✅ Fixed: removed invalid "*"
    max_age=3600,  # Cache preflight requests for 1 hour
)


# ============================================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================================

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {
        "status": "ok",
        "service": "reconai-backend",
        "version": "0.1.0"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "reconai-backend"
    }


# ============================================================================
# MOUNT CLASSIFY ENDPOINT AT ROOT LEVEL (NO PREFIX)
# ============================================================================

from app.routers.plaid import classify_transactions

# Mount at root level so frontend can call /classify-transactions directly
# Note: CORSMiddleware handles OPTIONS automatically, no need for separate handler
app.add_api_route(
    "/classify-transactions",
    classify_transactions,
    methods=["POST"],
    tags=["classification"]
)


# ============================================================================
# INCLUDE ALL ROUTERS (WITH THEIR ORIGINAL PREFIXES)
# ============================================================================

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(vendors_router)
app.include_router(organizations_router)
app.include_router(entities_router)
app.include_router(contact_router)
app.include_router(newsletter_router)
app.include_router(customers_router)
app.include_router(invoices_router)
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
app.include_router(claude.router)


# ============================================================================
# STARTUP & SHUTDOWN EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    from app.db import init_db
    from app.bookkeeping.engine import BookkeeperEngine
    from app.db import DB_PATH

    print("ReconAI Backend starting up...")
    print("Initializing database...")
    # Run synchronous DB init in thread pool to avoid blocking event loop
    await run_in_threadpool(init_db)
    print("Database ready")

    # Initialize bookkeeping engine
    print("Initializing bookkeeping engine...")
    await run_in_threadpool(lambda: BookkeeperEngine(DB_PATH))
    print("Bookkeeping engine ready")

    print(f"CORS enabled for: {get_allowed_origins()}")
    print(f"CORS regex: ^https://.*\.vercel\.app$")
    print("Classify endpoint mounted at: /classify-transactions")
    print("Auth API mounted at: /api/auth")
    print("Organizations API mounted at: /api/organizations")
    print("Entities API mounted at: /api/entities")
    print("Contact API mounted at: /api/contact")
    print("Newsletter API mounted at: /api/newsletter")
    print("Customers API mounted at: /api/customers")
    print("Invoices API mounted at: /api/invoices")
    print("Reports API mounted at: /api/reports")
    print("Stripe Webhooks mounted at: /api/webhooks/stripe")
    print("Compliance API mounted at: /api/compliance")
    print("Bookkeeping API mounted at: /api/bookkeeping")


@app.on_event("shutdown")
async def shutdown_event():
    print("ReconAI Backend shutting down...")