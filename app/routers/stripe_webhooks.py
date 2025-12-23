# app/routers/stripe_webhooks.py

"""
Stripe Webhook Handler
Handles Stripe events for subscription management
"""

from fastapi import APIRouter, HTTPException, Request, Header, status
from pydantic import BaseModel
from typing import Optional, Dict, Any
import sqlite3
import hmac
import hashlib
import json
import os
from datetime import datetime

from ..db import DB_PATH
from ..models_multitenancy import SubscriptionTier, SubscriptionStatus

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# Get Stripe webhook secret from environment
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


# =========================================================================
# MODELS
# =========================================================================

class WebhookResponse(BaseModel):
    """Webhook response"""
    received: bool
    event_type: str
    processed: bool
    message: Optional[str] = None


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def verify_stripe_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Stripe webhook signature"""
    if not secret:
        # If no secret configured, skip verification (dev mode)
        return True

    try:
        # Parse signature header
        elements = signature.split(',')
        timestamp = None
        signatures = []

        for element in elements:
            key, value = element.split('=')
            if key == 't':
                timestamp = value
            elif key == 'v1':
                signatures.append(value)

        if not timestamp or not signatures:
            return False

        # Construct signed payload
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"

        # Compute expected signature
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Compare signatures
        return any(hmac.compare_digest(expected_sig, sig) for sig in signatures)

    except Exception as e:
        print(f"Signature verification failed: {str(e)}")
        return False


def map_stripe_price_to_tier(price_id: str) -> SubscriptionTier:
    """Map Stripe price ID to subscription tier"""
    # These should match your Stripe price IDs
    price_tier_map = {
        # Add your actual Stripe price IDs here
        "price_individual": SubscriptionTier.INDIVIDUAL,
        "price_freelancer": SubscriptionTier.FREELANCER,
        "price_small_business": SubscriptionTier.SMALL_BUSINESS,
        "price_professional": SubscriptionTier.PROFESSIONAL,
        "price_enterprise": SubscriptionTier.ENTERPRISE,
    }

    return price_tier_map.get(price_id, SubscriptionTier.INDIVIDUAL)


def update_organization_subscription(
    org_id: str,
    tier: SubscriptionTier,
    status: SubscriptionStatus,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    current_period_end: Optional[str] = None
):
    """Update organization subscription in database"""
    with sqlite3.connect(DB_PATH) as conn:
        updates = {
            "tier": tier.value,
            "subscription_status": status.value,
        }

        if stripe_customer_id:
            updates["stripe_customer_id"] = stripe_customer_id

        if stripe_subscription_id:
            updates["stripe_subscription_id"] = stripe_subscription_id

        if current_period_end:
            updates["subscription_end_date"] = current_period_end

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = datetime('now')"
        values = list(updates.values()) + [org_id]

        conn.execute(
            f"UPDATE organizations SET {set_clause} WHERE id = ?",
            values
        )
        conn.commit()


def get_organization_by_stripe_customer(stripe_customer_id: str) -> Optional[str]:
    """Get organization ID by Stripe customer ID"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT id FROM organizations
            WHERE stripe_customer_id = ?
        """, (stripe_customer_id,))

        row = cursor.fetchone()
        return row[0] if row else None


# =========================================================================
# WEBHOOK HANDLERS
# =========================================================================

def handle_customer_subscription_created(data: Dict[str, Any]) -> str:
    """Handle subscription.created event"""
    subscription = data['object']
    customer_id = subscription['customer']
    price_id = subscription['items']['data'][0]['price']['id']
    subscription_id = subscription['id']
    current_period_end = datetime.fromtimestamp(subscription['current_period_end']).isoformat()

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return f"Organization not found for customer {customer_id}"

    # Map price to tier
    tier = map_stripe_price_to_tier(price_id)

    # Update organization
    update_organization_subscription(
        org_id=org_id,
        tier=tier,
        status=SubscriptionStatus.ACTIVE,
        stripe_subscription_id=subscription_id,
        current_period_end=current_period_end
    )

    return f"Subscription created for org {org_id}, tier: {tier.value}"


def handle_customer_subscription_updated(data: Dict[str, Any]) -> str:
    """Handle subscription.updated event"""
    subscription = data['object']
    customer_id = subscription['customer']
    price_id = subscription['items']['data'][0]['price']['id']
    subscription_status = subscription['status']
    current_period_end = datetime.fromtimestamp(subscription['current_period_end']).isoformat()

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return f"Organization not found for customer {customer_id}"

    # Map price to tier
    tier = map_stripe_price_to_tier(price_id)

    # Map Stripe status to our status
    status_map = {
        "active": SubscriptionStatus.ACTIVE,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELLED,
        "unpaid": SubscriptionStatus.PAST_DUE,
        "trialing": SubscriptionStatus.TRIAL,
    }
    status = status_map.get(subscription_status, SubscriptionStatus.ACTIVE)

    # Update organization
    update_organization_subscription(
        org_id=org_id,
        tier=tier,
        status=status,
        current_period_end=current_period_end
    )

    return f"Subscription updated for org {org_id}, tier: {tier.value}, status: {status.value}"


def handle_customer_subscription_deleted(data: Dict[str, Any]) -> str:
    """Handle subscription.deleted event"""
    subscription = data['object']
    customer_id = subscription['customer']

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return f"Organization not found for customer {customer_id}"

    # Downgrade to individual tier, mark as cancelled
    update_organization_subscription(
        org_id=org_id,
        tier=SubscriptionTier.INDIVIDUAL,
        status=SubscriptionStatus.CANCELLED
    )

    return f"Subscription cancelled for org {org_id}, downgraded to individual tier"


def handle_invoice_payment_succeeded(data: Dict[str, Any]) -> str:
    """Handle invoice.payment_succeeded event"""
    invoice = data['object']
    customer_id = invoice['customer']
    amount_paid = invoice['amount_paid'] / 100  # Convert from cents

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return f"Organization not found for customer {customer_id}"

    # If subscription was past_due, reactivate it
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT subscription_status FROM organizations
            WHERE id = ?
        """, (org_id,))

        row = cursor.fetchone()
        if row and row[0] == SubscriptionStatus.PAST_DUE.value:
            update_organization_subscription(
                org_id=org_id,
                tier=SubscriptionTier.INDIVIDUAL,  # Will be updated by subscription event
                status=SubscriptionStatus.ACTIVE
            )

    return f"Payment succeeded for org {org_id}, amount: ${amount_paid}"


