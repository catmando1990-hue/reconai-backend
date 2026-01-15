# app/routers/stripe_webhooks.py
# STEP 6 — Stripe Webhooks Hardening
# Signature verification, idempotency, replay protection, audit logging.
# Server-side authority — tier updates are atomic and audited.

"""
Stripe Webhook Handler (Hardened)
- Signature verification (STRIPE_WEBHOOK_SECRET)
- Idempotency (event_id dedupe via billing_events table)
- Timestamp replay protection (5-minute window)
- Audit logging for all billing events
- Structured errors with request_id
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Header, status
from pydantic import BaseModel
from typing import Optional, Dict, Any
import sqlite3
import hmac
import hashlib
import json
import os
import time
import uuid
from datetime import datetime

from ..db import DB_PATH
from ..models_multitenancy import SubscriptionTier, SubscriptionStatus

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# Get Stripe webhook secret from environment
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Replay protection: reject events older than this (seconds)
TIMESTAMP_TOLERANCE = 300  # 5 minutes


# =========================================================================
# MODELS
# =========================================================================

class WebhookResponse(BaseModel):
    """Webhook response"""
    received: bool
    event_type: str
    processed: bool
    message: Optional[str] = None
    event_id: Optional[str] = None


# =========================================================================
# STEP 6: BILLING EVENTS TABLE (Idempotency)
# =========================================================================

def _init_billing_events_table():
    """Create billing_events table for idempotency if it doesn't exist."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS billing_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    stripe_customer_id TEXT,
                    org_id TEXT,
                    processed_at TEXT NOT NULL,
                    result TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_billing_events_customer
                ON billing_events(stripe_customer_id, processed_at DESC)
            """)
            conn.commit()
    except Exception:
        pass  # Table may already exist


def _is_event_processed(event_id: str) -> bool:
    """Check if an event has already been processed (idempotency)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM billing_events WHERE event_id = ?",
                (event_id,)
            )
            return cursor.fetchone() is not None
    except Exception:
        return False


def _record_event_processed(
    event_id: str,
    event_type: str,
    stripe_customer_id: Optional[str],
    org_id: Optional[str],
    result: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Record that an event has been processed."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO billing_events (
                    event_id, event_type, stripe_customer_id, org_id,
                    processed_at, result, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                event_type,
                stripe_customer_id,
                org_id,
                datetime.utcnow().isoformat(),
                result,
                json.dumps(metadata) if metadata else None,
            ))
            conn.commit()
    except Exception as e:
        print(f"Failed to record billing event: {e}")


# =========================================================================
# STEP 6: BILLING AUDIT LOGGING
# =========================================================================

def _log_billing_audit(
    event_id: str,
    event_type: str,
    org_id: Optional[str],
    stripe_customer_id: Optional[str],
    action: str,
    result: str,
    request_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Log billing event to audit_logs table."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO audit_logs (
                    id, timestamp, user_id, organization_id, action,
                    resource_type, resource_id, method, path, status_code,
                    ip_address, user_agent, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                datetime.utcnow().isoformat(),
                "stripe_webhook",  # system user
                org_id,
                action,
                "billing",
                event_id,
                "POST",
                "/api/webhooks/stripe",
                200,
                "stripe",
                "stripe-webhook",
                json.dumps({
                    "event_type": event_type,
                    "stripe_customer_id": stripe_customer_id,
                    "result": result,
                    "request_id": request_id,
                    **(metadata or {}),
                }),
            ))
            conn.commit()
    except Exception as e:
        print(f"Billing audit log error: {e}")


# =========================================================================
# STEP 6: STRIPE PRICE → TIER MAPPING
# =========================================================================

# Map Stripe price IDs to ReconAI tiers (free/starter/pro/enterprise)
# Configure these in environment or hardcode for production
STRIPE_PRICE_TIER_MAP = {
    # Starter tier prices
    os.getenv("STRIPE_PRICE_STARTER_MONTHLY", "price_starter_monthly"): "starter",
    os.getenv("STRIPE_PRICE_STARTER_YEARLY", "price_starter_yearly"): "starter",
    # Pro tier prices
    os.getenv("STRIPE_PRICE_PRO_MONTHLY", "price_pro_monthly"): "pro",
    os.getenv("STRIPE_PRICE_PRO_YEARLY", "price_pro_yearly"): "pro",
    # Enterprise tier prices
    os.getenv("STRIPE_PRICE_ENTERPRISE_MONTHLY", "price_enterprise_monthly"): "enterprise",
    os.getenv("STRIPE_PRICE_ENTERPRISE_YEARLY", "price_enterprise_yearly"): "enterprise",
    # Legacy mappings (for backward compatibility)
    "price_individual": "free",
    "price_freelancer": "starter",
    "price_small_business": "pro",
    "price_professional": "pro",
    "price_enterprise": "enterprise",
}


