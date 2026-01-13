# maintenance_api.py
# BUILD 7 — Admin Maintenance Kill Switch
# Backend-controlled. Default OFF. Admin-only toggle. Audit-logged.

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import record_audit


router = APIRouter(prefix="/api")


# Maintenance state - DEFAULT OFF
MAINTENANCE_STATE = {"enabled": False}


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
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/admin/maintenance/enable - Enable maintenance mode (admin only)

    When enabled, non-admin dashboard access should redirect to /maintenance.
    """
    require_admin(ctx)

    MAINTENANCE_STATE["enabled"] = True

    # Audit log the toggle
    record_audit(
        actor=ctx["user_id"],
        action="maintenance_enabled",
        entity="system",
        entity_id="maintenance",
        payload={"enabled": True},
    )

    return {
        "ok": True,
        "status": "enabled",
        "message": "Maintenance mode enabled",
    }


@router.post("/admin/maintenance/disable")
async def disable_maintenance(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    POST /api/admin/maintenance/disable - Disable maintenance mode (admin only)
    """
    require_admin(ctx)

    MAINTENANCE_STATE["enabled"] = False

    # Audit log the toggle
    record_audit(
        actor=ctx["user_id"],
        action="maintenance_disabled",
        entity="system",
        entity_id="maintenance",
        payload={"enabled": False},
    )

    return {
        "ok": True,
        "status": "disabled",
        "message": "Maintenance mode disabled",
    }


@router.get("/maintenance/status")
async def maintenance_status():
    """
    GET /api/maintenance/status - Check maintenance mode status (public)

    No auth required - frontend needs to check this before loading dashboard.
    """
    return {
        "ok": True,
        "enabled": MAINTENANCE_STATE["enabled"],
    }
