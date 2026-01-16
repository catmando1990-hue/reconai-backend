# app/routers/billing_status_api.py
"""
STEP 8: Billing Status API (Read-Only)

GET /api/billing/status - Returns current organization billing status.
- Auth via get_current_context (Depends injection)
- Read-only (no mutations)
- Structured response with request_id
- RBAC: view_status permission required (all roles)
"""

import os
import sqlite3
from fastapi import APIRouter, Depends
from uuid import uuid4
from typing import Optional

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["billing"])


def _get_billing_status(org_id: str) -> dict:
    """
    Fetch billing status from database.
    Read-only query - no mutations.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT
                tier,
                stripe_customer_id,
                stripe_subscription_id,
                billing_interval,
                subscription_status,
                current_period_end
            FROM organizations
            WHERE id = ?
        """, (org_id,))
        row = cursor.fetchone()

        if row:
            return {
                "tier": row[0] or "free",
                "stripe_customer_id": row[1],
                "stripe_subscription_id": row[2],
                "interval": row[3] or "monthly",
                "status": row[4] or "active",
                "current_period_end": row[5],
            }

        return {
            "tier": "free",
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "interval": None,
            "status": "none",
            "current_period_end": None,
        }


@router.get("/api/billing/status")
async def billing_status(
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get current billing status for the authenticated organization.

    Read-only endpoint - no mutations.
    Returns tier, subscription status, and billing interval.
    RBAC: view_status permission (all authenticated users).
    """
    request_id = str(uuid4())

    # RBAC check: view_status is allowed for all roles
    actor = get_billing_actor(ctx["user_id"], ctx["org_id"])
    require_billing_permission(actor, "view_status", request_id)

    billing = _get_billing_status(ctx["org_id"])

    return {
        "org_id": ctx["org_id"],
        "tier": billing["tier"],
        "interval": billing["interval"],
        "status": billing["status"],
        "stripe_customer_id": billing["stripe_customer_id"],
        "subscription_id": billing["stripe_subscription_id"],
        "current_period_end": billing["current_period_end"],
        "renewal_date": billing["current_period_end"],  # Alias for frontend compatibility
        "source": "stripe",
        "request_id": request_id,
    }
