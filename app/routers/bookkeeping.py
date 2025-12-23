# app/routers/bookkeeping.py

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from decimal import Decimal

from ..bookkeeping import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntryLine,
    TrialBalance,
    GeneralLedger,
    BookkeeperEngine
)
from ..db import DB_PATH

router = APIRouter(prefix="/api/bookkeeping", tags=["bookkeeping"])

# Initialize bookkeeper engine
engine = BookkeeperEngine(DB_PATH)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class CreateAccountRequest(BaseModel):
    account_id: str
    account_number: str
    account_name: str
    account_type: AccountType
    account_subtype: Optional[str] = None
    description: Optional[str] = None
    parent_account_id: Optional[str] = None


class UpdateAccountRequest(BaseModel):
    account_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CreateJournalEntryRequest(BaseModel):
    entry_date: date
    description: str
    reference: Optional[str] = None
    lines: List[JournalEntryLine]
    auto_post: bool = False


class BulkAccountImportRequest(BaseModel):
    accounts: List[Account]


# =============================================================================
# CHART OF ACCOUNTS ENDPOINTS
# =============================================================================

@router.post("/accounts", response_model=Account)
def create_account(request: CreateAccountRequest):
    """
    Create a new account in the chart of accounts.

    - **account_id**: Unique identifier (e.g., '1000', '4010')
    - **account_number**: Display number (usually same as account_id)
    - **account_name**: Account name (e.g., 'Cash', 'Sales Revenue')
    - **account_type**: Asset/Liability/Equity/Revenue/Expense
    """
    try:
        # Create Account object from request
        from ..bookkeeping.models import AccountSubtype, NORMAL_BALANCE_MAP

        account = Account(
            account_id=request.account_id,
            account_number=request.account_number,
            account_name=request.account_name,
            account_type=request.account_type,
            account_subtype=AccountSubtype(request.account_subtype) if request.account_subtype else None,
            description=request.description,
            normal_balance=NORMAL_BALANCE_MAP[request.account_type],
            parent_account_id=request.parent_account_id,
            current_balance=Decimal("0.00")
        )

        return engine.create_account(account)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/accounts", response_model=List[Account])
def list_accounts(
    account_type: Optional[AccountType] = Query(None, description="Filter by account type"),
    active_only: bool = Query(True, description="Only return active accounts")
):
    """
    List all accounts in the chart of accounts.

    Accounts are returned sorted by account number.
    """
    return engine.list_accounts(account_type=account_type, active_only=active_only)


@router.get("/accounts/{account_id}", response_model=Account)
def get_account(account_id: str):
    """Get a specific account by ID"""
    account = engine.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return account


