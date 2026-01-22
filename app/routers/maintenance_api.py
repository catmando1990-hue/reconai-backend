# maintenance_api.py
# BUILD 7 — Admin Maintenance Kill Switch
# BUILD 10 — Extended Maintenance Status (reason, updated_at, updated_by)
# Backend-controlled. Default OFF. Admin-only toggle. Audit-logged.
# AUDIT: FAIL-CLOSED - Audit failures abort the request.

from datetime import datetime
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import record_audit, AuditServiceError


router = APIRouter(prefix="/api")


# BUILD 10: Extended maintenance state - DEFAULT OFF
MAINTENANCE_STATE = {
    "enabled": False,
    "reason": None,
    "updated_at": None,
    "updated_by": None,
}


class MaintenanceEnableRequest(BaseModel):
    reason: Optional[str] = None


def require_admin(ctx: AuthContext) -> None:
    """Check if user has admin role. Raises 403 if not."""
    # Check for admin role in permissions
    permissions = ctx.get("permissions", {})
    role = permissions.get("role", "")

    # Also check for admin in user metadata or claims
    is_admin = (
        role == "admin" or
        role == "org:admin" or
        ctx.get("is_admin", False) or
        "admin" in str(permissions.get("permissions", {}))
    )

    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "ok": False,
                "error": "FORBIDDEN",
                "message": "Admin access required",
                "code": "ADMIN_REQUIRED",
            },
        )


@router.post("/admin/maintenance/enable")
async def enable_maintenance(
    http_request: Request,
    maintenance_request: Optional[MaintenanceEnableRequest] = None,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/admin/maintenance/enable - Enable maintenance mode (admin only)

    When enabled, non-admin dashboard access should redirect to /maintenance.
    BUILD 10: Optionally accepts reason in request body.
    AUDIT: FAIL-CLOSED - If audit fails, enable is aborted.
    """
    require_admin(ctx)

    # Generate or extract request_id for traceability
    request_id = http_request.headers.get("X-Request-ID") or str(uuid4())

    # Capture previous state for rollback
    prev_enabled = MAINTENANCE_STATE["enabled"]
    prev_reason = MAINTENANCE_STATE["reason"]
    prev_updated_at = MAINTENANCE_STATE["updated_at"]
    prev_updated_by = MAINTENANCE_STATE["updated_by"]

    # BUILD 10: Extended state tracking
    MAINTENANCE_STATE["enabled"] = True
    MAINTENANCE_STATE["reason"] = maintenance_request.reason if maintenance_request else None
    MAINTENANCE_STATE["updated_at"] = datetime.utcnow().isoformat()
    MAINTENANCE_STATE["updated_by"] = ctx["user_id"]

    # AUDIT: FAIL-CLOSED - If this fails, the enable is aborted
    try:
        record_audit(
            actor=ctx["user_id"],
            action="maintenance_enabled",
            entity="system",
            entity_id="maintenance",
            payload={
                "enabled": True,
                "reason": MAINTENANCE_STATE["reason"],
            },
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Rollback state and abort
        MAINTENANCE_STATE["enabled"] = prev_enabled
        MAINTENANCE_STATE["reason"] = prev_reason
        MAINTENANCE_STATE["updated_at"] = prev_updated_at
        MAINTENANCE_STATE["updated_by"] = prev_updated_by
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "error": "AUDIT_FAILED",
                "message": "Maintenance enable aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    return {
        "ok": True,
        "status": "enabled",
        "message": "Maintenance mode enabled",
        "reason": MAINTENANCE_STATE["reason"],
        "updated_at": MAINTENANCE_STATE["updated_at"],
        "request_id": request_id,
    }


@router.post("/admin/maintenance/disable")
async def disable_maintenance(
    http_request: Request,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/admin/maintenance/disable - Disable maintenance mode (admin only)

    AUDIT: FAIL-CLOSED - If audit fails, disable is aborted.
    """
    require_admin(ctx)

    # Generate or extract request_id for traceability
    request_id = http_request.headers.get("X-Request-ID") or str(uuid4())

    # Capture previous state for rollback
    prev_enabled = MAINTENANCE_STATE["enabled"]
    prev_reason = MAINTENANCE_STATE["reason"]
    prev_updated_at = MAINTENANCE_STATE["updated_at"]
    prev_updated_by = MAINTENANCE_STATE["updated_by"]

    # BUILD 10: Extended state tracking
    MAINTENANCE_STATE["enabled"] = False
    MAINTENANCE_STATE["reason"] = None
    MAINTENANCE_STATE["updated_at"] = datetime.utcnow().isoformat()
    MAINTENANCE_STATE["updated_by"] = ctx["user_id"]

    # AUDIT: FAIL-CLOSED - If this fails, the disable is aborted
    try:
        record_audit(
            actor=ctx["user_id"],
            action="maintenance_disabled",
            entity="system",
            entity_id="maintenance",
            payload={"enabled": False},
            request_id=request_id,
        )
    except AuditServiceError as e:
        # FAIL-CLOSED: Rollback state and abort
        MAINTENANCE_STATE["enabled"] = prev_enabled
        MAINTENANCE_STATE["reason"] = prev_reason
        MAINTENANCE_STATE["updated_at"] = prev_updated_at
        MAINTENANCE_STATE["updated_by"] = prev_updated_by
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "error": "AUDIT_FAILED",
                "message": "Maintenance disable aborted: audit recording failed",
                "request_id": request_id,
            },
        ) from e

    return {
        "ok": True,
        "status": "disabled",
        "message": "Maintenance mode disabled",
        "updated_at": MAINTENANCE_STATE["updated_at"],
        "request_id": request_id,
    }


@router.get("/maintenance/status")
async def maintenance_status():
    """
    GET /api/maintenance/status - Check maintenance mode status (public)

    No auth required - frontend needs to check this before loading dashboard.
    BUILD 10: Returns extended status with reason, updated_at, updated_by.
    """
    return {
        "ok": True,
        "enabled": MAINTENANCE_STATE["enabled"],
        "reason": MAINTENANCE_STATE["reason"],
        "updated_at": MAINTENANCE_STATE["updated_at"],
        "updated_by": MAINTENANCE_STATE["updated_by"],
    }
