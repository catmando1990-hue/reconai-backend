# entitlements_api.py
# STEP 5 — Entitlements API
# Provides tier information and entitlement status to the frontend.
# NO dark patterns — transparent tier limits only.

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.entitlements import get_tier_limits, TIER_LIMITS


router = APIRouter(prefix="/api/entitlements", tags=["entitlements"])


@router.get("/status")
async def get_entitlement_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/entitlements/status

    Returns current tier and entitlement status.
    Used by frontend to show upgrade prompts (read-only, no dark patterns).
    """
    tier = ctx.get("tier", "free")
    limits = get_tier_limits(tier)

    return {
        "ok": True,
        "tier": tier,
        "tier_name": limits.name,
        "entitlements": {
            "exports_enabled": limits.exports_enabled,
            "export_limit_per_day": limits.export_limit_per_day,
            "signals_depth": limits.signals_depth,
            "summary_enabled": limits.summary_enabled,
            "intelligence_enabled": limits.intelligence_enabled,
            "max_transactions_per_month": limits.max_transactions_per_month,
        },
        "upgrade_url": "/settings/billing",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/tiers")
async def get_available_tiers(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/entitlements/tiers

    Returns all available tiers and their limits.
    Used by frontend for comparison tables (read-only).
    """
    current_tier = ctx.get("tier", "free")

    tiers = []
    for tier_key, limits in TIER_LIMITS.items():
        tiers.append({
            "tier": tier_key,
            "name": limits.name,
            "is_current": tier_key == current_tier,
            "entitlements": {
                "exports_enabled": limits.exports_enabled,
                "export_limit_per_day": limits.export_limit_per_day,
                "signals_depth": limits.signals_depth,
                "summary_enabled": limits.summary_enabled,
                "intelligence_enabled": limits.intelligence_enabled,
                "max_transactions_per_month": limits.max_transactions_per_month,
            },
        })

    return {
        "ok": True,
        "current_tier": current_tier,
        "tiers": tiers,
        "upgrade_url": "/settings/billing",
        "timestamp": datetime.utcnow().isoformat(),
    }
