# intelligence_guardrails_api.py
# BUILD 13 — Intelligence Guardrails (Read-only Advisory)
# Returns current intelligence guardrail configuration.
# Advisory-only mode with safety boundaries for AI-driven features.

from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext


router = APIRouter(prefix="/api")


# Intelligence guardrails configuration
# Advisory-only mode: AI provides recommendations but cannot execute writes
GUARDRAILS_CONFIG = {
    "mode": "advisory",
    "writes_allowed": False,
    "confidence_threshold": 0.85,
    "explanation_required": True,
    "signal_backed_only": True,
}


@router.get("/intelligence/guardrails")
async def get_intelligence_guardrails(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/intelligence/guardrails - Intelligence guardrails (read-only)

    Returns current AI guardrail configuration.
    Advisory-only mode means AI can recommend but not execute.
    Requires authentication.
    """
    return {
        "ok": True,
        "guardrails": GUARDRAILS_CONFIG,
        "timestamp": datetime.utcnow().isoformat(),
    }
