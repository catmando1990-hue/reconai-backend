# plaid_hardening.py
# BUILD 3C — Plaid Ingestion Hardening (Backend)
# BUILD 3D — Real Plaid Sync (Kill-Switch Controlled)
# Backend-only. No frontend impact.

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext


router = APIRouter(prefix="/api/plaid")


# Configuration - syncEnabled must remain FALSE by default (kill switch)
class PlaidConfig:
    sync_enabled: bool = False  # KILL SWITCH - must be explicitly enabled
    allow_double_pull: bool = False  # Prevents duplicate transaction fetches
    require_idempotent_cursor: bool = True  # Enforces cursor-based pagination


PLAID_CONFIG = PlaidConfig()

# In-memory stores
cursor_store: dict[str, str] = {}
transaction_store: dict[str, dict] = {}
signals_log: list[dict] = []


class SyncRequest(BaseModel):
    account_id: str
    access_token: Optional[str] = None
    cursor: Optional[str] = None


class CursorResetRequest(BaseModel):
    account_id: str


def get_cursor(account_id: str) -> Optional[str]:
    """Get cursor for account (cursor-based incremental sync only)"""
    return cursor_store.get(account_id)


def set_cursor(account_id: str, cursor: str) -> None:
    """Set cursor for account (only after successful sync)"""
    if cursor:
        cursor_store[account_id] = cursor


def would_double_pull(account_id: str, cursor: Optional[str]) -> bool:
    """Check if a sync request would result in a double-pull"""
    last_cursor = cursor_store.get(account_id)
    if not last_cursor:
        return False
    return last_cursor == cursor


def upsert_transactions(account_id: str, transactions: list[dict]) -> int:
    """Upsert transactions idempotently (no duplicates)"""
    new_count = 0
    for tx in transactions:
        key = f"{account_id}:{tx.get('transaction_id', '')}"
        if key not in transaction_store:
            transaction_store[key] = {
                **tx,
                "account_id": account_id,
                "synced_at": datetime.utcnow().isoformat(),
            }
            new_count += 1
    return new_count


def emit_signal(signal: dict) -> dict:
    """Emit signal on any failure"""
    entry = {
        **signal,
        "timestamp": datetime.utcnow().isoformat(),
    }
    signals_log.append(entry)
    return entry


@router.post("/sync")
async def plaid_sync(
    request: SyncRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """POST /api/plaid/sync - Hardened sync endpoint with kill switch"""
    account_id = request.account_id

    # BUILD 3D: Kill switch check - syncEnabled must remain FALSE by default
    if not PLAID_CONFIG.sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ok": False,
                "status": "blocked",
                "reason": "Plaid ingestion hardening guard active - sync not enabled",
                "code": "SYNC_DISABLED",
                "action": "enable_sync",
            },
        )

    # Guard: Prevent double-pulls
    if not PLAID_CONFIG.allow_double_pull and request.cursor and would_double_pull(account_id, request.cursor):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "ok": False,
                "status": "blocked",
                "reason": "Double-pull detected - cursor already processed",
                "code": "DOUBLE_PULL_BLOCKED",
                "action": "no_double_pull_enforced",
                "last_cursor": get_cursor(account_id),
            },
        )

    try:
        # BUILD 3D: Get cursor for incremental sync (cursor-based ONLY, no historical pull)
        cursor = get_cursor(account_id)

        # Placeholder for real Plaid sync
        # Real implementation would call plaidClient.transactionsSync()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ok": False,
                "status": "blocked",
                "reason": "Plaid client not configured - real sync requires Plaid credentials",
                "code": "PLAID_NOT_IMPLEMENTED",
                "action": "guardrail_infrastructure_only",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        # BUILD 3D: Emit signal on ANY failure
        emit_signal({
            "type": "plaid_sync_failed",
            "severity": "high",
            "entity": "plaid_item",
            "entity_id": account_id,
            "message": str(e),
            "code": "SYNC_ERROR",
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "status": "error",
                "reason": str(e),
                "code": "SYNC_FAILED",
            },
        )


@router.get("/status")
async def plaid_status(ctx: AuthContext = Depends(get_current_context)):
    """GET /api/plaid/status - Check hardening status"""
    return {
        "ok": True,
        "hardening": {
            "sync_enabled": PLAID_CONFIG.sync_enabled,
            "allow_double_pull": PLAID_CONFIG.allow_double_pull,
            "require_idempotent_cursor": PLAID_CONFIG.require_idempotent_cursor,
        },
        "message": (
            "Plaid sync enabled - kill switch OFF"
            if PLAID_CONFIG.sync_enabled
            else "Plaid sync disabled - kill switch ON (default)"
        ),
    }


@router.post("/cursor/reset")
async def cursor_reset(
    request: CursorResetRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """POST /api/plaid/cursor/reset - Admin endpoint to reset cursor"""
    account_id = request.account_id
    had_cursor = account_id in cursor_store

    if account_id in cursor_store:
        del cursor_store[account_id]

    return {
        "ok": True,
        "account_id": account_id,
        "cursor_cleared": had_cursor,
        "message": "Cursor reset for account" if had_cursor else "No cursor existed for account",
    }


@router.get("/signals")
async def get_signals(
    limit: int = 50,
    ctx: AuthContext = Depends(get_current_context),
):
    """GET /api/plaid/signals - View emitted signals (admin/debug)"""
    return {
        "ok": True,
        "signals": signals_log[-limit:],
        "total": len(signals_log),
    }


@router.get("/transactions")
async def get_transactions(
    account_id: Optional[str] = None,
    ctx: AuthContext = Depends(get_current_context),
):
    """GET /api/plaid/transactions - View stored transactions (admin/debug)"""
    transactions = list(transaction_store.values())

    if account_id:
        transactions = [tx for tx in transactions if tx.get("account_id") == account_id]

    return {
        "ok": True,
        "transactions": transactions[-100:],
        "total": len(transactions),
    }
