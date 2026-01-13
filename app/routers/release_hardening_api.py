# release_hardening_api.py
# BUILD 12 — Release Hardening (Structured Errors)
# Provides structured error response endpoint and hardening configuration.
# Rate limiting already handled by app/middleware/rate_limit.py

from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext


router = APIRouter(prefix="/api")


# Hardening configuration
HARDENING_CONFIG = {
    "enabled": True,
    "rate_limit_window": 60,
    "rate_limit_max": 120,
    "structured_errors": True,
    "error_codes": {
        "RATE_LIMITED": 429,
        "INTERNAL_ERROR": 500,
        "UNAUTHORIZED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "VALIDATION_ERROR": 422,
    },
}


@router.get("/hardening/config")
async def get_hardening_config(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/hardening/config - Release hardening configuration (read-only)

    Returns current hardening settings.
    Requires authentication.
    """
    return {
        "ok": True,
        "config": HARDENING_CONFIG,
        "timestamp": datetime.utcnow().isoformat(),
    }
