# app/routers/billing_invoices_api.py
"""
ReconAI Billing — Invoice & Receipt Access (Read-Only)

Endpoints:
- GET /api/billing/invoices - List invoices from Stripe
- GET /api/billing/invoices/{invoice_id} - Get single invoice

Requirements:
- Auth via get_current_context (Depends injection)
- Read-only (no mutations)
- Stripe is source of truth
- Do not expose secrets
- Prefer returning Stripe hosted_invoice_url / invoice_pdf (time-boxed by Stripe)
- RBAC: view_invoices permission required
"""

from __future__ import annotations

import os
import sqlite3
from uuid import uuid4
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth_context import get_current_context, AuthContext
from app.db import DB_PATH
from .billing_rbac import get_billing_actor, require_billing_permission

router = APIRouter(tags=["billing"])

# Optional: Import Stripe SDK if available
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False


def _get_stripe_customer_id(org_id: str) -> Optional[str]:
    """Get Stripe customer ID for an organization."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT stripe_customer_id FROM organizations WHERE id = ?",
            (org_id,)
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None


def _format_invoice(inv: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a Stripe invoice for API response.
    Only expose safe, non-secret fields.
    """
    return {
        "id": inv.get("id"),
        "number": inv.get("number"),
        "status": inv.get("status"),
        "created": inv.get("created"),
        "due_date": inv.get("due_date"),
        "amount_due": inv.get("amount_due"),
        "amount_paid": inv.get("amount_paid"),
        "total": inv.get("total"),
        "currency": inv.get("currency", "usd"),
        "hosted_invoice_url": inv.get("hosted_invoice_url"),
        "invoice_pdf": inv.get("invoice_pdf"),
        "period_start": inv.get("period_start"),
        "period_end": inv.get("period_end"),
        "description": inv.get("description"),
    }


@router.get("/api/billing/invoices")
async def list_invoices(
    ctx: AuthContext = Depends(get_current_context),
    limit: int = 10,
):
    """
    List invoices for the authenticated organization.

    Read-only endpoint - fetches from Stripe.
    Returns hosted_invoice_url and invoice_pdf for user access.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_invoices", request_id)

    # Get Stripe customer ID
    stripe_customer_id = _get_stripe_customer_id(org_id)

    if not stripe_customer_id:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoices": [],
            "notes": "No Stripe customer linked to this organization",
        }

    # Check Stripe configuration
    stripe_secret = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret:
        env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
        if env == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "STRIPE_NOT_CONFIGURED",
                    "message": "Stripe API key not configured",
                    "request_id": request_id,
                }
            )
        # Dev mode - return stub
        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoices": [],
            "notes": "Stripe not configured (dev mode)",
        }

    if not STRIPE_AVAILABLE:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoices": [],
            "notes": "Stripe SDK not installed",
        }

    # Fetch invoices from Stripe
    try:
        stripe.api_key = stripe_secret
        invoices = stripe.Invoice.list(
            customer=stripe_customer_id,
            limit=min(limit, 100),  # Cap at 100
        )

        formatted = [_format_invoice(inv) for inv in invoices.data]

        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoices": formatted,
            "has_more": invoices.has_more,
        }

    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "STRIPE_API_ERROR",
                "message": str(e.user_message) if hasattr(e, 'user_message') else "Stripe API error",
                "request_id": request_id,
            }
        )


@router.get("/api/billing/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    ctx: AuthContext = Depends(get_current_context),
):
    """
    Get a single invoice by ID.

    Read-only endpoint - fetches from Stripe.
    Validates invoice belongs to organization's customer.
    """
    request_id = str(uuid4())
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    if not invoice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "MISSING_INVOICE_ID",
                "message": "Invoice ID is required",
                "request_id": request_id,
            }
        )

    # RBAC check
    actor = get_billing_actor(user_id, org_id)
    require_billing_permission(actor, "view_invoices", request_id)

    # Get Stripe customer ID
    stripe_customer_id = _get_stripe_customer_id(org_id)

    if not stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "NO_STRIPE_CUSTOMER",
                "message": "No Stripe customer linked to this organization",
                "request_id": request_id,
            }
        )

    # Check Stripe configuration
    stripe_secret = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret:
        env = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV")
        if env == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "STRIPE_NOT_CONFIGURED",
                    "message": "Stripe API key not configured",
                    "request_id": request_id,
                }
            )
        # Dev mode - return stub
        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoice_id": invoice_id,
            "invoice": None,
            "notes": "Stripe not configured (dev mode)",
        }

    if not STRIPE_AVAILABLE:
        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoice_id": invoice_id,
            "invoice": None,
            "notes": "Stripe SDK not installed",
        }

    # Fetch invoice from Stripe
    try:
        stripe.api_key = stripe_secret
        invoice = stripe.Invoice.retrieve(invoice_id)

        # Validate ownership - invoice must belong to org's customer
        if invoice.customer != stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "INVOICE_ACCESS_DENIED",
                    "message": "Invoice does not belong to this organization",
                    "request_id": request_id,
                }
            )

        return {
            "request_id": request_id,
            "org_id": org_id,
            "invoice_id": invoice_id,
            "invoice": _format_invoice(invoice),
        }

    except stripe.error.InvalidRequestError as e:
        if "No such invoice" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "INVOICE_NOT_FOUND",
                    "message": f"Invoice {invoice_id} not found",
                    "request_id": request_id,
                }
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "STRIPE_REQUEST_ERROR",
                "message": str(e.user_message) if hasattr(e, 'user_message') else str(e),
                "request_id": request_id,
            }
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "STRIPE_API_ERROR",
                "message": str(e.user_message) if hasattr(e, 'user_message') else "Stripe API error",
                "request_id": request_id,
            }
        )