@router.patch("/accounts/{account_id}", response_model=Account)
def update_account(account_id: str, request: UpdateAccountRequest):
    """
    Update an existing account.

    Only account_name, description, and is_active can be updated.
    Account type and number cannot be changed after creation.
    """
    updates = request.model_dump(exclude_none=True)
    account = engine.update_account(account_id, updates)

    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    return account


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: str,
    force: bool = Query(False, description="Force hard delete (removes account even with transactions)")
):
    """
    Delete an account.

    By default, performs a soft delete (sets is_active=False).
    Use force=True to permanently delete (only if no transactions exist).
    """
    try:
        deleted = engine.delete_account(account_id, force=force)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
        return {"status": "deleted", "account_id": account_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/accounts/bulk-import", response_model=dict)
def bulk_import_accounts(request: BulkAccountImportRequest):
    """
    Bulk import accounts (useful for initial setup).

    Creates multiple accounts in a single operation.
    """
    created = []
    errors = []

    for account in request.accounts:
        try:
            created_account = engine.create_account(account)
            created.append(created_account.account_id)
        except Exception as e:
            errors.append({
                "account_id": account.account_id,
                "error": str(e)
            })

    return {
        "created_count": len(created),
        "created": created,
        "error_count": len(errors),
        "errors": errors
    }


# =============================================================================
# JOURNAL ENTRY ENDPOINTS
# =============================================================================

@router.post("/journal-entries", response_model=JournalEntry)
def create_journal_entry(request: CreateJournalEntryRequest):
    """
    Create a new journal entry.

    **Double-entry bookkeeping rules:**
    - Must have at least 2 lines
    - Each line must have either debit OR credit (not both, not neither)
    - Total debits must equal total credits
    - All accounts must exist

    **Example:**
    ```json
    {
      "entry_date": "2024-01-15",
      "description": "Payment received from customer",
      "reference": "INV-001",
      "lines": [
        {
          "account_id": "1000",
          "debit": "1000.00",
          "credit": "0.00",
          "memo": "Cash received"
        },
        {
          "account_id": "4000",
          "debit": "0.00",
          "credit": "1000.00",
          "memo": "Revenue recognized"
        }
      ],
      "auto_post": true
    }
    ```
    """
    try:
        entry = JournalEntry(
            entry_date=request.entry_date,
            description=request.description,
            reference=request.reference,
            lines=request.lines,
            status="draft"
        )

        return engine.create_journal_entry(entry, auto_post=request.auto_post)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/journal-entries", response_model=List[JournalEntry])
def list_journal_entries(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    status: Optional[str] = Query(None, description="Filter by status (draft/posted/voided)")
):
    """
    List all journal entries with optional filters.

    Entries are returned in reverse chronological order.
    """
    return engine.list_journal_entries(
        start_date=start_date,
        end_date=end_date,
        status=status
    )


@router.get("/journal-entries/{entry_id}", response_model=JournalEntry)
def get_journal_entry(entry_id: str):
    """Get a specific journal entry by ID"""
    entry = engine.get_journal_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    return entry


@router.post("/journal-entries/{entry_id}/post", response_model=JournalEntry)
def post_journal_entry(entry_id: str):
    """
    Post a journal entry (update account balances).

    Once posted:
    - Account balances are updated
    - Entry cannot be edited
    - Entry can only be reversed/voided
    """
    try:
        return engine.post_journal_entry(entry_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/journal-entries/{entry_id}/void", response_model=Optional[JournalEntry])
def void_journal_entry(
    entry_id: str,
    create_reversing_entry: bool = Query(True, description="Create reversing entry")
):
    """
    Void a posted journal entry.

    If create_reversing_entry=True, creates a new entry with debits/credits reversed.
    This maintains the audit trail while effectively canceling the original entry.
    """
    try:
        return engine.void_journal_entry(entry_id, create_reversing_entry=create_reversing_entry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# REPORTS & QUERIES
# =============================================================================

@router.get("/trial-balance", response_model=TrialBalance)
def get_trial_balance(
    as_of_date: Optional[date] = Query(None, description="Report date (defaults to today)")
):
    """
    Generate trial balance report.

    The trial balance lists all accounts with their debit/credit balances.
    Total debits must equal total credits in a balanced system.

    **Key validation:**
    - If is_balanced=True, the books are in balance
    - If is_balanced=False, there's an error that must be corrected
    """
    return engine.get_trial_balance(as_of_date=as_of_date)


@router.get("/general-ledger/{account_id}", response_model=GeneralLedger)
def get_general_ledger(
    account_id: str,
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date")
):
    """
    Get general ledger for a specific account.

    Shows all transactions affecting the account with running balance.
    """
    try:
        return engine.get_general_ledger(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/account-balance/{account_id}")
def get_account_balance(account_id: str):
    """Get current balance for a specific account"""
    balance = engine.get_account_balance(account_id)
    account = engine.get_account(account_id)

    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    return {
        "account_id": account_id,
        "account_name": account.account_name,
        "account_type": account.account_type,
        "normal_balance": account.normal_balance,
        "current_balance": balance
    }


# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================

@router.get("/validate-entry")
def validate_journal_entry_structure(
    total_debits: Decimal = Query(..., description="Total debits"),
    total_credits: Decimal = Query(..., description="Total credits")
):
    """
    Quick validation helper to check if debits equal credits.

    Useful for client-side validation before submitting.
    """
    is_balanced = total_debits == total_credits
    difference = total_debits - total_credits

    return {
        "is_balanced": is_balanced,
        "total_debits": total_debits,
        "total_credits": total_credits,
        "difference": difference,
        "valid": is_balanced
    }


@router.get("/chart-of-accounts/template")
def get_chart_of_accounts_template():
    """
    Get a standard chart of accounts template.

    Useful for initial setup. Includes common accounts for small businesses.
    """
    from ..bookkeeping.templates import get_standard_chart_of_accounts
    return get_standard_chart_of_accounts()


@router.get("/health")
def bookkeeping_health_check():
    """Health check for bookkeeping engine"""
    try:
        # Check if database is accessible
        accounts = engine.list_accounts()
        return {
            "status": "healthy",
            "database": "connected",
            "total_accounts": len(accounts)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
