# app/routers/billing_reconcile_api.py
"""
ReconAI — Billing ↔ Entitlement Reconciliation API (STEP 25)

Endpoints:
- GET /api/billing/reconcile/status - Reconciliation status
- GET /api/billing/reconcile/diff - Detailed diff between billing and entitlements

Features:
- Detect drift between Stripe billing state and internal entitlements
- Provides:
  - current tier (internal)
  - billing tier (Stripe-derived)
  - diff summary
  - recommended action (manual)
- No auto-fixes, no mutations
- Read-only reconciliation views

Requirements:
- Auth via get_current_context (Depends injection)
- RBAC: view_status
- Read-only, no mutations
- Structured responses with request_id
- Dashboard-only
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from app.routers.billing_rbac import get_billing_actor, require_billing_permission
from app.entitlements import get_tier_limits, TIER_LIMITS

router = APIRouter(prefix="/api/billing/reconcile", tags=["billing-reconcile"])


def _get_internal_tier(org_id: str) -> Dict[str, Any]:
    """Get internal tier from organizations table."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT tier FROM organizations WHERE id = ?",
                (org_id,)
            )
            row = cursor.fetchone()
            if row:
                tier = row[0] or "free"
                limits = get_tier_limits(tier)
                return {
                    "tier": tier,
                    "tier_name": limits.name,
                    "source": "internal",
                }
    except Exception:
        pass

    return {
        "tier": "free",
        "tier_name": "Free",
        "source": "internal",
    }


def _get_billing_tier(org_id: str) -> Dict[str, Any]:
    """Get billing tier from Stripe-related fields in organizations table."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """SELECT stripe_customer_id, stripe_subscription_id,
                          subscription_status, tier
                   FROM organizations WHERE id = ?""",
                (org_id,)
            )
            row = cursor.fetchone()
            if row:
                stripe_customer_id = row[0]
                stripe_subscription_id = row[1]
                subscription_status = row[2]
                tier = row[3] or "free"

                # Derive billing tier based on subscription status
                if not stripe_subscription_id:
                    billing_tier = "free"
                elif subscription_status in ("active", "trialing"):
                    billing_tier = tier
                elif subscription_status in ("past_due", "unpaid"):
                    billing_tier = tier  # Still active but at risk
                elif subscription_status in ("canceled", "incomplete_expired"):
                    billing_tier = "free"
                else:
                    billing_tier = "free"

                limits = get_tier_limits(billing_tier)

                return {
                    "tier": billing_tier,
                    "tier_name": limits.name,
                    "source": "stripe",
                    "stripe_customer_id": stripe_customer_id,
                    "stripe_subscription_id": stripe_subscription_id,
                    "subscription_status": subscription_status,
                }
    except Exception:
        pass

    return {
        "tier": "free",
        "tier_name": "Free",
        "source": "stripe",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "subscription_status": None,
    }


def _calculate_diff(internal: Dict[str, Any], billing: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate the diff between internal and billing tiers."""
    internal_tier = internal["tier"]
    billing_tier = billing["tier"]

    is_synced = internal_tier == billing_tier

    # Determine drift type
    drift_type = None
    if not is_synced:
        tier_order = ["free", "starter", "pro", "professional", "govcon", "enterprise"]
        try:
            internal_idx = tier_order.index(internal_tier.lower())
            billing_idx = tier_order.index(billing_tier.lower())
            if internal_idx > billing_idx:
                drift_type = "internal_higher"  # Internal shows higher tier than billing
            else:
                drift_type = "billing_higher"  # Billing shows higher tier than internal
        except ValueError:
            drift_type = "unknown"

    # Recommend action
    recommended_action = None
    if not is_synced:
        if drift_type == "internal_higher":
            recommended_action = "sync_down"  # Sync internal down to match billing
        elif drift_type == "billing_higher":
            recommended_action = "sync_up"  # Sync internal up to match billing
        else:
            recommended_action = "manual_review"

    # Get entitlement differences
    internal_limits = get_tier_limits(internal_tier)
    billing_limits = get_tier_limits(billing_tier)

    entitlement_diffs = []
    if internal_limits.exports_enabled != billing_limits.exports_enabled:
        entitlement_diffs.append({
            "feature": "exports_enabled",
            "internal": internal_limits.exports_enabled,
            "billing": billing_limits.exports_enabled,
        })
    if internal_limits.signals_depth != billing_limits.signals_depth:
        entitlement_diffs.append({
            "feature": "signals_depth",
            "internal": internal_limits.signals_depth,
            "billing": billing_limits.signals_depth,
        })
    if internal_limits.export_limit_per_day != billing_limits.export_limit_per_day:
        entitlement_diffs.append({
            "feature": "export_limit_per_day",
            "internal": internal_limits.export_limit_per_day,
            "billing": billing_limits.export_limit_per_day,
        })

    return {
        "is_synced": is_synced,
        "drift_type": drift_type,
        "recommended_action": recommended_action,
        "entitlement_diffs": entitlement_diffs,
        "diff_count": len(entitlement_diffs),
    }


