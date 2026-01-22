# transaction_overrides.py
# BUILD 4 — Controlled Write Enablement
# Backend-only. Feature-flagged. Audit-logged.
# No historical reclassification. Every write audit-logged.
# AUDIT: FAIL-CLOSED - Audit failures abort the request.

from datetime import datetime
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import record_audit, get_audit_entries, get_audit_count, AuditServiceError


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
    override_request: OverrideRequest,
    http_request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """POST /api/transactions/:id/override - Override transaction category

    AUDIT: FAIL-CLOSED - If audit fails, override is aborted.
    """
    # Generate or extract request_id for traceability
    request_id = http_request.headers.get("X-Request-ID") or str(uuid4())

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
    if WRITE_CONFIG.require_reason and not override_request.reason:
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
        "category": override_request.category,
        "reason": override_request.reason,
        "overridden_by": ctx["user_id"],
        "overridden_at": datetime.utcnow().isoformat(),
    }
    override_store[transaction_id] = override

    # AUDIT: FAIL-CLOSED - If this fails, the override is aborted
    try:
        record_audit(
            actor=ctx["user_id"],
            action="transaction_override",
            entity="transaction",
            entity_id=transaction_id,
            payload={"category": override_request.category, "reason": override_request.reason},
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Rollback the override and abort
        del override_store[transaction_id]
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "error": "AUDIT_FAILED",
                "message": "Override aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    return {
        "ok": True,
        "status": "ok",
        "transaction_id": transaction_id,
        "category": override_request.category,
        "message": "Transaction override applied successfully",
        "request_id": request_id,
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
    http_request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """DELETE /api/transactions/:id/override - Remove override

    AUDIT: FAIL-CLOSED - If audit fails, removal is aborted.
    """
    # Generate or extract request_id for traceability
    request_id = http_request.headers.get("X-Request-ID") or str(uuid4())

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
    removed_override = None

    if transaction_id in override_store:
        removed_override = override_store[transaction_id]
        del override_store[transaction_id]

    # AUDIT: FAIL-CLOSED - If this fails, the removal is aborted
    try:
        record_audit(
            actor=ctx["user_id"],
            action="transaction_override_removed",
            entity="transaction",
            entity_id=transaction_id,
            payload={"removed": had_override},
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Rollback the removal and abort
        if removed_override:
            override_store[transaction_id] = removed_override
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "error": "AUDIT_FAILED",
                "message": "Override removal aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    return {
        "ok": True,
        "transaction_id": transaction_id,
        "removed": had_override,
        "message": "Override removed" if had_override else "No override existed",
        "request_id": request_id,
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
