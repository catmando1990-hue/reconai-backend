# system_status_api.py
# BUILD 11 — System Health Status (Read-Only)
# Exposes system health metrics for admin dashboard.

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.services.audit_service import get_audit_entries, get_audit_count
from app.routers.maintenance_api import MAINTENANCE_STATE


router = APIRouter(prefix="/api")


def get_signals_24h() -> int:
    """Count signals/audit entries in the last 24 hours."""
    entries = get_audit_entries(limit=1000)
    cutoff = datetime.utcnow() - timedelta(hours=24)

    count = 0
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry.get("timestamp", ""))
            if ts >= cutoff:
                count += 1
        except (ValueError, TypeError):
            continue

    return count


def get_last_plaid_sync() -> str | None:
    """Get timestamp of last plaid sync from audit log."""
    entries = get_audit_entries(action="plaid_sync", limit=1)
    if entries:
        return entries[0].get("timestamp")
    return None


@router.get("/system/status")
async def system_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/system/status - System health status (read-only)

    Returns health metrics for admin dashboard.
    Requires authentication but no special role.
    """
    return {
        "ok": True,
        "api": "ok",
        "maintenance": MAINTENANCE_STATE.get("enabled", False),
        "signals_24h": get_signals_24h(),
        "audit_total": get_audit_count(),
        "last_plaid_sync": get_last_plaid_sync(),
        "timestamp": datetime.utcnow().isoformat(),
    }
