# app/routers/gtm_pricing_api.py
"""
ReconAI — Go-To-Market & Pricing API (Read-Only)

Endpoints:
- GET /api/gtm/tiers - List tier packaging and pricing
- GET /api/gtm/features - Feature gates by tier
- GET /api/gtm/upgrade-paths - Available upgrade paths
- GET /api/gtm/demo-metadata - Sales/demo metadata
- POST /api/gtm/request-upgrade - Request upgrade (manual, audit-logged)

Features:
- Tier packaging definitions
- Feature gate configuration
- Upgrade path recommendations
- Sales/demo metadata for marketing

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status for reads
- Manual invocation only (no polling)
- Structured responses with request_id
"""

from __future__ import annotations

import os
import json
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["gtm-pricing"])


# Tier Definitions
PRICING_TIERS = [
    {
        "id": "free",
        "name": "Free",
        "price_monthly_usd": 0,
        "price_annual_usd": 0,
        "description": "For individuals getting started",
        "features": ["basic_transactions", "manual_categorization", "email_support"],
        "limits": {"transactions_per_month": 100, "users": 1, "integrations": 1},
        "recommended_for": "Freelancers, personal use",
    },
    {
        "id": "starter",
        "name": "Starter",
        "price_monthly_usd": 49,
        "price_annual_usd": 470,
        "description": "For small businesses",
        "features": ["basic_transactions", "ai_categorization", "plaid_integration", "basic_reports", "email_support"],
        "limits": {"transactions_per_month": 1000, "users": 3, "integrations": 3},
        "recommended_for": "Small businesses, startups",
    },
    {
        "id": "professional",
        "name": "Professional",
        "price_monthly_usd": 149,
        "price_annual_usd": 1430,
        "description": "For growing companies",
        "features": ["ai_categorization", "ai_insights", "plaid_integration", "advanced_reports", "tax_intelligence", "priority_support", "api_access"],
        "limits": {"transactions_per_month": 10000, "users": 10, "integrations": 10},
        "recommended_for": "Growing companies, finance teams",
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_monthly_usd": 499,
        "price_annual_usd": 4790,
        "description": "For large organizations",
        "features": ["ai_categorization", "ai_insights", "ai_forecasting", "plaid_integration", "advanced_reports", "tax_intelligence", "compliance_automation", "soc2_readiness", "dedicated_support", "api_access", "custom_integrations", "sla_guarantee"],
        "limits": {"transactions_per_month": -1, "users": -1, "integrations": -1},  # -1 = unlimited
        "recommended_for": "Enterprises, regulated industries",
    },
]

# Feature Gates
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
}

# Demo Metadata
DEMO_METADATA = {
    "demo_available": True,
    "demo_duration_days": 14,
    "demo_tier": "professional",
    "sales_contact": "sales@reconai.com",
    "demo_features": ["Full Professional tier access", "Sample data included", "Guided onboarding"],
    "case_studies": [
        {"title": "How TechCorp saved 40 hours/month", "industry": "Technology"},
        {"title": "Reducing audit prep time by 60%", "industry": "Finance"},
    ],
}


class UpgradeRequest(BaseModel):
    target_tier: str
    billing_cycle: str = "monthly"  # monthly | annual
    notes: Optional[str] = None


