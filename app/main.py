# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import (
    plaid,
    transactions,
    accounting,
    tax,
    credit,
    feedback,
    reconai,
    exports,
)

app = FastAPI(title="ReconAI Backend MVP")


# ---------------------------
# CORS (frontend ready)
# ---------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------
# Startup
# ---------------------------
@app.on_event("startup")
def on_startup():
    init_db()


# ---------------------------
# Routers
# ---------------------------

# Plaid router has NO internal prefix -> we set it here
app.include_router(plaid.router, prefix="/plaid", tags=["plaid"])

# Everything below should already define its own prefix inside the router file
app.include_router(transactions.router)
app.include_router(reconai.router)
app.include_router(exports.router)

app.include_router(accounting.router)
app.include_router(tax.router)
app.include_router(credit.router)
app.include_router(feedback.router)


# ---------------------------
# Health
# ---------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "ReconAI brain online."}
