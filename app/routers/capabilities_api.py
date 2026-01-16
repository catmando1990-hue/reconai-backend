# app/routers/capabilities_api.py
"""
ReconAI — Capability Gating API (STEP 14A)

Endpoints:
- GET /api/entitlements/capabilities - Central source of truth for tier capabilities

Features:
- Current tier
- Enabled features
- Tier limits
- Feature gates resolved for current tier

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Read-only, no mutations
- Structured response with request_id
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.entitlements import TIER_LIMITS, get_tier_limits
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(prefix="/api/entitlements", tags=["entitlements"])


# Feature Gates (canonical source)
FEATURE_GATES = {
    "basic_transactions": {"tiers": ["free", "starter", "professional", "enterprise"], "description": "Transaction tracking and management"},
    "manual_categorization": {"tiers": ["free"], "description": "Manual transaction categorization"},
    "ai_categorization": {"tiers": ["starter", "professional", "enterprise"], "description": "AI-powered auto-categorization"},
    "ai_insights": {"tiers": ["professional", "enterprise"], "description": "AI-generated financial insights"},
    "ai_forecasting": {"tiers": ["enterprise"], "description": "AI revenue forecasting"},
    "plaid_integration": {"tiers": ["starter", "professional", "enterprise"], "description": "Bank account sync via Plaid"},
    "basic_reports": {"tiers": ["starter"], "description": "Basic financial reports"},
    "advanced_reports": {"tiers": ["professional", "enterprise"], "description": "Advanced financial reports and analytics"},
    "tax_intelligence": {"tiers": ["professional", "enterprise"], "description": "Tax deduction tracking and insights"},
    "compliance_automation": {"tiers": ["enterprise"], "description": "DCAA/SF-1408 compliance automation"},
    "soc2_readiness": {"tiers": ["enterprise"], "description": "SOC 2 readiness tracking"},
    "email_support": {"tiers": ["free", "starter"], "description": "Email support"},
    "priority_support": {"tiers": ["professional"], "description": "Priority email and chat support"},
    "dedicated_support": {"tiers": ["enterprise"], "description": "Dedicated account manager"},
    "api_access": {"tiers": ["professional", "enterprise"], "description": "API access for integrations"},
    "custom_integrations": {"tiers": ["enterprise"], "description": "Custom integration development"},
    "sla_guarantee": {"tiers": ["enterprise"], "description": "99.9% uptime SLA guarantee"},
    "exports": {"tiers": ["starter", "professional", "enterprise"], "description": "Data export functionality"},
    "signals": {"tiers": ["free", "starter", "professional", "enterprise"], "description": "Financial signals and alerts"},
    "intelligence": {"tiers": ["free", "starter", "professional", "enterprise"], "description": "AI intelligence features"},
}


def _get_org_tier(org_id: str) -> str:
    """Get current tier for an organization from DB."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT tier FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else "free"
    except Exception:
        return "free"


def _resolve_enabled_features(tier: str) -> List[Dict[str, Any]]:
    """Resolve which features are enabled for a given tier."""
    enabled = []
    for feature_id, config in FEATURE_GATES.items():
        is_enabled = tier in config["tiers"]
        enabled.append({
            "id": feature_id,
            "description": config["description"],
            "enabled": is_enabled,
        })
    return enabled


@router.get("/capabilities")
async def get_capabilities(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/entitlements/capabilities

    Central source of truth for tier capabilities.
    Returns current tier, enabled features, and limits.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    # Get tier from DB (most accurate) or context fallback
    tier = _get_org_tier(org_id)
    if not tier or tier == "free":
        tier = ctx.get("tier", "free")

    # Get tier limits
    limits = get_tier_limits(tier)

    # Resolve enabled features
    features = _resolve_enabled_features(tier)
    enabled_features = [f for f in features if f["enabled"]]
    disabled_features = [f for f in features if not f["enabled"]]

    return {
        "request_id": request_id,
        "org_id": org_id,
        "tier": tier,
        "tier_name": limits.name,
        "limits": {
            "transactions_per_month": limits.max_transactions_per_month,
            "exports_per_day": limits.export_limit_per_day,
            "signals_depth": limits.signals_depth,
        },
        "features": {
            "enabled": [f["id"] for f in enabled_features],
            "disabled": [f["id"] for f in disabled_features],
            "details": features,
        },
        "entitlements": {
            "exports_enabled": limits.exports_enabled,
            "summary_enabled": limits.summary_enabled,
            "intelligence_enabled": limits.intelligence_enabled,
        },
        "upgrade_url": "/settings/billing",
        "timestamp": datetime.utcnow().isoformat(),
    }
