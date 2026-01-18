# app/routers/billing_api.py
"""
STEP 8: Stripe Checkout Session Creator

Creates POST /api/billing/create-checkout-session for tier upgrades.
- Auth via get_current_context (Depends injection)
- Tier allowlist (starter | pro | govcon)
- Resolves Stripe price IDs via env vars
- Returns checkout_url with request_id
- Structured error envelopes with request_id
"""

import os
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from uuid import uuid4

from app.auth_context import get_current_context, AuthContext

router = APIRouter(tags=["billing"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Price ID environment variable mapping
TIER_PRICE_ENV = {
    "starter": {
        "monthly": "STRIPE_PRICE_STARTER_MONTHLY",
        "yearly": "STRIPE_PRICE_STARTER_YEARLY",
    },
    "pro": {
        "monthly": "STRIPE_PRICE_PRO_MONTHLY",
        "yearly": "STRIPE_PRICE_PRO_YEARLY",
    },
    "govcon": {
        "monthly": "STRIPE_PRICE_GOVCON_MONTHLY",
        "yearly": "STRIPE_PRICE_GOVCON_YEARLY",
    },
}


class CheckoutRequest(BaseModel):
    tier: str
    interval: str  # monthly | yearly


@router.post("/api/billing/create-checkout-session")
async def create_checkout_session(
    payload: CheckoutRequest,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Create a Stripe Checkout session for tier upgrades.

    - Validates tier (starter/pro/govcon) and interval (monthly/yearly)
    - Resolves price ID from environment variables
    - Returns checkout_url for redirect-based checkout
    - Structured errors include request_id for traceability
    """
    request_id = str(uuid4())

    tier = payload.tier
    interval = payload.interval

    # Validate tier and interval
    if tier not in TIER_PRICE_ENV or interval not in ("monthly", "yearly"):
        raise HTTPException(
            status_code=400,
            detail={"request_id": request_id, "error": "invalid tier or interval"}
        )

    # Resolve price ID from environment
    price_env = TIER_PRICE_ENV[tier][interval]
    price_id = os.getenv(price_env)

    if not price_id:
        raise HTTPException(
            status_code=500,
            detail={"request_id": request_id, "error": f"missing env {price_env}"}
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=os.getenv(
                "STRIPE_SUCCESS_URL",
                "https://app.reconai.dev/settings?checkout=success"
            ),
            cancel_url=os.getenv(
                "STRIPE_CANCEL_URL",
                "https://app.reconai.dev/settings?checkout=cancelled"
            ),
            metadata={
                "org_id": ctx["org_id"],
                "user_id": ctx["user_id"],
                "tier": tier,
                "interval": interval,
            },
        )
        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "request_id": request_id
        }
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=500,
            detail={"request_id": request_id, "error": str(e)}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"request_id": request_id, "error": str(e)}
        )
