# app/routers/billing_safeguards_api.py
"""
Billing Reliability: Cancel & Downgrade Safeguards

POST /api/billing/cancel - Schedule subscription cancellation (end of period)
POST /api/billing/downgrade - Schedule tier downgrade (end of period)

SAFEGUARDS:
- Explicit user action required (no auto-cancel)
- Changes are SCHEDULED, not immediate
- Grace period until end of billing period
- Stripe handles actual mutation at period end
- Full audit logging
- RBAC: cancel/downgrade permissions required (owner, billing_admin)
"""

import os
import sqlite3
import stripe
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import uuid4
from typing import Optional

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["billing"])

# Note: stripe.api_key is set per-request in endpoint handlers for fail-closed LAW 5 compliance

# Tier hierarchy for downgrade validation
TIER_HIERARCHY = ["free", "starter", "pro", "govcon", "enterprise"]


class DowngradeRequest(BaseModel):
    target_tier: str


def _log_billing_action(org_id: str, action: str, details: dict, request_id: str):
    """Audit log billing safeguard action."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, org_id, action, details, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                org_id,
                action,
                str(details)
            ))
            conn.commit()
    except Exception:
        pass  # Audit logging should not fail the request


def _get_org_subscription(org_id: str) -> Optional[dict]:
    """Get org's current subscription info."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT stripe_subscription_id, tier, subscription_status, current_period_end
            FROM organizations WHERE id = ?
        """, (org_id,))
        row = cursor.fetchone()
        if row:
            return {
                "subscription_id": row[0],
                "tier": row[1] or "free",
                "status": row[2],
                "current_period_end": row[3],
            }
    return None


@router.post("/api/billing/cancel")
async def cancel_subscription(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Schedule subscription cancellation at end of billing period.

    SAFEGUARDS:
    - Requires explicit user action
    - Does NOT cancel immediately
    - Schedules cancellation for end of current period
    - User retains access until period end
    - Audit logged
    """
    request_id = str(uuid4())

    # RBAC check: cancel requires owner or billing_admin
    actor = get_billing_actor(ctx["user_id"], ctx["org_id"])
    require_billing_permission(actor, "cancel", request_id)

    # LAW 5: Fail-closed in production if Stripe secrets missing
    stripe_secret = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret:
        env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
        if env == "production":
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "STRIPE_NOT_CONFIGURED",
                    "message": "Stripe API key not configured",
                    "request_id": request_id,
                }
            )
        # Dev mode: return stub
        return {
            "org_id": ctx["org_id"],
            "action": "no_action",
            "message": "Stripe not configured (dev mode)",
            "request_id": request_id,
        }
    stripe.api_key = stripe_secret

    # Get current subscription
    sub_info = _get_org_subscription(ctx["org_id"])

    if not sub_info or not sub_info.get("subscription_id"):
        return {
            "org_id": ctx["org_id"],
            "action": "no_action",
            "message": "No active subscription to cancel",
            "request_id": request_id,
        }

    # Schedule cancellation at period end via Stripe
    # This does NOT immediately cancel - user keeps access until period end
    try:
        stripe.Subscription.modify(
            sub_info["subscription_id"],
            cancel_at_period_end=True
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "STRIPE_ERROR",
                "message": str(e),
                "request_id": request_id
            }
        )

    # Update local state to reflect scheduled cancellation
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE organizations
            SET subscription_status = 'cancel_scheduled',
                updated_at = datetime('now')
            WHERE id = ?
        """, (ctx["org_id"],))
        conn.commit()

    # Audit log
    _log_billing_action(ctx["org_id"], "BILLING_CANCEL_SCHEDULED", {
        "subscription_id": sub_info["subscription_id"],
        "effective_date": sub_info.get("current_period_end"),
        "user_id": ctx["user_id"],
    }, request_id)

    return {
        "org_id": ctx["org_id"],
        "action": "cancel_scheduled",
        "effective_date": sub_info.get("current_period_end"),
        "message": "Subscription will cancel at end of billing period",
        "request_id": request_id,
    }


@router.post("/api/billing/downgrade")
async def downgrade_subscription(
    payload: DowngradeRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Schedule subscription downgrade at end of billing period.

    SAFEGUARDS:
    - Requires explicit user action
    - Does NOT downgrade immediately
    - Schedules tier change for next billing cycle
    - Current tier access retained until period end
    - Validates target tier is lower than current
    - Audit logged
    """
    request_id = str(uuid4())
    target_tier = payload.target_tier.lower()

    # Validate target tier
    ALLOWED_TIERS = {"free", "starter", "pro", "govcon"}
    if target_tier not in ALLOWED_TIERS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_TIER",
                "message": f"Invalid target tier: {target_tier}",
                "allowed": list(ALLOWED_TIERS),
                "request_id": request_id
            }
        )

    # RBAC check: downgrade requires owner or billing_admin
    actor = get_billing_actor(ctx["user_id"], ctx["org_id"])
    require_billing_permission(actor, "downgrade", request_id)

    # LAW 5: Fail-closed in production if Stripe secrets missing
    stripe_secret = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret:
        env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
        if env == "production":
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "STRIPE_NOT_CONFIGURED",
                    "message": "Stripe API key not configured",
                    "request_id": request_id,
                }
            )
        # Dev mode: return stub
        return {
            "org_id": ctx["org_id"],
            "action": "no_action",
            "message": "Stripe not configured (dev mode)",
            "request_id": request_id,
        }
    stripe.api_key = stripe_secret

    # Get current subscription
    sub_info = _get_org_subscription(ctx["org_id"])
    current_tier = sub_info.get("tier", "free") if sub_info else "free"

    # Validate this is actually a downgrade
    current_idx = TIER_HIERARCHY.index(current_tier) if current_tier in TIER_HIERARCHY else 0
    target_idx = TIER_HIERARCHY.index(target_tier) if target_tier in TIER_HIERARCHY else 0

    if target_idx >= current_idx:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "NOT_A_DOWNGRADE",
                "message": f"Target tier '{target_tier}' is not lower than current tier '{current_tier}'",
                "request_id": request_id
            }
        )

    # For downgrade to free, schedule cancellation
    if target_tier == "free":
        if sub_info and sub_info.get("subscription_id"):
            try:
                stripe.Subscription.modify(
                    sub_info["subscription_id"],
                    cancel_at_period_end=True
                )
            except stripe.error.StripeError as e:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "STRIPE_ERROR",
                        "message": str(e),
                        "request_id": request_id
                    }
                )

    # Record scheduled downgrade (Stripe webhook will apply at period end)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE organizations
            SET scheduled_tier_change = ?,
                subscription_status = 'downgrade_scheduled',
                updated_at = datetime('now')
            WHERE id = ?
        """, (target_tier, ctx["org_id"]))
        conn.commit()

    # Audit log
    _log_billing_action(ctx["org_id"], "BILLING_DOWNGRADE_SCHEDULED", {
        "from_tier": current_tier,
        "to_tier": target_tier,
        "effective_date": sub_info.get("current_period_end") if sub_info else None,
        "user_id": ctx["user_id"],
    }, request_id)

    return {
        "org_id": ctx["org_id"],
        "action": "downgrade_scheduled",
        "from_tier": current_tier,
        "to_tier": target_tier,
        "effective_date": sub_info.get("current_period_end") if sub_info else None,
        "message": "Downgrade will take effect at end of billing period",
        "request_id": request_id,
    }
