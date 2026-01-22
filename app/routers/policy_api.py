# policy_api.py
# BUILD 6 — Policy & Disclaimer Enforcement (Read-Only First)
# Contextual display only. Every acknowledgement audit-logged.
# AUDIT: FAIL-CLOSED - Audit failures abort the request.

from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import record_audit, get_audit_entries, AuditServiceError


router = APIRouter(prefix="/api")


class PolicyAcknowledgeRequest(BaseModel):
    policy: str  # e.g., "bookkeeping", "accounting", "tax", "legal"
    version: Optional[str] = "1.0"
    context: Optional[str] = None  # Optional context (e.g., page where acknowledged)


@router.post("/policy/acknowledge")
async def acknowledge_policy(
    policy_request: PolicyAcknowledgeRequest,
    http_request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/policy/acknowledge - Record policy acknowledgement

    Every acknowledgement is audit-logged for compliance.
    AUDIT: FAIL-CLOSED - If audit fails, acknowledgement is aborted.
    """
    # Generate or extract request_id for traceability
    request_id = http_request.headers.get("X-Request-ID") or str(uuid4())

    # AUDIT: FAIL-CLOSED - If this fails, the acknowledgement is aborted
    try:
        record_audit(
            actor=ctx["user_id"],
            action="policy_acknowledged",
            entity="policy",
            entity_id=policy_request.policy,
            payload={
                "policy": policy_request.policy,
                "version": policy_request.version,
                "context": policy_request.context,
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Abort - policy acknowledgement MUST be recorded
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "error": "AUDIT_FAILED",
                "message": "Policy acknowledgement aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    return {
        "ok": True,
        "status": "acknowledged",
        "policy": policy_request.policy,
        "request_id": request_id,
    }


@router.get("/policy/status")
async def get_policy_status(
    policy: Optional[str] = None,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/policy/status - Check policy acknowledgement status

    Returns acknowledgement history for the current user.
    """
    user_id = ctx["user_id"]

    # Get all policy acknowledgements from audit log
    entries = get_audit_entries(entity="policy", action="policy_acknowledged", limit=100)

    # Filter to current user's acknowledgements
    user_entries = [e for e in entries if e.get("actor") == user_id]

    if policy:
        user_entries = [e for e in user_entries if e.get("entity_id") == policy]

    return {
        "ok": True,
        "user_id": user_id,
        "acknowledgements": user_entries,
        "count": len(user_entries),
    }
