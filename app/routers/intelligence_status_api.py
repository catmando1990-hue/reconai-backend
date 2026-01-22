# intelligence_status_api.py
# BUILD 28-30 — Intelligence Status (Read-only)
# Returns intelligence system status for Settings page.
# Advisory-only mode with confidence gating.
#
# CONTRACT VERSION: 1
# - intelligence_version: ALWAYS present in response

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.guardrails import INTELLIGENCE_CONTRACT_VERSION


router = APIRouter(prefix="/api/intelligence")


# In-memory cache status (placeholder - would be populated by actual runs)
_last_run: Optional[str] = None
_cache_status: str = "cold"


@router.get("/status")
async def get_intelligence_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/intelligence/status - Intelligence system status (read-only)

    Returns current intelligence configuration and run status.
    Advisory-only mode: AI provides recommendations but cannot execute writes.
    Manual run required: Intelligence does not run automatically.
    Confidence threshold: ≥ 0.85 required for suggestions.
    """
    return {
        "intelligence_version": INTELLIGENCE_CONTRACT_VERSION,  # ALWAYS present
        "ok": True,
        "enabled": True,
        "mode": "advisory",
        "manualRunRequired": True,
        "confidenceThreshold": 0.85,
        "categories": ["Categorization", "Duplicates", "Cashflow"],
        "lastRun": _last_run,
        "cache": _cache_status,
        "timestamp": datetime.utcnow().isoformat(),
    }
