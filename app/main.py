# app/main.py
from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    return [
        "http://localhost:5173",      # Vite default
        "http://127.0.0.1:5173",
        "http://localhost:3000",      # Alternative React port
        "http://127.0.0.1:3000",
        "https://reconai-frontend.onrender.com",  # Production
    ]


# Initialize FastAPI app
app = FastAPI(
    title="ReconAI Backend",
    version="0.1.0",
    description="Financial Intelligence API for ReconAI"
)

# Add CORS middleware (ONLY ONCE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Root endpoint (supports both GET and HEAD for health checks)
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {
        "status": "ok",
        "service": "reconai-backend",
        "version": "0.1.0"
    }


# Health check endpoint
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "reconai-backend"
    }


# Include all routers
app.include_router(files_router)
app.include_router(exports_router)
app.include_router(reconai_router)
app.include_router(transactions_router)
app.include_router(accounting_router)
app.include_router(tax_router)
app.include_router(credit_router)
app.include_router(feedback_router)
app.include_router(plaid_router)
app.include_router(claude.router)


# Startup event
@app.on_event("startup")
async def startup_event():
    from app.db import init_db
    
    print("🚀 ReconAI Backend starting up...")
    print("📊 Initializing database...")
    init_db()
    print("✅ Database ready")
    print(f"📡 CORS enabled for: {get_allowed_origins()}")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    print("👋 ReconAI Backend shutting down...")