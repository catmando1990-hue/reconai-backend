# app/routers/killswitch_api.py
"""
ReconAI — Kill-Switch Status API (STEP 24)

Endpoints:
- GET /api/killswitch/status - Get kill-switch status for all features

Features:
- Read-only status endpoint
- Returns status of all kill-switches
- Used by frontend to show intentional states
- Auth via get_current_context
- RBAC: view_status
- Structured responses with request_id

Requirements:
- Dashboard-only
- Manual refresh only
"""

from __future__ import annotations

from uuid import uuid4
from datetime import datetime

from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.routers.billing_rbac import get_billing_actor, require_billing_permission
from app.entitlements import get_killswitch_status

router = APIRouter(prefix="/api/killswitch", tags=["killswitch"])


@router.get("/status")
async def killswitch_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/killswitch/status

    Get kill-switch status for all features.

    Returns the status of each feature's kill-switch.
    Used by frontend to show intentional disabled states.

    Read-only endpoint - manual refresh only.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    status = get_killswitch_status()

    # Calculate summary
    total_features = len(status)
    killed_count = sum(1 for f in status.values() if f["is_killed"])
    enabled_count = total_features - killed_count

    return {
        "request_id": request_id,
        "features": status,
        "summary": {
            "total": total_features,
            "enabled": enabled_count,
            "disabled": killed_count,
            "all_enabled": killed_count == 0,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