def _get_current_tier(org_id: str) -> str:
    """Get current tier for an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT tier FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else "free"


def _get_upgrade_paths(current_tier: str) -> List[Dict[str, Any]]:
    """Get available upgrade paths from current tier."""
    tier_order = ["free", "starter", "professional", "enterprise"]
    current_index = tier_order.index(current_tier) if current_tier in tier_order else 0

    paths = []
    for tier in PRICING_TIERS:
        tier_index = tier_order.index(tier["id"])
        if tier_index > current_index:
            savings = 0
            if tier["price_annual_usd"] > 0 and tier["price_monthly_usd"] > 0:
                savings = (tier["price_monthly_usd"] * 12) - tier["price_annual_usd"]

            paths.append({
                "target_tier": tier["id"],
                "name": tier["name"],
                "price_monthly": tier["price_monthly_usd"],
                "price_annual": tier["price_annual_usd"],
                "annual_savings": savings,
                "new_features": [f for f in tier["features"] if f not in _get_tier_features(current_tier)],
                "recommended": tier_index == current_index + 1,
            })

    return paths


def _get_tier_features(tier_id: str) -> List[str]:
    """Get features for a specific tier."""
    for tier in PRICING_TIERS:
        if tier["id"] == tier_id:
            return tier["features"]
    return []


@router.get("/api/gtm/tiers")
async def get_pricing_tiers(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get tier packaging and pricing information.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    current_tier = _get_current_tier(org_id)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "current_tier": current_tier,
        "tiers": PRICING_TIERS,
    }


@router.get("/api/gtm/features")
async def get_feature_gates(
    ctx: AuthContext = Depends(get_current_context),
    tier: Optional[str] = Query(None, description="Filter by tier"),
):
    """
    Get feature gates configuration by tier.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    current_tier = _get_current_tier(org_id)

    features = []
    for feature_id, config in FEATURE_GATES.items():
        if tier and tier not in config["tiers"]:
            continue

        features.append({
            "id": feature_id,
            "description": config["description"],
            "available_tiers": config["tiers"],
            "enabled_for_current": current_tier in config["tiers"],
        })

    return {
        "request_id": request_id,
        "org_id": org_id,
        "current_tier": current_tier,
        "features": features,
        "total_features": len(FEATURE_GATES),
        "enabled_count": sum(1 for f in features if f["enabled_for_current"]),
    }


@router.get("/api/gtm/upgrade-paths")
async def get_upgrade_paths(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get available upgrade paths from current tier.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    current_tier = _get_current_tier(org_id)
    paths = _get_upgrade_paths(current_tier)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "current_tier": current_tier,
        "upgrade_paths": paths,
        "recommendation": paths[0] if paths else None,
    }


@router.get("/api/gtm/demo-metadata")
async def get_demo_metadata(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get sales/demo metadata for marketing.

    Read-only endpoint - no mutations.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "demo": DEMO_METADATA,
    }


@router.post("/api/gtm/request-upgrade")
async def request_upgrade(
    payload: UpgradeRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Request an upgrade to a higher tier.

    Manual trigger only - requires explicit user action.
    RBAC: manage_roles permission required.
    Audit-logged for compliance.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check - elevated permission for upgrade requests
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "manage_roles", request_id)

    # Validate target tier
    valid_tiers = [t["id"] for t in PRICING_TIERS]
    if payload.target_tier not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_TIER",
                "message": f"Tier must be one of: {', '.join(valid_tiers)}",
                "request_id": request_id,
            }
        )

    # Validate billing cycle
    if payload.billing_cycle not in ["monthly", "annual"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_BILLING_CYCLE",
                "message": "Billing cycle must be: monthly or annual",
                "request_id": request_id,
            }
        )

    current_tier = _get_current_tier(org_id)

    # Check if actually an upgrade
    tier_order = ["free", "starter", "professional", "enterprise"]
    current_index = tier_order.index(current_tier) if current_tier in tier_order else 0
    target_index = tier_order.index(payload.target_tier)

    if target_index <= current_index:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "NOT_AN_UPGRADE",
                "message": f"Target tier must be higher than current tier ({current_tier})",
                "request_id": request_id,
            }
        )

    # Audit log BEFORE returning
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, action, actor, metadata, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                "GTM_UPGRADE_REQUESTED",
                user_id,
                json.dumps({
                    "org_id": org_id,
                    "current_tier": current_tier,
                    "target_tier": payload.target_tier,
                    "billing_cycle": payload.billing_cycle,
                }),
            ))
            conn.commit()
    except Exception:
        pass

    target_tier_info = next((t for t in PRICING_TIERS if t["id"] == payload.target_tier), None)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "status": "upgrade_requested",
        "current_tier": current_tier,
        "target_tier": payload.target_tier,
        "billing_cycle": payload.billing_cycle,
        "price": target_tier_info["price_monthly_usd"] if payload.billing_cycle == "monthly" else target_tier_info["price_annual_usd"],
        "message": "Upgrade request submitted. You will be redirected to payment.",
    }
