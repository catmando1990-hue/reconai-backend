# BUILD 15 — Claims debug endpoint (read-only, auth required)

from __future__ import annotations

from fastapi import APIRouter, Depends
from app.auth_context import get_current_context, AuthContext

router = APIRouter(prefix="/api")


@router.get("/me/claims")
def me_claims(ctx: AuthContext = Depends(get_current_context)):
    """
    GET /api/me/claims - Returns effective claims for debugging.

    Auth required, read-only.
    Useful for debugging role/permission issues.
    """
    return {
        "user_id": getattr(ctx, "user_id", None),
        "org_id": getattr(ctx, "org_id", None),
        "role": getattr(ctx, "role", None),
        "roles": getattr(ctx, "roles", None),
        "claims": getattr(ctx, "claims", None),
    }
