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
    files,
)

app = FastAPI(title="ReconAI Backend MVP")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(plaid.router, prefix="/plaid", tags=["plaid"])

app.include_router(transactions.router)
app.include_router(reconai.router)
app.include_router(exports.router)
app.include_router(files.router)

app.include_router(accounting.router)
app.include_router(tax.router)
app.include_router(credit.router)
app.include_router(feedback.router)

@app.get("/")
def root():
    return {"status": "ok", "message": "ReconAI brain online."}
