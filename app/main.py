# app/main.py

from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Routers
from app.routers.files import router as files_router
from app.routers.exports import router as exports_router
from app.routers.reconai import router as reconai_router
from app.routers.transactions import router as transactions_router
from app.routers.accounting import router as accounting_router
from app.routers.tax import router as tax_router
from app.routers.credit import router as credit_router
from app.routers.feedback import router as feedback_router
from app.routers.plaid import router as plaid_router


def get_allowed_origins() -> list[str]:
    env = os.getenv("CORS_ORIGINS", "").strip()
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]

    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # add deployed frontend later if needed
    ]


# ✅ CREATE APP ONCE
app = FastAPI(title="ReconAI Backend MVP", version="0.1.0")

# ✅ ADD CORS ONCE (AFTER app exists)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Root + HEAD (fixes Render 405 noise)
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "ok", "service": "reconai-backend"}


# ✅ INCLUDE ROUTERS ONCE
app.include_router(files_router)
app.include_router(exports_router)
app.include_router(reconai_router)
app.include_router(transactions_router)
app.include_router(accounting_router)
app.include_router(tax_router)
app.include_router(credit_router)
app.include_router(feedback_router)
app.include_router(plaid_router)
