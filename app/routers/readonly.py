from fastapi import APIRouter, Depends
from app.auth_context import get_current_context

router = APIRouter(prefix="/api")

@router.get("/accounts")
def accounts(ctx=Depends(get_current_context)):
    return []

@router.get("/transactions")
def transactions(start: str | None = None, end: str | None = None, ctx=Depends(get_current_context)):
    return []

@router.get("/vendors")
def vendors(ctx=Depends(get_current_context)):
    return []

@router.get("/customers")
def customers(ctx=Depends(get_current_context)):
    return []

@router.get("/bills")
def bills(ctx=Depends(get_current_context)):
    return []

@router.get("/invoices")
def invoices(ctx=Depends(get_current_context)):
    return []