def _map_stripe_price_to_tier(price_id: str) -> str:
    """Map Stripe price ID to ReconAI tier (free/starter/pro/enterprise)."""
    return STRIPE_PRICE_TIER_MAP.get(price_id, "free")


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def verify_stripe_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> tuple[bool, Optional[str]]:
    """
    Verify Stripe webhook signature with replay protection.

    Returns (is_valid, error_message).
    STEP 6: Includes timestamp check to prevent replay attacks.
    """
    if not secret:
        # If no secret configured, skip verification (dev mode)
        # Log warning for production
        if os.getenv("ENVIRONMENT") == "production":
            print("WARNING: STRIPE_WEBHOOK_SECRET not configured in production!")
        return (True, None)

    if not signature:
        return (False, "Missing stripe-signature header")

    try:
        # Parse signature header
        elements = signature.split(',')
        timestamp = None
        signatures = []

        for element in elements:
            if '=' not in element:
                continue
            key, value = element.split('=', 1)
            if key == 't':
                timestamp = value
            elif key == 'v1':
                signatures.append(value)

        if not timestamp:
            return (False, "Missing timestamp in signature")

        if not signatures:
            return (False, "Missing v1 signature")

        # STEP 6: Replay protection — reject events older than tolerance
        event_timestamp = int(timestamp)
        current_timestamp = int(time.time())
        if abs(current_timestamp - event_timestamp) > TIMESTAMP_TOLERANCE:
            return (False, f"Timestamp outside tolerance ({TIMESTAMP_TOLERANCE}s)")

        # Construct signed payload
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"

        # Compute expected signature
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Compare signatures (constant-time comparison)
        if any(hmac.compare_digest(expected_sig, sig) for sig in signatures):
            return (True, None)

        return (False, "Signature mismatch")

    except ValueError as e:
        return (False, f"Invalid timestamp: {e}")
    except Exception as e:
        print(f"Signature verification failed: {str(e)}")
        return (False, f"Verification error: {str(e)}")


def map_stripe_price_to_tier(price_id: str) -> SubscriptionTier:
    """
    Map Stripe price ID to subscription tier (legacy enum).
    STEP 6: Also updates using _map_stripe_price_to_tier for new tier system.
    """
    # Map new tier string to legacy SubscriptionTier enum
    tier_str = _map_stripe_price_to_tier(price_id)
    tier_enum_map = {
        "free": SubscriptionTier.INDIVIDUAL,
        "starter": SubscriptionTier.FREELANCER,
        "pro": SubscriptionTier.SMALL_BUSINESS,
        "enterprise": SubscriptionTier.ENTERPRISE,
    }
    return tier_enum_map.get(tier_str, SubscriptionTier.INDIVIDUAL)


def update_organization_subscription(
    org_id: str,
    tier: SubscriptionTier,
    status: SubscriptionStatus,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    current_period_end: Optional[str] = None,
    price_id: Optional[str] = None,
) -> bool:
    """
    Update organization subscription in database (atomic).

    STEP 6: Server-side authority — tier is set by Stripe webhook, not user input.
    Uses transaction for atomicity.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Enable foreign keys and begin transaction
            conn.execute("PRAGMA foreign_keys = ON")

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

            cursor = conn.execute(
                f"UPDATE organizations SET {set_clause} WHERE id = ?",
                values
            )

            if cursor.rowcount == 0:
                print(f"WARNING: No organization found with id {org_id}")
                return False

            conn.commit()
            return True

    except sqlite3.Error as e:
        print(f"Database error updating subscription: {e}")
        return False


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
# WEBHOOK HANDLERS (STEP 6: Return (org_id, result) for audit logging)
# =========================================================================

def handle_checkout_session_completed(data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """
    Handle checkout.session.completed event.
    STEP 6: New handler for Stripe Checkout flow.
    """
    session = data['object']
    customer_id = session.get('customer')
    subscription_id = session.get('subscription')
    client_reference_id = session.get('client_reference_id')  # org_id passed during checkout

    if not customer_id:
        return (None, "No customer ID in checkout session")

    # Try to find org by client_reference_id first (most reliable)
    org_id = client_reference_id

    # Fallback: find org by customer_id
    if not org_id:
        org_id = get_organization_by_stripe_customer(customer_id)

    if not org_id:
        # Try to link by email
        customer_email = session.get('customer_details', {}).get('email')
        if customer_email:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute("""
                    SELECT o.id FROM organizations o
                    JOIN users u ON o.owner_user_id = u.id
                    WHERE u.email = ?
                """, (customer_email,))
                row = cursor.fetchone()
                if row:
                    org_id = row[0]

    if not org_id:
        return (None, f"Organization not found for customer {customer_id}")

    # Link customer to org if not already linked
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE organizations
            SET stripe_customer_id = ?, stripe_subscription_id = ?, updated_at = datetime('now')
            WHERE id = ? AND (stripe_customer_id IS NULL OR stripe_customer_id = '')
        """, (customer_id, subscription_id, org_id))
        conn.commit()

    return (org_id, f"Checkout completed for org {org_id}, customer {customer_id}")


