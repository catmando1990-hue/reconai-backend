# app/routers/billing_sync_api.py
"""
Billing Reliability: Manual Subscription Sync

POST /api/billing/sync - Reconcile local tier with Stripe subscription state.
- Auth via get_current_context (Depends injection)
- Stripe is source of truth
- No background jobs - manual invocation only
- Audit logged for compliance
"""

import os
import sqlite3
import stripe
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from uuid import uuid4
from typing import Optional

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH

router = APIRouter(tags=["billing"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Tier mapping from Stripe price IDs
PRICE_TO_TIER = {
    os.getenv("STRIPE_PRICE_STARTER_MONTHLY"): "starter",
    os.getenv("STRIPE_PRICE_STARTER_YEARLY"): "starter",
    os.getenv("STRIPE_PRICE_PRO_MONTHLY"): "pro",
    os.getenv("STRIPE_PRICE_PRO_YEARLY"): "pro",
    os.getenv("STRIPE_PRICE_GOVCON_MONTHLY"): "govcon",
    os.getenv("STRIPE_PRICE_GOVCON_YEARLY"): "govcon",
}


def _get_stripe_subscription_state(stripe_customer_id: str) -> Optional[dict]:
    """
    Fetch current subscription state from Stripe.
    Stripe is source of truth.
    """
    if not stripe_customer_id:
        return None

    try:
        subscriptions = stripe.Subscription.list(
            customer=stripe_customer_id,
            status="active",
            limit=1
        )
        if not subscriptions.data:
            return {"tier": "free", "status": "none", "interval": None}

        sub = subscriptions.data[0]
        price_id = sub["items"]["data"][0]["price"]["id"]
        tier = PRICE_TO_TIER.get(price_id, "free")
        interval = sub["items"]["data"][0]["price"]["recurring"]["interval"]

        return {
            "tier": tier,
            "status": sub["status"],
            "interval": "yearly" if interval == "year" else "monthly",
            "subscription_id": sub["id"],
            "current_period_end": datetime.fromtimestamp(sub["current_period_end"]).isoformat(),
        }
    except stripe.error.StripeError:
        return None


def _sync_org_billing(org_id: str, stripe_state: dict) -> dict:
    """
    Update local org billing state to match Stripe.
    Idempotent - can be called multiple times safely.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE organizations
            SET tier = ?,
                subscription_status = ?,
                billing_interval = ?,
                stripe_subscription_id = ?,
                current_period_end = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (
            stripe_state["tier"],
            stripe_state["status"],
            stripe_state.get("interval"),
            stripe_state.get("subscription_id"),
            stripe_state.get("current_period_end"),
            org_id
        ))
        conn.commit()

    return {
        "synced": True,
        "tier": stripe_state["tier"],
        "status": stripe_state["status"],
    }


def _log_billing_sync(org_id: str, action: str, result: dict, request_id: str):
    """Audit log billing sync action."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_log (id, org_id, action, details, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                request_id,
                org_id,
                action,
                str(result)
            ))
            conn.commit()
    except Exception:
        pass  # Audit logging should not fail the request


@router.post("/api/billing/sync")
async def billing_sync(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Manually reconcile local billing state with Stripe.

    - Requires explicit user action (no background sync)
    - Stripe is source of truth
    - Updates local tier/status to match Stripe subscription
    - Audit logged for compliance
    """
    request_id = str(uuid4())

    # Get org's Stripe customer ID
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT stripe_customer_id FROM organizations WHERE id = ?",
            (ctx["org_id"],)
        )
        row = cursor.fetchone()
        stripe_customer_id = row[0] if row else None

    if not stripe_customer_id:
        return {
            "org_id": ctx["org_id"],
            "status": "no_stripe_customer",
            "synced": False,
            "request_id": request_id,
        }

    # Fetch current state from Stripe (source of truth)
    stripe_state = _get_stripe_subscription_state(stripe_customer_id)

    if not stripe_state:
        return {
            "org_id": ctx["org_id"],
            "status": "stripe_error",
            "synced": False,
            "request_id": request_id,
        }

    # Sync local state to match Stripe
    sync_result = _sync_org_billing(ctx["org_id"], stripe_state)

    # Audit log
    _log_billing_sync(ctx["org_id"], "BILLING_SYNC", sync_result, request_id)

    return {
        "org_id": ctx["org_id"],
        "status": "in_sync",
        "tier": stripe_state["tier"],
        "subscription_status": stripe_state["status"],
        "interval": stripe_state.get("interval"),
        "synced": True,
        "request_id": request_id,
    }