@router.get("/status")
async def reconcile_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/billing/reconcile/status

    Get reconciliation status between billing and entitlements.

    Returns:
    - is_synced: True if internal tier matches billing tier
    - drift_type: Type of drift (if any)
    - recommended_action: Manual action to take (if any)

    Read-only endpoint - no auto-fixes.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    internal = _get_internal_tier(org_id)
    billing = _get_billing_tier(org_id)
    diff = _calculate_diff(internal, billing)

    return {
        "request_id": request_id,
        "org_id": org_id,
        "status": {
            "is_synced": diff["is_synced"],
            "drift_type": diff["drift_type"],
            "drift_count": diff["diff_count"],
        },
        "internal_tier": internal["tier"],
        "billing_tier": billing["tier"],
        "recommended_action": diff["recommended_action"],
        "advisory": "No auto-fixes. Manual reconciliation required if drift detected.",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/diff")
async def reconcile_diff(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    GET /api/billing/reconcile/diff

    Get detailed diff between billing and internal entitlements.

    Returns:
    - Internal tier details
    - Billing tier details (Stripe-derived)
    - Entitlement differences
    - Recommended manual action

    Read-only endpoint - no auto-fixes.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_status", request_id)

    internal = _get_internal_tier(org_id)
    billing = _get_billing_tier(org_id)
    diff = _calculate_diff(internal, billing)

    # Get full entitlement details for both
    internal_limits = get_tier_limits(internal["tier"])
    billing_limits = get_tier_limits(billing["tier"])

    return {
        "request_id": request_id,
        "org_id": org_id,
        "internal": {
            "tier": internal["tier"],
            "tier_name": internal["tier_name"],
            "source": internal["source"],
            "entitlements": {
                "exports_enabled": internal_limits.exports_enabled,
                "export_limit_per_day": internal_limits.export_limit_per_day,
                "signals_depth": internal_limits.signals_depth,
                "summary_enabled": internal_limits.summary_enabled,
                "intelligence_enabled": internal_limits.intelligence_enabled,
                "max_transactions_per_month": internal_limits.max_transactions_per_month,
            },
        },
        "billing": {
            "tier": billing["tier"],
            "tier_name": billing["tier_name"],
            "source": billing["source"],
            "stripe_customer_id": billing.get("stripe_customer_id"),
            "subscription_status": billing.get("subscription_status"),
            "entitlements": {
                "exports_enabled": billing_limits.exports_enabled,
                "export_limit_per_day": billing_limits.export_limit_per_day,
                "signals_depth": billing_limits.signals_depth,
                "summary_enabled": billing_limits.summary_enabled,
                "intelligence_enabled": billing_limits.intelligence_enabled,
                "max_transactions_per_month": billing_limits.max_transactions_per_month,
            },
        },
        "diff": {
            "is_synced": diff["is_synced"],
            "drift_type": diff["drift_type"],
            "entitlement_diffs": diff["entitlement_diffs"],
            "diff_count": diff["diff_count"],
        },
        "recommended_action": {
            "action": diff["recommended_action"],
            "description": _get_action_description(diff["recommended_action"]),
            "manual_only": True,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


def _get_action_description(action: Optional[str]) -> str:
    """Get human-readable description for recommended action."""
    if action is None:
        return "No action required - billing and entitlements are in sync."
    elif action == "sync_down":
        return "Internal tier is higher than billing. Verify subscription status and sync down if needed."
    elif action == "sync_up":
        return "Billing tier is higher than internal. Sync internal tier up to match subscription."
    elif action == "manual_review":
        return "Unable to determine automatic reconciliation. Manual review required."
    else:
        return "Unknown action - please contact support."
