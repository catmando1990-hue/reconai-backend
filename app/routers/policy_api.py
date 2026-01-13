# policy_api.py
# BUILD 6 — Policy & Disclaimer Enforcement (Read-Only First)
# Contextual display only. Every acknowledgement audit-logged.

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import record_audit, get_audit_entries


router = APIRouter(prefix="/api")


class PolicyAcknowledgeRequest(BaseModel):
    policy: str  # e.g., "bookkeeping", "accounting", "tax", "legal"
    version: Optional[str] = "1.0"
    context: Optional[str] = None  # Optional context (e.g., page where acknowledged)


@router.post("/policy/acknowledge")
async def acknowledge_policy(
    request: PolicyAcknowledgeRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/policy/acknowledge - Record policy acknowledgement

    Every acknowledgement is audit-logged for compliance.
    """
    # Record audit entry for policy acknowledgement
    record_audit(
        actor=ctx["user_id"],
        action="policy_acknowledged",
        entity="policy",
        entity_id=request.policy,
        payload={
            "policy": request.policy,
            "version": request.version,
            "context": request.context,
        },
    )

    return {
        "ok": True,
        "status": "acknowledged",
        "policy": request.policy,
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
