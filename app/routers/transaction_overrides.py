# transaction_overrides.py
# BUILD 4 — Controlled Write Enablement
# Backend-only. Feature-flagged. Audit-logged.
# No historical reclassification. Every write audit-logged.

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import record_audit, get_audit_entries, get_audit_count


router = APIRouter(prefix="/api")


# Configuration - DISABLED by default (kill switch)
class WriteConfig:
    enabled: bool = False  # MUST be false by default - feature-flagged
    allow_bulk_overrides: bool = False  # Prevent mass updates
    require_reason: bool = True  # Require reason for override


WRITE_CONFIG = WriteConfig()

# In-memory stores
override_store: dict[str, dict] = {}


class OverrideRequest(BaseModel):
    category: str
    reason: Optional[str] = None


@router.post("/transactions/{transaction_id}/override")
async def override_transaction(
    transaction_id: str,
    request: OverrideRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """POST /api/transactions/:id/override - Override transaction category"""

    # Feature flag check - writes MUST be disabled by default
    if not WRITE_CONFIG.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ok": False,
                "status": "blocked",
                "reason": "Write operations are disabled",
                "code": "WRITES_DISABLED",
                "action": "contact_admin_to_enable",
            },
        )

    # Require reason if configured
    if WRITE_CONFIG.require_reason and not request.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "reason": "Override reason is required",
                "code": "MISSING_REASON",
            },
        )

    # Store the override (NO historical reclassification)
    # This only affects future processing, not past transactions
    override = {
        "transaction_id": transaction_id,
        "category": request.category,
        "reason": request.reason,
        "overridden_by": ctx["user_id"],
        "overridden_at": datetime.utcnow().isoformat(),
    }
    override_store[transaction_id] = override

    # AUDIT LOG - every successful write MUST be logged
    record_audit(
        actor=ctx["user_id"],
        action="transaction_override",
        entity="transaction",
        entity_id=transaction_id,
        payload={"category": request.category, "reason": request.reason},
    )

    return {
        "ok": True,
        "status": "ok",
        "transaction_id": transaction_id,
        "category": request.category,
        "message": "Transaction override applied successfully",
    }


@router.get("/transactions/{transaction_id}/override")
async def get_override(
    transaction_id: str,
    ctx: AuthContext = Depends(get_current_context),
):
    """GET /api/transactions/:id/override - Get override for a transaction"""
    override = override_store.get(transaction_id)

    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "ok": False,
                "reason": "No override found for this transaction",
                "code": "OVERRIDE_NOT_FOUND",
            },
        )

    return {"ok": True, "override": override}


@router.delete("/transactions/{transaction_id}/override")
async def delete_override(
    transaction_id: str,
    ctx: AuthContext = Depends(get_current_context),
):
    """DELETE /api/transactions/:id/override - Remove override"""

    # Feature flag check
    if not WRITE_CONFIG.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ok": False,
                "reason": "Write operations are disabled",
                "code": "WRITES_DISABLED",
            },
        )

    had_override = transaction_id in override_store

    if transaction_id in override_store:
        del override_store[transaction_id]

    # Audit the deletion
    record_audit(
        actor=ctx["user_id"],
        action="transaction_override_removed",
        entity="transaction",
        entity_id=transaction_id,
        payload={"removed": had_override},
    )

    return {
        "ok": True,
        "transaction_id": transaction_id,
        "removed": had_override,
        "message": "Override removed" if had_override else "No override existed",
    }


@router.get("/write/status")
async def write_status(ctx: AuthContext = Depends(get_current_context)):
    """GET /api/write/status - Check write feature flag status"""
    return {
        "ok": True,
        "config": {
            "enabled": WRITE_CONFIG.enabled,
            "allow_bulk_overrides": WRITE_CONFIG.allow_bulk_overrides,
            "require_reason": WRITE_CONFIG.require_reason,
        },
        "message": (
            "Write operations enabled"
            if WRITE_CONFIG.enabled
            else "Write operations disabled (default)"
        ),
    }


@router.get("/write/audit")
async def get_write_audit_log(
    limit: int = 50,
    actor: Optional[str] = None,
    ctx: AuthContext = Depends(get_current_context),
):
    """GET /api/write/audit - View audit log (admin)"""
    entries = get_audit_entries(limit=limit)

    if actor:
        entries = [e for e in entries if e.get("actor") == actor]

    return {
        "ok": True,
        "entries": entries,
        "total": get_audit_count(),
    }