def handle_customer_subscription_created(data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """Handle subscription.created event"""
    subscription = data['object']
    customer_id = subscription['customer']
    price_id = subscription['items']['data'][0]['price']['id']
    subscription_id = subscription['id']
    current_period_end = datetime.fromtimestamp(subscription['current_period_end']).isoformat()

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return (None, f"Organization not found for customer {customer_id}")

    # Map price to tier
    tier = map_stripe_price_to_tier(price_id)

    # Update organization
    success = update_organization_subscription(
        org_id=org_id,
        tier=tier,
        status=SubscriptionStatus.ACTIVE,
        stripe_subscription_id=subscription_id,
        current_period_end=current_period_end,
        price_id=price_id,
    )

    if not success:
        return (org_id, f"Failed to update subscription for org {org_id}")

    return (org_id, f"Subscription created for org {org_id}, tier: {tier.value}")


def handle_customer_subscription_updated(data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """Handle subscription.updated event"""
    subscription = data['object']
    customer_id = subscription['customer']
    price_id = subscription['items']['data'][0]['price']['id']
    subscription_status = subscription['status']
    current_period_end = datetime.fromtimestamp(subscription['current_period_end']).isoformat()

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return (None, f"Organization not found for customer {customer_id}")

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
    success = update_organization_subscription(
        org_id=org_id,
        tier=tier,
        status=status,
        current_period_end=current_period_end,
        price_id=price_id,
    )

    if not success:
        return (org_id, f"Failed to update subscription for org {org_id}")

    return (org_id, f"Subscription updated for org {org_id}, tier: {tier.value}, status: {status.value}")


def handle_customer_subscription_deleted(data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """Handle subscription.deleted event"""
    subscription = data['object']
    customer_id = subscription['customer']

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return (None, f"Organization not found for customer {customer_id}")

    # Downgrade to individual tier, mark as cancelled
    success = update_organization_subscription(
        org_id=org_id,
        tier=SubscriptionTier.INDIVIDUAL,
        status=SubscriptionStatus.CANCELLED
    )

    if not success:
        return (org_id, f"Failed to cancel subscription for org {org_id}")

    return (org_id, f"Subscription cancelled for org {org_id}, downgraded to free tier")


def handle_invoice_payment_succeeded(data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """Handle invoice.payment_succeeded event"""
    invoice = data['object']
    customer_id = invoice['customer']
    amount_paid = invoice['amount_paid'] / 100  # Convert from cents

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return (None, f"Organization not found for customer {customer_id}")

    # If subscription was past_due, reactivate it
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT subscription_status, tier FROM organizations
            WHERE id = ?
        """, (org_id,))

        row = cursor.fetchone()
        if row and row[0] == SubscriptionStatus.PAST_DUE.value:
            # Preserve existing tier, just update status
            current_tier = row[1] if row[1] else SubscriptionTier.INDIVIDUAL.value
            conn.execute("""
                UPDATE organizations
                SET subscription_status = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (SubscriptionStatus.ACTIVE.value, org_id))
            conn.commit()

    return (org_id, f"Payment succeeded for org {org_id}, amount: ${amount_paid}")


def handle_invoice_payment_failed(data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """Handle invoice.payment_failed event"""
    invoice = data['object']
    customer_id = invoice['customer']

    # Get organization
    org_id = get_organization_by_stripe_customer(customer_id)
    if not org_id:
        return (None, f"Organization not found for customer {customer_id}")

    # Mark subscription as past_due (preserve tier)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE organizations
            SET subscription_status = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (SubscriptionStatus.PAST_DUE.value, org_id))
        conn.commit()

    return (org_id, f"Payment failed for org {org_id}, status: past_due")


def handle_customer_created(data: Dict[str, Any]) -> tuple[Optional[str], str]:
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
            return (org_id, f"Customer linked to org {org_id}")

    return (None, f"Customer created: {customer_id}, no org found for email {email}")


# =========================================================================
# WEBHOOK ENDPOINT (STEP 6: Hardened)
# =========================================================================

@router.post("/stripe", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature")
):
    """
    Handle Stripe webhook events (STEP 6: Hardened)

    Security features:
    - Signature verification (STRIPE_WEBHOOK_SECRET)
    - Timestamp replay protection (5-minute window)
    - Idempotency (event_id dedupe)
    - Structured errors with request_id
    - Full audit logging

    Supported events:
    - checkout.session.completed
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    - customer.created
    """
    # Initialize billing events table
    _init_billing_events_table()

    # Get request_id for structured errors
    request_id = getattr(request.state, "request_id", None)

    try:
        # Get raw body
        payload = await request.body()

        # STEP 6: Verify signature with replay protection
        is_valid, error_message = verify_stripe_signature(
            payload, stripe_signature or "", STRIPE_WEBHOOK_SECRET
        )
        if not is_valid:
            _log_billing_audit(
                event_id="unknown",
                event_type="signature_failed",
                org_id=None,
                stripe_customer_id=None,
                action="BILLING_SIGNATURE_FAILED",
                result=error_message or "Invalid signature",
                request_id=request_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "SIGNATURE_INVALID",
                    "message": error_message or "Invalid signature",
                    "request_id": request_id,
                }
            )

        # Parse event
        event = json.loads(payload)
        event_id = event.get('id', 'unknown')
        event_type = event['type']
        data = event['data']

        # STEP 6: Idempotency check — skip if already processed
        if _is_event_processed(event_id):
            return WebhookResponse(
                received=True,
                event_type=event_type,
                processed=False,
                message="Event already processed (idempotent skip)",
                event_id=event_id,
            )

        # Get customer ID for logging
        stripe_customer_id = None
        obj = data.get('object', {})
        if 'customer' in obj:
            stripe_customer_id = obj['customer']
        elif event_type == 'customer.created':
            stripe_customer_id = obj.get('id')

        # Handle event based on type
        handlers = {
            'checkout.session.completed': handle_checkout_session_completed,
            'customer.subscription.created': handle_customer_subscription_created,
            'customer.subscription.updated': handle_customer_subscription_updated,
            'customer.subscription.deleted': handle_customer_subscription_deleted,
            'invoice.payment_succeeded': handle_invoice_payment_succeeded,
            'invoice.payment_failed': handle_invoice_payment_failed,
            'customer.created': handle_customer_created,
        }

        handler = handlers.get(event_type)
        org_id = None
        message = f"Unhandled event type: {event_type}"
        processed = False

        if handler:
            org_id, message = handler(data)
            processed = True

        # STEP 6: Record event as processed (idempotency)
        _record_event_processed(
            event_id=event_id,
            event_type=event_type,
            stripe_customer_id=stripe_customer_id,
            org_id=org_id,
            result=message,
            metadata={"processed": processed},
        )

        # STEP 6: Audit log the billing event
        action_map = {
            'checkout.session.completed': 'BILLING_CHECKOUT_COMPLETED',
            'customer.subscription.created': 'BILLING_SUBSCRIPTION_CREATED',
            'customer.subscription.updated': 'BILLING_SUBSCRIPTION_UPDATED',
            'customer.subscription.deleted': 'BILLING_SUBSCRIPTION_DELETED',
            'invoice.payment_succeeded': 'BILLING_PAYMENT_SUCCEEDED',
            'invoice.payment_failed': 'BILLING_PAYMENT_FAILED',
            'customer.created': 'BILLING_CUSTOMER_CREATED',
        }
        action = action_map.get(event_type, 'BILLING_EVENT_RECEIVED')

        _log_billing_audit(
            event_id=event_id,
            event_type=event_type,
            org_id=org_id,
            stripe_customer_id=stripe_customer_id,
            action=action,
            result=message,
            request_id=request_id,
            metadata={"processed": processed},
        )

        # Log to console
        print(f"Stripe webhook: {event_type} [{event_id}] - {message}")

        return WebhookResponse(
            received=True,
            event_type=event_type,
            processed=processed,
            message=message,
            event_id=event_id,
        )

    except json.JSONDecodeError as e:
        _log_billing_audit(
            event_id="unknown",
            event_type="parse_error",
            org_id=None,
            stripe_customer_id=None,
            action="BILLING_PARSE_ERROR",
            result=str(e),
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_JSON",
                "message": "Invalid JSON payload",
                "request_id": request_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        _log_billing_audit(
            event_id="unknown",
            event_type="processing_error",
            org_id=None,
            stripe_customer_id=None,
            action="BILLING_PROCESSING_ERROR",
            result=str(e),
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "WEBHOOK_FAILED",
                "message": f"Webhook processing failed: {str(e)}",
                "request_id": request_id,
            }
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