def handle_invoice_payment_failed(data: Dict[str, Any]) -> str:
    """Handle invoice.payment_failed event"""
    invoice = data['object']
    customer_id = invoice['customer']

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return f"Organization not found for customer {customer_id}"

    # Mark subscription as past_due
    update_organization_subscription(
        org_id=org_id,
        tier=SubscriptionTier.INDIVIDUAL,  # Preserve tier
        status=SubscriptionStatus.PAST_DUE
    )

    return f"Payment failed for org {org_id}, status: past_due"


def handle_customer_created(data: Dict[str, Any]) -> str:
    """Handle customer.created event"""
    customer = data['object']
    customer_id = customer['id']
    email = customer.get('email')

    # Try to find organization by email
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT o.id FROM organizations o
            JOIN users u ON o.owner_user_id = u.id
            WHERE u.email = ?
        """, (email,))

        row = cursor.fetchone()
        if row:
            org_id = row[0]
            update_organization_subscription(
                org_id=org_id,
                tier=SubscriptionTier.INDIVIDUAL,
                status=SubscriptionStatus.TRIAL,
                stripe_customer_id=customer_id
            )
            return f"Customer linked to org {org_id}"

    return f"Customer created: {customer_id}, no org found for email {email}"


# =========================================================================
# WEBHOOK ENDPOINT
# =========================================================================

@router.post("/stripe", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature")
):
    """
    Handle Stripe webhook events

    Supported events:
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    - customer.created
    """
    try:
        # Get raw body
        payload = await request.body()

        # Verify signature
        if not verify_stripe_signature(payload, stripe_signature or "", STRIPE_WEBHOOK_SECRET):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature"
            )

        # Parse event
        event = json.loads(payload)
        event_type = event['type']
        data = event['data']

        # Handle event based on type
        handlers = {
            'customer.subscription.created': handle_customer_subscription_created,
            'customer.subscription.updated': handle_customer_subscription_updated,
            'customer.subscription.deleted': handle_customer_subscription_deleted,
            'invoice.payment_succeeded': handle_invoice_payment_succeeded,
            'invoice.payment_failed': handle_invoice_payment_failed,
            'customer.created': handle_customer_created,
        }

        handler = handlers.get(event_type)
        if handler:
            message = handler(data)
            processed = True
        else:
            message = f"Unhandled event type: {event_type}"
            processed = False

        # Log event
        print(f"Stripe webhook: {event_type} - {message}")

        return WebhookResponse(
            received=True,
            event_type=event_type,
            processed=processed,
            message=message
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing failed: {str(e)}"
        )


@router.get("/stripe/test")
async def test_stripe_webhook():
    """
    Test endpoint to verify webhook is accessible

    Should return 200 OK when webhook URL is configured in Stripe
    """
    return {
        "status": "ok",
        "message": "Stripe webhook endpoint is ready",
        "webhook_secret_configured": bool(STRIPE_WEBHOOK_SECRET)
    }
