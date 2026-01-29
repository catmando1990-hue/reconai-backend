# app/routers/cfo_data.py
"""
CFO Data Management API - Accounts & Transactions

CRUD endpoints for CFO-isolated data:
- Accounts: Manual account setup
- Transactions: Manual entry and CSV import

All endpoints are organization-isolated and require authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, status, Query, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from uuid import uuid4
import csv
import io

from app.auth_context import get_current_context, AuthContext
from app.cfo import db as cfo_db


router = APIRouter(prefix="/api/cfo", tags=["CFO Data"])


# =============================================================================
# MODELS
# =============================================================================

class AccountCreate(BaseModel):
    """Request model for creating a CFO account."""
    account_name: str = Field(..., min_length=1, max_length=100)
    account_type: Literal["bank", "credit", "investment", "loan", "other"]
    institution_name: Optional[str] = None
    account_number_masked: Optional[str] = Field(None, max_length=4)
    currency: str = "USD"
    current_balance: float = 0.0


class AccountUpdate(BaseModel):
    """Request model for updating a CFO account."""
    account_name: Optional[str] = None
    account_type: Optional[Literal["bank", "credit", "investment", "loan", "other"]] = None
    institution_name: Optional[str] = None
    current_balance: Optional[float] = None
    is_active: Optional[bool] = None


class TransactionCreate(BaseModel):
    """Request model for creating a CFO transaction."""
    transaction_date: str = Field(..., description="YYYY-MM-DD")
    amount: float
    account_id: Optional[str] = None
    description: Optional[str] = None
    merchant_name: Optional[str] = None
    category: Optional[str] = None
    transaction_type: Optional[Literal["revenue", "expense", "transfer", "other"]] = None
    department: Optional[str] = None
    cost_center: Optional[str] = None


class TransactionUpdate(BaseModel):
    """Request model for updating a CFO transaction."""
    amount: Optional[float] = None
    description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[Literal["pending", "posted", "reconciled", "voided"]] = None


# =============================================================================
# HELPERS
# =============================================================================

def _generate_request_id() -> str:
    """Generate unique request ID for audit trail."""
    return f"req_{uuid4().hex[:12]}"


# =============================================================================
# ACCOUNT ENDPOINTS
# =============================================================================

@router.get("/accounts")
async def list_accounts(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    """List all CFO accounts for the organization."""
    request_id = _generate_request_id()
    items = cfo_db.list_accounts(ctx["org_id"], limit=limit)
    return {
        "status": "ok",
        "items": items,
        "total": len(items),
        "request_id": request_id
    }


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(
    body: AccountCreate,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Create a new CFO account."""
    request_id = _generate_request_id()
    account_id = str(uuid4())

    cfo_db.create_account(
        id=account_id,
        org_id=ctx["org_id"],
        account_name=body.account_name,
        account_type=body.account_type,
        institution_name=body.institution_name,
        account_number_masked=body.account_number_masked,
        currency=body.currency,
        current_balance=body.current_balance,
        created_by=ctx["user_id"],
    )

    account = cfo_db.get_account(ctx["org_id"], account_id)
    return {
        "status": "ok",
        "data": account,
        "request_id": request_id
    }


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Get a single CFO account."""
    request_id = _generate_request_id()
    account = cfo_db.get_account(ctx["org_id"], account_id)

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Account not found", "request_id": request_id}
        )

    return {
        "status": "ok",
        "data": account,
        "request_id": request_id
    }


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: str,
    body: AccountUpdate,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Update a CFO account."""
    request_id = _generate_request_id()

    existing = cfo_db.get_account(ctx["org_id"], account_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Account not found", "request_id": request_id}
        )

    updates = body.model_dump(exclude_none=True)
    account = cfo_db.update_account(ctx["org_id"], account_id, updates)

    return {
        "status": "ok",
        "data": account,
        "request_id": request_id
    }


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Soft delete a CFO account."""
    request_id = _generate_request_id()

    existing = cfo_db.get_account(ctx["org_id"], account_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Account not found", "request_id": request_id}
        )

    cfo_db.delete_account(ctx["org_id"], account_id)

    return {
        "status": "ok",
        "message": "Account deleted",
        "request_id": request_id
    }


# =============================================================================
# TRANSACTION ENDPOINTS
# =============================================================================

@router.get("/transactions")
async def list_transactions(
    ctx: AuthContext = Depends(get_current_context),
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(default=100, le=500),
) -> Dict[str, Any]:
    """List CFO transactions with optional filters."""
    request_id = _generate_request_id()

    items = cfo_db.list_transactions(
        ctx["org_id"],
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    return {
        "status": "ok",
        "items": items,
        "total": len(items),
        "request_id": request_id
    }


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
async def create_transaction(
    body: TransactionCreate,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Create a new CFO transaction."""
    request_id = _generate_request_id()
    tx_id = str(uuid4())

    cfo_db.create_transaction(
        id=tx_id,
        org_id=ctx["org_id"],
        transaction_date=body.transaction_date,
        amount=body.amount,
        account_id=body.account_id,
        description=body.description,
        merchant_name=body.merchant_name,
        category=body.category,
        transaction_type=body.transaction_type,
        department=body.department,
        cost_center=body.cost_center,
        created_by=ctx["user_id"],
    )

    tx = cfo_db.get_transaction(ctx["org_id"], tx_id)
    return {
        "status": "ok",
        "data": tx,
        "request_id": request_id
    }


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Get a single CFO transaction."""
    request_id = _generate_request_id()
    tx = cfo_db.get_transaction(ctx["org_id"], transaction_id)

    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Transaction not found", "request_id": request_id}
        )

    return {
        "status": "ok",
        "data": tx,
        "request_id": request_id
    }


@router.patch("/transactions/{transaction_id}")
async def update_transaction(
    transaction_id: str,
    body: TransactionUpdate,
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """Update a CFO transaction."""
    request_id = _generate_request_id()

    existing = cfo_db.get_transaction(ctx["org_id"], transaction_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Transaction not found", "request_id": request_id}
        )

    updates = body.model_dump(exclude_none=True)
    tx = cfo_db.update_transaction(ctx["org_id"], transaction_id, updates)

    return {
        "status": "ok",
        "data": tx,
        "request_id": request_id
    }


@router.post("/transactions/import")
async def import_transactions(
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_current_context),
) -> Dict[str, Any]:
    """
    Import transactions from CSV file.

    Expected columns:
    - date (required): YYYY-MM-DD
    - amount (required): Decimal number
    - description (optional)
    - merchant (optional)
    - category (optional)
    - type (optional): revenue, expense, transfer, other
    - department (optional)
    - external_id (optional): For deduplication
    """
    request_id = _generate_request_id()

    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_FILE", "message": "File must be CSV", "request_id": request_id}
        )

    content = await file.read()
    decoded = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(decoded))

    transactions = []
    errors = []

    for i, row in enumerate(reader, start=2):  # Start at 2 to account for header
        try:
            tx = {
                "transaction_date": row.get("date", "").strip(),
                "amount": float(row.get("amount", "0").strip()),
                "description": row.get("description", "").strip() or None,
                "merchant_name": row.get("merchant", "").strip() or None,
                "category": row.get("category", "").strip() or None,
                "transaction_type": row.get("type", "").strip() or None,
                "department": row.get("department", "").strip() or None,
                "external_id": row.get("external_id", "").strip() or None,
            }

            if not tx["transaction_date"]:
                errors.append(f"Row {i}: Missing date")
                continue

            transactions.append(tx)
        except ValueError as e:
            errors.append(f"Row {i}: {str(e)}")

    if not transactions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "NO_VALID_ROWS",
                "message": "No valid transactions found",
                "errors": errors[:10],  # Limit errors shown
                "request_id": request_id
            }
        )

    result = cfo_db.bulk_import_transactions(
        ctx["org_id"],
        transactions,
        ctx["user_id"],
    )

    return {
        "status": "ok",
        "imported": result["imported"],
        "skipped": result["skipped"],
        "errors": errors[:10] if errors else None,
        "request_id": request_id
    }
